"""Unofficial Home Assistant add-on: browser-based breitbandmessung.de measurements."""
import csv
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, render_template_string, request, abort

DATA = Path(os.environ.get("BBM_DATA", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "measurements.sqlite3"
OPTIONS = DATA / "options.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("breitbandmessung")
app = Flask(__name__)
lock = threading.Lock()
status = {"running": False, "message": "Bereit", "last_attempt": None}


def settings():
    options = {"tests_per_day": 4, "timezone": "Europe/Berlin",
               "run_on_start": False, "timeout_minutes": 12}
    if OPTIONS.exists():
        options.update(json.loads(OPTIONS.read_text(encoding="utf-8")))
    options["tests_per_day"] = max(1, min(24, int(options["tests_per_day"])))
    options["timeout_minutes"] = max(3, min(30, int(options["timeout_minutes"])))
    ZoneInfo(options["timezone"])
    return options

TARIFFS = [
 ("custom","Benutzerdefiniert",0,0),
 ("telekom_m","Telekom MagentaZuhause M",50,10),
 ("telekom_l","Telekom MagentaZuhause L",100,40),
 ("telekom_xl","Telekom MagentaZuhause XL",250,40),
 ("vodafone_100","Vodafone Kabel 100",100,50),
 ("vodafone_250","Vodafone Kabel 250",250,50),
 ("vodafone_500","Vodafone Kabel 500",500,50),
 ("vodafone_1000","Vodafone Kabel 1000",1000,50),
 ("o2_m","O2 Home M",150,75),
 ("o2_l","O2 Home L",300,75),
 ("o2_xl","O2 Home XL",600,75),
 ("o2_xxl","O2 Home XXL",1000,75),
]
TARGET_PATH = DATA / "target.json"

def get_target():
    result = {"tariff":"custom", "download":300.0, "upload":150.0}
    if TARGET_PATH.exists():
        try:
            result.update(json.loads(TARGET_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.warning("Ungültige Tarif-Konfiguration")
    return result


def connection():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
            local_date TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
            download_mbps REAL, upload_mbps REAL, ping_ms REAL,
            error TEXT, raw_csv TEXT)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON measurements(local_date, source)")


def measure(timeout_minutes):
    """Run the actual site's web test and parse the site's exported result CSV."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    with tempfile.TemporaryDirectory(prefix="bbm-") as folder:
        options = Options()
        options.add_argument("-headless")
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", folder)
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk",
                               "text/csv,application/csv,application/octet-stream,application/force-download")
        browser = webdriver.Firefox(options=options, service=Service("/usr/bin/geckodriver"))
        try:
            browser.set_page_load_timeout(60)
            browser.get("https://breitbandmessung.de/test")
            # The website has animated overlays; Selenium's "clickable" state
            # alone does not guarantee that an element is unobstructed.
            from selenium.common.exceptions import (
                ElementClickInterceptedException, StaleElementReferenceException,
                TimeoutException, NoSuchElementException,
            )

            def click_when_ready(selector, label, timeout=45):
                deadline = time.monotonic() + timeout
                last_error = None
                while time.monotonic() < deadline:
                    try:
                        element = browser.find_element(By.CSS_SELECTOR, selector)
                        if not element.is_displayed() or not element.is_enabled():
                            time.sleep(0.6)
                            continue
                        browser.execute_script(
                            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                            element,
                        )
                        time.sleep(0.4)
                        try:
                            element.click()
                        except ElementClickInterceptedException as exc:
                            # Fall back to a DOM click for a known visible/enabled
                            # button when a transparent/animated overlay intercepts.
                            last_error = exc
                            browser.execute_script("arguments[0].click();", element)
                        log.info("Website step completed: %s", label)
                        return
                    except (NoSuchElementException, StaleElementReferenceException,
                            ElementClickInterceptedException) as exc:
                        last_error = exc
                        time.sleep(0.8)
                raise TimeoutError(
                    f"Website button '{label}' ({selector}) not available: {last_error}"
                )

            click_when_ready("#allow-necessary", "Cookies")
            time.sleep(2)
            click_when_ready("button.btn:nth-child(4)", "Start")
            time.sleep(1)
            click_when_ready("button.btn:nth-child(2)", "Datenschutz")

            deadline = time.monotonic() + timeout_minutes * 60
            while time.monotonic() < deadline:
                if "abgeschlossen" in browser.find_element(By.TAG_NAME, "body").text.lower():
                    browser.find_element(By.CSS_SELECTOR, "button.px-0:nth-child(1)").click()
                    break
                time.sleep(3)
            else:
                raise TimeoutError("Messung hat das Zeitlimit überschritten")

            for _ in range(30):
                files = [p for p in Path(folder).glob("*.csv") if p.stat().st_size > 0]
                if files and not list(Path(folder).glob("*.part")):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Die Website hat keine fertige CSV-Datei geliefert")

            raw = max(files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8-sig")
            record = next(csv.DictReader(io.StringIO(raw), delimiter=";"))

            def numeric(key):
                value = record[key].strip().replace(",", ".")
                found = re.search(r"-?\d+(?:\.\d+)?", value)
                if not found:
                    raise ValueError(f"Ungültiger Messwert: {key}={value}")
                return float(found.group())

            return (numeric("Download (Mbit/s)"), numeric("Upload (Mbit/s)"),
                    numeric("Laufzeit (ms)"), raw)
        finally:
            browser.quit()


def run_test(source):
    if not lock.acquire(blocking=False):
        return False

    status["running"] = True
    status["message"] = "Messung läuft"

    def worker():
        start = datetime.now(ZoneInfo("Europe/Berlin"))
        result = {"download_mbps": None, "upload_mbps": None, "ping_ms": None,
                  "raw_csv": None, "error": None, "status": "ok"}
        try:
            cfg = settings()
            zone = ZoneInfo(cfg["timezone"])
            start = datetime.now(zone)
            status["last_attempt"] = start.isoformat()
            dl, ul, ping, raw = measure(cfg["timeout_minutes"])
            result.update(download_mbps=dl, upload_mbps=ul, ping_ms=ping, raw_csv=raw)
            status["message"] = f"Erfolgreich: {dl:.2f} ↓ / {ul:.2f} ↑ Mbit/s"
            log.info("Download %.2f Mbit/s, Upload %.2f Mbit/s, Ping %.2f ms", dl, ul, ping)
        except Exception as exc:
            result.update(status="error", error=str(exc)[:1000])
            status["message"] = f"Fehler: {exc}"
            log.exception("Messung fehlgeschlagen")
        finally:
            end = datetime.now(start.tzinfo)
            try:
                with connection() as conn:
                    conn.execute("""INSERT INTO measurements
                        (started_at, finished_at, local_date, source, status,
                         download_mbps, upload_mbps, ping_ms, error, raw_csv)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (start.isoformat(), end.isoformat(), start.date().isoformat(),
                         source, result["status"], result["download_mbps"],
                         result["upload_mbps"], result["ping_ms"],
                         result["error"], result["raw_csv"]))
            except Exception:
                log.exception("Datenbankfehler beim Speichern")
            finally:
                status["running"] = False
                lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def scheduler():
    """One attempt per slot/day, including failures (daylight saving aware by local date)."""
    while True:
        try:
            cfg = settings()
            now = datetime.now(ZoneInfo(cfg["timezone"]))
            count = cfg["tests_per_day"]
            minute = now.hour * 60 + now.minute
            slot = min(count - 1, minute * count // 1440)
            slot_start = (slot * 1440 + count - 1) // count
            source = f"slot:{slot}"
            with connection() as conn:
                prior = conn.execute(
                    "SELECT 1 FROM measurements WHERE local_date=? AND source=? LIMIT 1",
                    (now.date().isoformat(), source)).fetchone()
            if slot_start <= minute < slot_start + 10 and not prior and not status["running"]:
                run_test(source)
        except Exception:
            log.exception("Schedulerfehler")
        time.sleep(30)


PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:15px system-ui;background:#f5f7f9;color:#202832;margin:18px}main{max-width:1100px;margin:auto}
section{background:white;padding:18px;margin:12px 0;border-radius:12px;box-shadow:0 1px 4px #0002}
table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #ddd}
.wrap{overflow-x:auto}input,select{padding:9px;border-radius:6px;border:1px solid #bbb;margin:5px}
button,.btn{border:0;border-radius:6px;padding:10px 14px;background:#178ac9;color:white;cursor:pointer;text-decoration:none}
.danger{background:#bd2929}.grid{display:flex;gap:10px;flex-wrap:wrap}.metric{background:#eaf4fb;border-radius:9px;padding:15px;flex:1;min-width:180px}
.metric b{display:block;font-size:23px}</style></head><body><main><h2>Breitbandmessung Logger</h2>
<section><p><b>Status:</b> {{status.message}}</p><p>Messungen pro Tag: {{cfg.tests_per_day}} · Zeitzone: {{cfg.timezone}}</p>
<form method="post" action="run"><button {% if status.running %}disabled{% endif %}>Jetzt messen</button>
<a class="btn" href="export.csv">CSV exportieren</a></form></section>
<section><h3>Soll-/Ist-Vergleich</h3><form method="post" action="target">
<label>Tarif <select id="tariff" name="tariff" onchange="tarifwahl()">
{% for t in tariffs %}<option value="{{t[0]}}" data-down="{{t[2]}}" data-up="{{t[3]}}" {% if t[0]==tariff.tariff %}selected{% endif %}>{{t[1]}}</option>{% endfor %}
</select></label>
<label>Download Soll (Mbit/s) <input id="down" name="download" type="number" step="0.01" min="0.01" max="100000" required value="{{tariff.download}}"></label>
<label>Upload Soll (Mbit/s) <input id="up" name="upload" type="number" step="0.01" min="0.01" max="100000" required value="{{tariff.upload}}"></label>
<button>Tarif speichern</button></form>
<p><small>Tarife zeigen beispielhafte beworbene Maximalgeschwindigkeiten. Für verbindliche Werte deinen Vertrag bzw. das Produktinformationsblatt prüfen.</small></p>
{% if last %}<div class="grid">
<div class="metric">Download Ist <b>{{'%.2f'|format(last.download_mbps)}} Mbit/s</b>
Soll {{tariff.download}} · {{'%.1f'|format(last.download_mbps / tariff.download * 100)}} % erreicht</div>
<div class="metric">Upload Ist <b>{{'%.2f'|format(last.upload_mbps)}} Mbit/s</b>
Soll {{tariff.upload}} · {{'%.1f'|format(last.upload_mbps / tariff.upload * 100)}} % erreicht</div>
<div class="metric">Ping Ist <b>{{'%.1f'|format(last.ping_ms)}} ms</b>Kein Sollwert festgelegt</div></div>
<p><small>Letzte erfolgreiche Messung: {{last.started_at[:19].replace('T',' ')}}</small></p>
{% else %}<p>Noch keine erfolgreiche Messung vorhanden.</p>{% endif %}</section>
<section class="wrap"><h3>Messprotokoll ({{total}} Datensätze)</h3><table><thead><tr><th>Zeit</th><th>Quelle</th><th>Download</th><th>Upload</th><th>Ping</th><th>Status</th><th>Löschen</th></tr></thead>
<tbody>{% for r in rows %}<tr><td>{{r.started_at[:19].replace('T',' ')}}</td><td>{{r.source}}</td>
<td>{{'%.2f'|format(r.download_mbps) if r.download_mbps is not none else '–'}}</td>
<td>{{'%.2f'|format(r.upload_mbps) if r.upload_mbps is not none else '–'}}</td>
<td>{{'%.1f'|format(r.ping_ms) if r.ping_ms is not none else '–'}}</td><td title="{{r.error or ''}}">{{r.status}}</td>
<td><form method="post" action="delete/{{r.id}}" onsubmit="return confirm('Datensatz endgültig löschen?')">
<button class="danger">Löschen</button></form></td></tr>{% endfor %}</tbody></table>
<p><small>Nur die letzten 100 werden angezeigt, CSV exportiert alle.</small></p>
<form method="post" action="delete-all" onsubmit="return confirm('ACHTUNG: ALLE Messungen endgültig löschen?')">
<button class="danger">Alle Messungen löschen</button></form></section>
<script>function tarifwahl(){let t=document.getElementById('tariff'),o=t.selectedOptions[0];
if(t.value!=='custom'){document.getElementById('down').value=o.dataset.down;document.getElementById('up').value=o.dataset.up;}}</script>
</main></body></html>"""


@app.get("/")
def home():
    with connection() as conn:
        rows = conn.execute("SELECT * FROM measurements ORDER BY id DESC LIMIT 100").fetchall()
        last = conn.execute("SELECT * FROM measurements WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        total = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    return render_template_string(PAGE, cfg=settings(), status=status, rows=rows,
                                  last=last, total=total, tariff=get_target(), tariffs=TARIFFS)


@app.post("/target")
def save_target():
    key = request.form.get("tariff")
    matching = next((t for t in TARIFFS if t[0] == key), None)
    if not matching:
        abort(400)
    try:
        down = float(request.form.get("download", "0"))
        up = float(request.form.get("upload", "0"))
    except ValueError:
        abort(400)
    if not (0 < down <= 100000 and 0 < up <= 100000):
        abort(400)
    # Predefined speeds are fixed; manual numbers apply to Custom.
    if key != "custom":
        down, up = matching[2], matching[3]
    TARGET_PATH.write_text(json.dumps({"tariff":key,"download":down,"upload":up}), encoding="utf-8")
    return redirect("./", code=303)


@app.post("/delete/<int:record_id>")
def delete_one(record_id):
    if status["running"]:
        abort(409)
    with connection() as conn:
        conn.execute("DELETE FROM measurements WHERE id=?", (record_id,))
    return redirect("../", code=303)


@app.post("/delete-all")
def delete_all():
    if status["running"]:
        abort(409)
    with connection() as conn:
        conn.execute("DELETE FROM measurements")
    return redirect("./", code=303)


@app.post("/run")
def manual():
    run_test("manual")
    return redirect("./", code=303)


@app.get("/api/latest")
def latest():
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM measurements WHERE status='ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return jsonify(dict(row) if row else {})


@app.get("/export.csv")
def export():
    with connection() as conn:
        rows = conn.execute(
            """SELECT started_at, finished_at, source, status, download_mbps,
            upload_mbps, ping_ms, error FROM measurements ORDER BY id"""
        ).fetchall()
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["Start", "Ende", "Quelle", "Status", "Download_Mbit_s",
                     "Upload_Mbit_s", "Ping_ms", "Fehler"])
    writer.writerows([tuple(row) for row in rows])
    return Response(stream.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=breitbandmessung.csv"})


if __name__ == "__main__":
    init_db()
    if settings()["run_on_start"]:
        run_test("startup")
    threading.Thread(target=scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=8099, threaded=True)
