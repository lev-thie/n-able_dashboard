#!/usr/bin/env bash
# NOC-Wanddisplay – vom eigenen Rechner per SSH auf den Raspberry Pi übertragen und einrichten.
#
#   ./deploy/deploy.sh pi@noc-display.local            # installieren / aktualisieren
#   ./deploy/deploy.sh pi@noc-display.local --reset    # vorher auf Grundzustand zurücksetzen
#   ./deploy/deploy.sh pi@192.168.1.50 --reset --reboot --hostname noc-display
#
# Mitgeschickt werden: app/, web/, deploy/, config/ (inkl. config.env, falls vorhanden) und sounds/*.wav
set -euo pipefail

if [ $# -lt 1 ]; then
  sed -n '2,8p' "$0"; exit 2
fi
TARGET="$1"; shift
REBOOT=0
INSTALL_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --reboot) REBOOT=1 ;;
    --reset) INSTALL_ARGS+=(--reset) ;;
    --hostname) INSTALL_ARGS+=(--hostname "$2"); shift ;;
    *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/noc-dashboard.tar.gz"

[ -f "$ROOT/config/config.env" ] || echo "Hinweis: config/config.env fehlt – auf dem Pi bleibt die vorhandene Konfiguration (oder Demo-Modus)."
ls "$ROOT"/sounds/*.wav >/dev/null 2>&1 || echo "Hinweis: keine .wav-Datei in sounds/ – Alarmton bleibt stumm."

echo "==> Packe Dateien"
tar -C "$ROOT" --exclude='__pycache__' -czf "$ARCHIVE" app web deploy config sounds

echo "==> Übertrage nach $TARGET"
scp -q "$ARCHIVE" "$TARGET:/tmp/noc-dashboard.tar.gz"

echo "==> Installiere auf dem Pi"
ssh -t "$TARGET" "set -e; rm -rf /tmp/noc-dashboard-src; mkdir -p /tmp/noc-dashboard-src; \
  tar -xzf /tmp/noc-dashboard.tar.gz -C /tmp/noc-dashboard-src; \
  sudo bash /tmp/noc-dashboard-src/deploy/install.sh ${INSTALL_ARGS[*]:-}; \
  rm -rf /tmp/noc-dashboard-src /tmp/noc-dashboard.tar.gz"

if [ "$REBOOT" -eq 1 ]; then
  echo "==> Starte Pi neu"
  ssh "$TARGET" "sudo systemctl reboot" || true
fi
