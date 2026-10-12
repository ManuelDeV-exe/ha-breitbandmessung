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
