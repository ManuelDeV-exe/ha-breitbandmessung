# Home Assistant Breitbandmessung Logger

Inoffizielles Home Assistant Add-on (amd64) für automatisierte Tests auf [breitbandmessung.de](https://breitbandmessung.de/test).

## Installation

In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories** und `https://github.com/ManuelDeV-exe/ha-breitbandmessung` eintragen. Anschließend **Breitbandmessung Logger** installieren und starten.

## Funktionen

- 1 bis 24 Tests täglich, verteilt über 24 Stunden
- Firefox-basierte automatisierte Messung auf der Website
- Protokollierung von Download, Upload, Ping und Fehlern in SQLite (`/data`)
- CSV-Export, Weboberfläche via Home Assistant Ingress und manuelle Tests

**Wichtig:** Experimentelle Browserautomation, nicht die offizielle Desktop-App der Bundesnetzagentur; kein Ersatz für eine rechtlich relevante Messkampagne. Die Website kann sich ändern und die Messautomation beeinträchtigen.

Details: [Add-on README](breitbandmessung/README.md).
