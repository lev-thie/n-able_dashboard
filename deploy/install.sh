#!/usr/bin/env bash
# NOC-Wanddisplay – Einrichtung auf dem Raspberry Pi (läuft als root auf dem Pi).
# Wird von deploy.sh / deploy.ps1 aufgerufen, kann aber auch direkt laufen:
#   sudo bash install.sh [--reset] [--hostname NAME]
#
#   --reset     Pi auf einen sauberen Grundzustand für den Kiosk-Betrieb zurücksetzen:
#               alte Dashboard-Installation und Kiosk-Benutzer entfernen, Desktop-Autologin
#               und Display-Manager abschalten, Pakete aktualisieren, nicht mehr benötigte
#               Pakete entfernen. Persönliche Dateien und SSH-Zugang bleiben erhalten.
#               Ein echter Werkszustand ist nur durch Neu-Flashen der SD-Karte möglich.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/noc-dashboard
CONF_DIR=/etc/noc-dashboard
RESET=0
NEW_HOSTNAME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --reset) RESET=1 ;;
    --hostname) NEW_HOSTNAME="$2"; shift ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1;38;2;255;97;76m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }
. /etc/os-release
case "${VERSION_CODENAME:-}" in
  bookworm|trixie) ;;
  *) echo "Warnung: getestet für Raspberry Pi OS Bookworm/Trixie, gefunden: ${PRETTY_NAME:-?}" >&2 ;;
esac
export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------------------- Zurücksetzen
if [ "$RESET" -eq 1 ]; then
  say "Setze Pi auf Grundzustand für Kiosk-Betrieb zurück"
  systemctl disable --now noc-kiosk.service noc-dashboard.service noc-kiosk-restart.timer 2>/dev/null || true
  rm -f /etc/systemd/system/noc-kiosk.service /etc/systemd/system/noc-dashboard.service \
        /etc/systemd/system/noc-kiosk-restart.service /etc/systemd/system/noc-kiosk-restart.timer \
        /etc/pam.d/noc-kiosk
  rm -rf "$DEST"
  id kiosk >/dev/null 2>&1 && userdel -r kiosk 2>/dev/null || true
  rm -rf /var/lib/noc-kiosk
  # Desktop-Oberfläche (falls vorhanden) samt aller Desktop-Autostarts abschalten
  for dm in lightdm gdm3 sddm; do
    systemctl disable --now "$dm.service" 2>/dev/null || true
  done
  rm -f /etc/systemd/system/display-manager.service
  # Konsolen-Autologin entfernen (raspi-config-Variante)
  rm -f /etc/systemd/system/getty@tty1.service.d/autologin.conf
  systemctl daemon-reload
  apt-get update
  apt-get -y full-upgrade
  apt-get -y autoremove --purge
fi

# --------------------------------------------------------------------------- Pakete
say "Installiere Pakete"
apt-get update
apt-get install -y --no-install-recommends \
  python3 alsa-utils curl ca-certificates cage fonts-liberation2 fonts-dejavu-core dbus-user-session
# Bookworm (Raspberry Pi OS) heißt das Paket "chromium-browser", ab Trixie "chromium"
apt-get install -y --no-install-recommends chromium-browser 2>/dev/null \
  || apt-get install -y --no-install-recommends chromium

# --------------------------------------------------------------------------- System
if [ -n "$NEW_HOSTNAME" ]; then
  say "Setze Hostname: $NEW_HOSTNAME"
  hostnamectl set-hostname "$NEW_HOSTNAME"
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NEW_HOSTNAME/" /etc/hosts
fi
timedatectl set-timezone Europe/Berlin || true
timedatectl set-ntp true || true

say "Bildschirmschoner der Konsole abschalten"
CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
if [ -f "$CMDLINE" ] && ! grep -q 'consoleblank=0' "$CMDLINE"; then
  sed -i '1 s/$/ consoleblank=0/' "$CMDLINE"
fi

# --------------------------------------------------------------------------- Benutzer
say "Lege Dienstbenutzer an"
id noc >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin noc
usermod -aG audio noc
if ! id kiosk >/dev/null 2>&1; then
  useradd --create-home --home-dir /var/lib/noc-kiosk --shell /usr/sbin/nologin kiosk
fi
usermod -aG video,render,input,audio kiosk 2>/dev/null || usermod -aG video,input,audio kiosk

