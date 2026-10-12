# Breitbandmessung Logger

Inoffizielles Home-Assistant-Add-on (**amd64**) für automatisierte Webmessungen auf https://breitbandmessung.de/test.

- `tests_per_day`: 1–24 Messungen pro Tag, gleichmäßig verteilte Slots
- `timezone`: Zeitzone, standardmäßig `Europe/Berlin`
- `run_on_start`: optionaler Test beim Start
- `timeout_minutes`: maximal zulässige Messdauer
- Messungen, Fehler und Original-CSV werden dauerhaft in `/data/measurements.sqlite3` gespeichert
- Dashboard via Home-Assistant-Ingress, manuelle Messung und CSV-Export

## Installation

1. Home Assistant → **Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories**.
2. Die URL `https://github.com/ManuelDeV-exe/ha-breitbandmessung` hinzufügen.
3. **Breitbandmessung Logger** installieren, konfigurieren und starten.
4. **Weboberfläche öffnen**.

## Wichtige Einschränkungen

Dies ist eine experimentelle Browserautomatisierung und **keine offizielle Anwendung der Bundesnetzagentur**. Selektoren der Website können sich ändern; bei Problemen Log prüfen. Die Resultate sind **kein Ersatz für eine rechtlich anerkannte Messkampagne**. Tests verbrauchen Datenvolumen und können die Verbindung belasten. Eine Messung wird nur dann als erfolgreich protokolliert, wenn die Website eine auswertbare CSV liefert. Ausfälle werden mit Fehlertext gespeichert. Bei Neustart während einer laufenden Messung kann ein Slot erneut anlaufen.

Die Browserinteraktion orientiert sich konzeptionell an https://github.com/Shnezzin/breitbandmessung (kein Quellcode kopiert).

## Neu in 0.2.0

- **Soll-/Ist-Vergleich** mit Tarifprofilen von Telekom, Vodafone Kabel und O2 sowie **Benutzerdefiniert** (Down-/Upload in Mbit/s).
- Prozentuale Zielerreichung anhand der **letzten erfolgreichen Messung**. Tarifwerte sind beispielhafte maximale beworbene Werte, keine vertraglichen Mindestgeschwindigkeiten.
- Einzelne Datensätze mit Rückfrage löschen oder **alle Messungen** mit Sicherheitsabfrage entfernen. Löschaktionen sind während laufender Messungen gesperrt.
- Weiterhin vollständiger CSV-Export aller vorhandenen Daten.
- Die neueste importierte Fehler-CSV enthält einen erfolgreichen Test (30,69/5,30 Mbit/s); die früheren Fehlermeldungen stammen vom verdeckten Button. Der Workaround bleibt aktiv; die Webautomation muss weiterhin praktisch überprüft werden.

Quellen zu Beispieltarifen: [Telekom](https://www.telekom.de/agb/downloads/55504.pdf), [Vodafone](https://www.vodafone.de/media/downloads/pdf/KH_09868_screen_2610.pdf), [O2](https://www.o2online.de/internet-festnetz/internetanschluss/).

## Neu in 0.3.0: Dark Mode und Diagramme

- Darstellung **Auto / Hell / Dunkel**. Im Auto-Modus wird die Betriebssystem- bzw. Browser-Einstellung verwendet; die manuelle Wahl wird lokal im Browser gespeichert.
- Zwei interaktive Zeitraumfilter-Diagramme ohne externe JavaScript-Abhängigkeiten: **Download + Upload in Mbit/s** und **Ping in ms**.
- Zeiträume **7 / 30 / 90 Tage / Gesamt** und Kennzahlen zu Durchschnitt, Sollwerterreichung und Erfolgsquote.
- Diagramme basieren auf den in SQLite vorhandenen Datensätzen und berücksichtigen im Zeitverlauf nur erfolgreiche Messungen.
- Die Schaltfläche **Löschen** kann seit 0.2.2 auch während einer laufenden Messung genutzt werden.
