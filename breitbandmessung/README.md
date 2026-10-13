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

## 0.4.0 – Benutzerrechte und Home-Assistant-Dashboard

### Rollen in der Add-on-Weboberfläche
Die Weboberfläche ist weiterhin für alle berechtigten Home-Assistant-Nutzer über **Ingress** sichtbar.
Sie erkennt die HA-Benutzer-ID über den vom Supervisor gesetzten `X-Remote-User-Id`-Header und fragt die Benutzergruppen bei Home Assistant ab. Nur **Administratoren** können hier:
- Messungen manuell starten,
- Tarif/Sollwerte ändern,
- einzelne bzw. alle Messdaten löschen.

Normale Benutzer sehen die Werte, Tabellen, Statistiken und Diagramme (und können die CSV exportieren). Geschützte Aktionen sind serverseitig mit 403 gesperrt, selbst bei direktem HTTP-POST. Bei fehlender Rollenprüfung werden **keine Administratorrechte** vergeben. Die Weboberfläche ist nur über Home Assistant Ingress zugänglich.

### Dashboard-Integration mittels MQTT
Das Add-on veröffentlicht automatisch MQTT Discovery-Entitäten, wenn ein kompatibler MQTT-Dienst vorhanden ist. Installiere dafür bei Bedarf das **Mosquitto Broker Add-on** und richte unter **Einstellungen → Geräte & Dienste** die **MQTT-Integration** ein.

Erstellt werden:
- `sensor.breitbandmessung_download`, `sensor.breitbandmessung_upload`
- `sensor.breitbandmessung_ping`
- `sensor.breitbandmessung_download_percent`, `sensor.breitbandmessung_upload_percent`
- `sensor.breitbandmessung_tests`
- `button.breitbandmessung_messung_starten`

Die realen Entitäts-IDs können bei bestehenden Einträgen oder Namenskonflikten abweichen. Prüfe sie unter **Entwicklerwerkzeuge → Zustände**.

Für einen direkt einsetzbaren Dashboard-Baustein siehe [dashboard.yaml](../dashboard.yaml). Im Dashboard **Bearbeiten → Karte hinzufügen → Manuell** und den YAML-Inhalt einfügen.

**Rechtehinweis:** Der MQTT-Button wird von Home Assistant selbst bereitgestellt. Die Berechtigung, ihn im Dashboard zu bedienen, wird über die Home-Assistant-Entitäts-/Dashboardrechte geregelt. Er ist **nicht automatisch auf Administratoren beschränkt**. In der Add-on-Weboberfläche ist der manuelle Start dagegen adminpflichtig. Wenn Standardbenutzer überhaupt keine Tests starten sollen, den MQTT-Button nur auf einem administrativen Dashboard platzieren und Zugriffsrechte entsprechend setzen.

Die MQTT-Anbindung ist optional. Ohne MQTT bleiben die Add-on-Oberfläche, SQLite-Speicherung und CSV-Export nutzbar. Bereits gespeicherte Messdaten bleiben bei einem normalen Update erhalten.

### Hinweise zur Absicherung
Keine zusätzlichen Netzwerkports am Host veröffentlichen. Die Administrationsberechtigung wird serverseitig anhand der Benutzer-ID geprüft; eigene reverse proxies dürfen die Ingress-Header nicht ungeprüft selbst setzen. Dieses Release wurde noch nicht in einer realen Home-Assistant-Installation durchgetestet.

## 0.4.3 – Gemeinsames Dashboard und Tortendiagramm

- In der Add-on-Weboberfläche zeigt das neue Donut-/Tortendiagramm erfolgreiche gegen fehlgeschlagene Messversuche; der gewählte Zeitraum (7/30/90 Tage/Gesamt) wird berücksichtigt.
- Für Home Assistant stehen zusätzlich die MQTT-Entitäten `sensor.breitbandmessung_tests_success` und `sensor.breitbandmessung_tests_error` zur Verfügung.
- Ein optionales Tortendiagramm für Lovelace ist unter [dashboard_pie.yaml](../dashboard_pie.yaml) hinterlegt. Es benötigt die **ApexCharts Card** aus HACS.
- Das normale Messwerte-Dashboard ist weiter unter [dashboard.yaml](../dashboard.yaml) verfügbar.

### Dashboard für alle Home-Assistant-Benutzer sichtbar machen

**Wichtig:** Eine in GitHub gespeicherte Lovelace-Vorlage erscheint nicht automatisch als Dashboard bei allen Benutzern. Das Add-on kann ein vorhandenes Home-Assistant-Dashboard nicht ohne weitere Einrichtung global anlegen oder dessen Benutzersichtbarkeit einstellen.

1. Home Assistant als Administrator öffnen → **Einstellungen → Dashboards** → neues Dashboard `Breitbandmessung` erstellen.
2. Option **Nur für Administratoren** **deaktivieren**, **In Seitenleiste anzeigen** aktivieren und nicht auf einzelne Benutzer einschränken.
3. Dashboard bearbeiten → **Karte hinzufügen → Manuell**, Inhalt aus `dashboard.yaml` einfügen.
4. Optional HACS → ApexCharts Card installieren, dann `dashboard_pie.yaml` als **weitere** manuelle Karte hinzufügen.
5. Als normaler Benutzer ab- und wieder anmelden und die Sichtbarkeit prüfen.

Die Add-on-Seitenleiste hat schon `panel_admin: false`, sofern die Home-Assistant-Installation die Ingress-Freigabe für Nicht-Administratoren unterstützt.

**Sicherheit:** Der MQTT-Startbutton ist nicht durch die Add-on-Weboberflächen-Rechteprüfung geschützt. Auf einem Dashboard für alle Benutzer kann er von Benutzern mit entsprechender Home-Assistant-Berechtigung ausgelöst werden. Für ein rein lesendes Dashboard den Startbutton aus der Vorlage entfernen oder getrennt nur Administratoren bereitstellen.
