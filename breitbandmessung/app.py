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

from flask import Flask, Response, jsonify, redirect, render_template_string

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
            wait = WebDriverWait(browser, 35)
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#allow-necessary"))).click()
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn:nth-child(4)"))).click()
            wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn:nth-child(2)"))).click()

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


PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui,sans-serif;margin:24px;background:#f6f8fa;color:#18212b}
main{max-width:1000px;margin:auto}.panel{background:white;padding:18px;border-radius:12px;
margin:12px 0;box-shadow:0 1px 5px #0001}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:9px;border-bottom:1px solid #ddd}
button,a.action{background:#1684c6;color:white;border:0;padding:10px 14px;
border-radius:7px;cursor:pointer;text-decoration:none}small{color:#666}.scroll{overflow:auto}
</style></head><body><main><h2>Breitbandmessung Logger</h2>
<div class="panel"><p><b>Status:</b> {{status.message}}</p>
<p><b>Messungen pro Tag:</b> {{cfg.tests_per_day}} · <b>Zeitzone:</b> {{cfg.timezone}}</p>
<form method="post" action="run"><button type="submit" {% if status.running %}disabled{% endif %}>
Jetzt messen</button> <a class="action" href="export.csv">CSV exportieren</a></form>
<p><small>Messhäufigkeit im Add-on unter Konfiguration einstellen.</small></p></div>
<div class="panel scroll"><h3>Letzte Messungen</h3><table><thead><tr>
<th>Zeit</th><th>Quelle</th><th>Download</th><th>Upload</th><th>Ping</th><th>Status</th>
</tr></thead><tbody>{% for r in rows %}<tr><td>{{r.started_at[:19].replace('T',' ')}}</td>
<td>{{r.source}}</td>
<td>{{'%.2f'|format(r.download_mbps) if r.download_mbps is not none else '–'}}</td>
<td>{{'%.2f'|format(r.upload_mbps) if r.upload_mbps is not none else '–'}}</td>
<td>{{'%.1f'|format(r.ping_ms) if r.ping_ms is not none else '–'}}</td>
<td title="{{r.error or ''}}">{{r.status}}</td></tr>{% endfor %}</tbody></table>
<p><small>Download/Upload in Mbit/s, Ping in ms. Letzte 100 Einträge.</small></p>
</div></main></body></html>"""


@app.get("/")
def home():
    with connection() as conn:
        rows = conn.execute("SELECT * FROM measurements ORDER BY id DESC LIMIT 100").fetchall()
    return render_template_string(PAGE, cfg=settings(), status=status, rows=rows)


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
