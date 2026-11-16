# Startprompt für eine Claude-Code-Sitzung auf dem Raspberry Pi

Claude Code direkt auf dem Pi starten (per SSH angemeldet):

```bash
curl -fsSL https://claude.ai/install.sh | bash     # einmalig installieren
cd ~/n-able_dashboard && git pull
claude
```

Dann den folgenden Text als erste Nachricht einfügen.

---

Du arbeitest direkt auf einem Raspberry Pi (Raspberry Pi OS, Debian Trixie, arm64, Python 3.13), auf dem ein NOC-Wanddisplay im Kiosk-Modus läuft. Ich bin per SSH als Benutzer `gleichitadmin` angemeldet. Hostname: `noc-display` (vorher `GIT-MON-001`). Antworte auf Deutsch.

## Projekt
- Repository: `~/n-able_dashboard` (GitHub `lev-thie/n-able_dashboard`, Branch `claude/pensive-faraday-qn8y4t`). Lies zuerst `README.md`.
- Zweck: Bildschirm-Dashboard für die Firma, nur Heras-Branding, keine anderen Firmennamen. Von 07:30 bis 17:00 Uhr zeigt es das Dashboard, sonst eine Digitaluhr mit zentriertem Heras-Logo. Bei neuen kritischen Problemen spielt es eine WAV-Datei ab.
- Aufbau:
  - `app/server.py`: Backend, nur Python-Standardbibliothek. Es fragt die APIs ab, liefert `/api/status` und `/healthz` und spielt den Alarm per `aplay`.
  - `app/demo.py`: Beispieldaten für den Fall, dass keine Zugangsdaten eingetragen sind.
  - `web/`: Oberfläche (`index.html`, `style.css`, `app.js`, Logo unter `web/assets/`).
  - `deploy/install.sh`: Einrichtung als root, mit `--reset` für den Grundzustand.
  - `deploy/kiosk-start.sh`: startet Cage und Chromium.
  - `deploy/systemd/`: die systemd-Units.

## Installation auf diesem Pi
- Programm unter `/opt/noc-dashboard/` (Kopie aus dem Repo, wird durch `sudo bash deploy/install.sh` aktualisiert).
- Konfiguration unter `/etc/noc-dashboard/config.env` (root:noc, 640). `install.sh` überschreibt sie mit `~/n-able_dashboard/config/config.env`, falls diese existiert. Vorlage: `config/config.example.env`.
- Dienste:
  - `noc-dashboard.service`: Backend, Benutzer `noc`, `127.0.0.1:8765`.
  - `noc-kiosk.service`: Cage und Chromium auf tty1, Benutzer `kiosk`, Profil unter `/var/lib/noc-kiosk`.
  - `noc-kiosk-restart.timer`: startet den Browser täglich um 03:15 neu.
- Port 8080 ist von einem anderen, fremden Python-Programm belegt. **Dieses Programm nicht beenden.** Das Dashboard nutzt deshalb `PORT=8765`; der Port steht zusätzlich in `/opt/noc-dashboard/port`.
- Alarmton: `/opt/noc-dashboard/sounds/alarm.wav` (Quelle: `sounds/*.wav` im Repo). Test: `sudo -u noc python3 /opt/noc-dashboard/app/server.py --config /etc/noc-dashboard/config.env --test-sound`. Ausgabegerät über `ALARM_ALSA_DEVICE`, Liste mit `aplay -L`.
- Schriftgröße über `UI_SCALE` (Standard 1).

## Datenquellen
- **N-able GraphQL** (`https://api.n-able.com/graphql`, Bearer-Token `NABLE_API_TOKEN`):
  - `assetSearch` mit Seiten über `pageInfo.endCursor`.
  - `assets(ids:)` liefert `metrics.cpu.percentage` und `metrics.memory.percentage`. Diese brauchen das Argument `input: {timeSeries: {dateTimeRange: {relative: {relativeTo, dateTimePeriod: PREVIOUS_MINUTES, numberOfDateTimeUnits}}, granularity: {value, unit: MINUTE}}}`.
  - Außerdem: `agentConnection.status` (CONNECTED/DISCONNECTED), `logicalDrives`, `reboot.isRequired`, `lastBootedAt`, `ncentralDevice.deviceId`.
- **N-central REST** (`NCENTRAL_SERVER`, `NCENTRAL_JWT`):
  - Anmeldung: `POST /api/auth/authenticate` mit dem JWT als Bearer, liefert `tokens.access.token`.
  - Gerätefilter: `NCENTRAL_DEVICE_FILTER=DASHBOARD EXTERN PROJEKT`. Name auflösen über `GET /api/device-filters`, Geräte holen über `GET /api/devices?filterId=…`. Es werden **nur Geräte aus diesem Filter** angezeigt.
  - Probleme je Gerät: `GET /api/devices/{id}/service-monitor-status`. `stateStatus` „Failed“ zählt als kritisch, „Warning“ und „Misconfigured“ als Warnung (einstellbar). `moduleName` ist der Dienstname.
- **UniFi Site Manager** (`https://api.ui.com`, Header `X-API-Key: UNIFI_API_KEY`): `GET /v1/sites` (`statistics.counts`, `percentages.wanUptime`) und `GET /v1/devices`.

## Noch nicht gegen echte Daten geprüft – bitte verifizieren
1. Ob die N-able-GraphQL-Abfragen mit dem echten Token fehlerfrei laufen. Die Feldnamen stammen aus der Schema-Dokumentation.
2. Ob der Filter „DASHBOARD EXTERN PROJEKT“ gefunden wird und welche `stateStatus`-Werte vorkommen. Beides steht im Log: `journalctl -u noc-dashboard | grep -E "Filter|stateStatus"`.
3. Ob N-able-Assets den N-central-Geräten zugeordnet werden (über `ncentralDevice.deviceId` oder den Namen). Ohne Zuordnung fehlen die CPU-, RAM- und Datenträger-Balken.
4. Ob der Alarmton über HDMI hörbar ist.
5. Ob Kiosk, Schriftgröße und der Wechsel zwischen Uhr und Dashboard am echten Bildschirm passen.

## Arbeitsweise
- Diagnose: `systemctl status noc-dashboard noc-kiosk`, `journalctl -u noc-dashboard -n 100 --no-pager`, `curl -s http://127.0.0.1:8765/api/status | python3 -m json.tool | head -80`.
- Code nur im Repo `~/n-able_dashboard` ändern. Danach `sudo bash deploy/install.sh` und `sudo systemctl restart noc-kiosk`.
- Zugangsdaten nie ausgeben, nie committen und nie in Logs oder Chat kopieren. `config/config.env` steht in `.gitignore`.
- Kein `deploy/install.sh --reset`, kein Neustart des Pi und keine Änderungen an fremden Diensten (z. B. dem Programm auf Port 8080) ohne meine ausdrückliche Zustimmung.
- Änderungen auf den Branch `claude/pensive-faraday-qn8y4t` committen und pushen, wenn ich es sage.

Erste Aufgabe: Prüfe den aktuellen Zustand beider Dienste und des Logs, arbeite die Punkte 1 bis 3 der Prüfliste ab und berichte mir kurz, was funktioniert und was nicht.
