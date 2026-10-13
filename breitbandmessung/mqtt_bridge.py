"""Optional MQTT discovery integration for HA dashboard charts and test button."""
import json
import logging
import os
import threading
import time

import paho.mqtt.client as mqtt
import requests

log = logging.getLogger("breitbandmessung.mqtt")
BASE = "breitbandmessung"
STATE_TOPIC = BASE + "/state"
COMMAND_TOPIC = BASE + "/command/test"
AVAIL_TOPIC = BASE + "/availability"
DEVICE = {"identifiers": ["breitbandmessung_logger"],
          "name": "Breitbandmessung Logger", "manufacturer": "Community",
          "model": "Breitbandmessung Webtest"}

SENSORS = [
    ("download", "Download", "Mbit/s", "measurement", None),
    ("upload", "Upload", "Mbit/s", "measurement", "data_rate"),
    ("ping", "Ping", "ms", "measurement", None),
    ("download_percent", "Download Soll erreicht", "%", "measurement", None),
    ("upload_percent", "Upload Soll erreicht", "%", "measurement", None),
    ("tests", "Messungen gesamt", None, "measurement", None),
    ("tests_success", "Erfolgreiche Messungen", None, "measurement", None),
    ("tests_error", "Fehlgeschlagene Messungen", None, "measurement", None),
]


class MqttBridge:
    def __init__(self, db_connect, target_getter, start_test):
        self.db_connect = db_connect
        self.target_getter = target_getter
        self.start_test = start_test
        self.client = None
        self.connected = False
        self.last_state = None

    def _discovery(self, client):
        for key, title, unit, state_class, device_class in SENSORS:
            config = {
                "name": title, "unique_id": "bbm_" + key,
                "default_entity_id": "sensor.breitbandmessung_" + key,
                "state_topic": STATE_TOPIC,
                "value_template": "{{ value_json." + key + " }}",
                "availability_topic": AVAIL_TOPIC,
                "device": DEVICE,
                "state_class": state_class,
            }
            if unit:
                config["unit_of_measurement"] = unit
            if device_class:
                config["device_class"] = device_class
            client.publish(
                f"homeassistant/sensor/bbm_{key}/config", json.dumps(config),
                qos=1, retain=True
            )
        button = {
            "name": "Messung starten", "unique_id": "bbm_start",
            "default_entity_id": "button.breitbandmessung_messung_starten",
            "command_topic": COMMAND_TOPIC, "payload_press": "PRESS",
            "availability_topic": AVAIL_TOPIC, "device": DEVICE,
        }
        client.publish("homeassistant/button/bbm_start/config",
                       json.dumps(button), qos=1, retain=True)

    def start(self):
        threading.Thread(target=self._loop, daemon=True,
                         name="bbm-mqtt").start()

    def _loop(self):
        while True:
            try:
                token = os.environ.get("SUPERVISOR_TOKEN")
                if not token:
                    raise RuntimeError("Kein Supervisor-Token")
                resp = requests.get("http://supervisor/services/mqtt",
                                    headers={"Authorization": "Bearer " + token},
                                    timeout=8)
                resp.raise_for_status()
                info = resp.json().get("data", {})
                if not info or not info.get("host"):
                    raise RuntimeError("MQTT-Service nicht verfügbar (Mosquitto installieren)")
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                     client_id="breitbandmessung-logger")
                if info.get("username"):
                    client.username_pw_set(info["username"], info.get("password"))
                if info.get("ssl"):
                    import ssl
                    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                def on_connect(client, userdata, flags, reason_code, properties):
                    if reason_code == 0:
                        self.connected = True
                        self._discovery(client)
                        client.publish(AVAIL_TOPIC, "online", qos=1, retain=True)
                        client.subscribe(COMMAND_TOPIC)
                        self.last_state = None
                    else:
                        self.connected = False
                def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
                    self.connected = False
                def on_message(client, userdata, message):
                    if message.topic == COMMAND_TOPIC and message.payload == b"PRESS":
                        if self.start_test("dashboard"):
                            log.info("Speedtest vom Home-Assistant-Dashboard gestartet")
                        else:
                            log.info("Dashboard-Speedtest ignoriert: Messung läuft bereits")
                client.on_connect = on_connect
                client.on_disconnect = on_disconnect
                client.on_message = on_message
                client.will_set(AVAIL_TOPIC, "offline", qos=1, retain=True)
                client.connect(info["host"], int(info.get("port", 1883)), keepalive=60)
                self.client = client
                client.loop_start()
                try:
                    for _ in range(20):
                        if client.is_connected():
                            break
                        time.sleep(0.5)
                    if not client.is_connected():
                        raise RuntimeError('MQTT-Verbindungsaufbau fehlgeschlagen')
                    while client.is_connected():
                        self.publish_state()
                        time.sleep(15)
                finally:
                    self.connected = False
                    client.loop_stop()
                    client.disconnect()
            except Exception as err:
                log.warning("MQTT-Verbindung nicht bereit: %s", err)
            time.sleep(60)

    def publish_state(self):
        if not self.connected or not self.client:
            return
        with self.db_connect() as conn:
            latest = conn.execute(
                "SELECT * FROM measurements WHERE status='ok' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            counts = conn.execute(
                "SELECT status, COUNT(*) AS n FROM measurements GROUP BY status"
            ).fetchall()
            success_count = sum(int(r["n"]) for r in counts if r["status"] == "ok")
            error_count = sum(int(r["n"]) for r in counts if r["status"] != "ok")
            total = success_count + error_count
        target = self.target_getter()
        state = {"tests": total, "tests_success": success_count, "tests_error": error_count}
        if latest:
            down = float(latest["download_mbps"])
            up = float(latest["upload_mbps"])
            state.update(
                download=down, upload=up, ping=float(latest["ping_ms"]),
                download_percent=round(down / target["download"] * 100, 2),
                upload_percent=round(up / target["upload"] * 100, 2),
            )
        serialized = json.dumps(state)
        if serialized != self.last_state:
            self.client.publish(STATE_TOPIC, serialized, qos=1, retain=True)
            self.last_state = serialized
