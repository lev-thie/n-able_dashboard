# NOC-Wanddisplay

Dashboard für einen Bildschirm am Raspberry Pi: Server und Dienste aus **N-able**, Kundenstandorte aus **UniFi**.
Von 07:30 bis 17:00 Uhr zeigt es das Dashboard, außerhalb dieser Zeit eine Digitaluhr mit Heras-Logo.
Bei einem neuen kritischen Problem spielt der Pi eine WAV-Datei ab.

## Aufbau

```
app/server.py        Backend (nur Python-Standardbibliothek): fragt die APIs ab, liefert /api/status, spielt den Alarmton
app/demo.py          Beispieldaten, solange keine Zugangsdaten eingetragen sind
web/                 Oberfläche (index.html, style.css, app.js, Logo)
config/              config.example.env → als config.env kopieren und ausfüllen (wird nicht eingecheckt)
sounds/              Alarmton als .wav hier ablegen
deploy/              deploy.sh (Linux/macOS), deploy.ps1 (Windows), install.sh (läuft auf dem Pi), systemd-Dienste
prototype/           grafischer Prototyp
```

Auf dem Pi laufen zwei Dienste:

| Dienst | Aufgabe |
|---|---|
| `noc-dashboard` | Backend auf `127.0.0.1:8765` (Port über `PORT` einstellbar), Benutzer `noc` |
| `noc-kiosk` | Chromium im Vollbild über den Wayland-Kiosk-Compositor `cage` auf tty1, Benutzer `kiosk`, startet automatisch beim Booten |

Zusätzlich startet ein Timer den Browser jede Nacht um 03:15 neu; die Seite lädt sich außerdem alle 6 Stunden neu.

## Datenquellen

| Quelle | Liefert | Zugang |
|---|---|---|
| N-able GraphQL (`api.n-able.com/graphql`) | Serverliste (Betriebssystem-Rolle `SERVER`), Agent online/offline, CPU- und RAM-Auslastung, Datenträgerbelegung, Laufzeit, ausstehender Neustart | API-Token als Bearer |
| N-central REST (optional) | Aktive Probleme je Kunde, daraus die gestoppten Dienste | User-API-Token (JWT) → `/api/auth/authenticate` |
| UniFi Site Manager (`api.ui.com/v1`) | Standorte, Geräte online/gesamt, Clients, WAN-Uptime, Provider, Gateway offline | API-Schlüssel im Header `X-API-Key` |

Gestoppte Dienste und Alarme bietet die N-able GraphQL-API nicht an. Sie kommen deshalb aus der N-central-REST-Schnittstelle (Endpunkt „active issues“, laut N-able noch im Preview-Status).

## Raspberry Pi einrichten

### 1. SD-Karte vorbereiten (echter Werkszustand)

Den echten Werkszustand erreichen Sie nur durch Neu-Flashen. Mit dem **Raspberry Pi Imager**:

1. **Raspberry Pi OS Lite (64-bit)** wählen.
2. In den Einstellungen Hostname (z. B. `noc-display`), Benutzer und Passwort sowie WLAN (falls nötig) setzen und **SSH aktivieren**, am besten mit Ihrem öffentlichen Schlüssel.
3. Karte einsetzen, Pi starten und warten, bis er per SSH erreichbar ist.

Es funktioniert auch auf einer vorhandenen Installation mit Desktop. Mit `--reset` entfernt das Skript dann alte Dashboard-Installationen, schaltet den Desktop samt Autologin und Autostart ab und aktualisiert alle Pakete. Persönliche Dateien und der SSH-Zugang bleiben erhalten.

### 2. Konfiguration ausfüllen

```bash
cp config/config.example.env config/config.env
# NABLE_API_TOKEN, UNIFI_API_KEY und optional NCENTRAL_SERVER/NCENTRAL_JWT eintragen
```

Den Alarmton als `sounds/alarm.wav` ablegen.

### 3. Deployen

Linux/macOS:

```bash
./deploy/deploy.sh pi@noc-display.local --reset --reboot
```

Windows (PowerShell):

```powershell
.\deploy\deploy.ps1 -Target pi@noc-display.local -Reset -Reboot
```

Für spätere Updates reicht der Aufruf ohne `--reset`/`--reboot`. Optionen:

- `--reset`: Pi vorher auf einen sauberen Grundzustand zurücksetzen (siehe oben).
- `--reboot`: Pi danach neu starten.
- `--hostname NAME`: Hostname setzen.

Ohne `config/config.env` behält der Pi seine bisherige Konfiguration. Ist noch keine vorhanden, läuft das Dashboard im Demo-Modus mit Beispieldaten.

## Betrieb

```bash
systemctl status noc-dashboard noc-kiosk       # Status
journalctl -u noc-dashboard -f                 # Log des Backends (API-Fehler stehen hier)
sudo nano /etc/noc-dashboard/config.env        # Konfiguration ändern …
sudo systemctl restart noc-dashboard           # … und übernehmen
sudo -u noc python3 /opt/noc-dashboard/app/server.py --config /etc/noc-dashboard/config.env --test-sound
aplay -L                                       # Audioausgänge auflisten (für ALARM_ALSA_DEVICE)
```

### Alarmton

- Der Ton erklingt, wenn ein **neues** kritisches Problem auftaucht. Kritisch sind:
  - Agent offline
  - CPU, RAM oder Datenträger über dem kritischen Schwellwert
  - kritischer N-central-Status
  - UniFi-Gateway offline
- Probleme, die beim Start des Dienstes schon bestehen, lösen keinen Ton aus.
- Standardmäßig ertönt er nur während der Anzeigezeit und höchstens einmal pro Minute.
- Mit `ALARM_REPEAT_MINUTES` lässt sich eine Erinnerung einstellen, solange kritische Probleme bestehen.
- Gleichzeitig blendet das Dashboard 30 Sekunden lang einen roten Hinweis ein.

### Vor dem Echtbetrieb prüfen

- **N-central-Status:** Welche `notificationState`-Werte als kritisch gelten, ist in der N-central-Dokumentation nicht beschrieben. Voreingestellt ist `5`, abgeleitet aus dem Dokumentationsbeispiel. Das Backend protokolliert jeden neuen Wert (`journalctl -u noc-dashboard | grep notificationState`); tragen Sie danach die richtigen Werte in `NCENTRAL_CRITICAL_STATES` ein.
- **Standortnamen:** Bei UniFi heißt ein Standort oft nur „Default“. Dann zeigt das Dashboard den Namen der Konsole. Benennen Sie Konsolen oder Standorte in UniFi deshalb nach dem Kunden.

## Lokal testen (ohne Pi)

```bash
cd app && python3 server.py --demo --config /dev/null
# Browser: http://127.0.0.1:8765/?preview=1  (Umschalter Dashboard/Uhr unten rechts)
```