# --------------------------------------------------------------------------- Anwendung
say "Kopiere Anwendung nach $DEST"
install -d -m 755 "$DEST"
rm -rf "$DEST/app" "$DEST/web" "$DEST/deploy"
cp -r "$SRC/app" "$SRC/web" "$SRC/deploy" "$DEST/"
install -d -m 755 "$DEST/sounds"
if ls "$SRC"/sounds/*.wav >/dev/null 2>&1; then
  WAV="$(ls "$SRC"/sounds/*.wav | head -n1)"
  install -m 644 "$WAV" "$DEST/sounds/alarm.wav"
  echo "Alarmton: $(basename "$WAV") → $DEST/sounds/alarm.wav"
else
  echo "Hinweis: keine .wav-Datei in sounds/ – Alarmton bleibt stumm, bis eine abgelegt wird."
fi
chmod 755 "$DEST/deploy/kiosk-start.sh"
find "$DEST" -name '__pycache__' -prune -exec rm -rf {} +

install -d -m 750 -o root -g noc "$CONF_DIR"
if [ -f "$SRC/config/config.env" ]; then
  install -m 640 -o root -g noc "$SRC/config/config.env" "$CONF_DIR/config.env"
  echo "Konfiguration übernommen."
elif [ ! -f "$CONF_DIR/config.env" ]; then
  install -m 640 -o root -g noc "$SRC/config/config.example.env" "$CONF_DIR/config.env"
  echo "Keine config.env mitgeliefert – Vorlage installiert, Dashboard startet im Demo-Modus."
else
  echo "Vorhandene $CONF_DIR/config.env bleibt unverändert."
fi

# --------------------------------------------------------------------------- Dienste
say "Richte systemd-Dienste und Kiosk-Autostart ein"
cat > /etc/pam.d/noc-kiosk <<'EOF'
auth     required pam_unix.so nullok
account  required pam_unix.so
session  required pam_unix.so
session  required pam_systemd.so
EOF
install -m 644 "$SRC/deploy/systemd/noc-dashboard.service" /etc/systemd/system/
install -m 644 "$SRC/deploy/systemd/noc-kiosk.service" /etc/systemd/system/

# Nächtlicher Neustart des Browsers (03:15) gegen Speicherwachstum im Dauerbetrieb
cat > /etc/systemd/system/noc-kiosk-restart.service <<'EOF'
[Unit]
Description=NOC-Wanddisplay: Kiosk-Browser neu starten
[Service]
Type=oneshot
ExecStart=/bin/systemctl restart noc-kiosk.service
EOF
cat > /etc/systemd/system/noc-kiosk-restart.timer <<'EOF'
[Unit]
Description=NOC-Wanddisplay: nächtlicher Browser-Neustart
[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=false
[Install]
WantedBy=timers.target
EOF

# Kein anderer Desktop darf den Bildschirm belegen
for dm in lightdm gdm3 sddm; do systemctl disable --now "$dm.service" 2>/dev/null || true; done
systemctl set-default graphical.target
systemctl daemon-reload
systemctl enable noc-dashboard.service noc-kiosk.service noc-kiosk-restart.timer
systemctl restart noc-dashboard.service
systemctl restart noc-kiosk.service || true
systemctl start noc-kiosk-restart.timer

say "Prüfe Backend"
BACKEND_OK=0
for i in $(seq 30); do
  if curl -sf http://127.0.0.1:8080/healthz >/dev/null; then BACKEND_OK=1; echo "Backend antwortet."; break; fi
  sleep 1
done
if [ "$BACKEND_OK" -eq 1 ]; then
  curl -sf http://127.0.0.1:8080/api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("Demo-Modus" if d["demo"] else "Echtdaten", "|", {k:("ok" if v["ok"] else (v["error"] or "wartet")) for k,v in d["sources"].items() if v["enabled"]})' || true
else
  echo "FEHLER: Backend antwortet nicht auf Port 8080. Letzte Log-Zeilen:"
  journalctl -u noc-dashboard -n 25 --no-pager || true
  echo "Belegt ein anderes Programm Port 8080?"
  ss -ltnp 2>/dev/null | grep ':8080 ' || echo "  (nein, Port 8080 ist frei)"
fi

cat <<EOF

Fertig. Das Dashboard startet ab jetzt automatisch im Kiosk-Modus.
  Status Backend:   systemctl status noc-dashboard
  Log Backend:      journalctl -u noc-dashboard -f
  Status Kiosk:     systemctl status noc-kiosk
  Alarmton testen:  sudo -u noc python3 $DEST/app/server.py --config $CONF_DIR/config.env --test-sound
  Konfiguration:    sudo nano $CONF_DIR/config.env  (danach: sudo systemctl restart noc-dashboard)
EOF
if [ "$RESET" -eq 1 ]; then
  echo
  echo "Nach dem Zurücksetzen wird ein Neustart empfohlen: sudo reboot"
fi
