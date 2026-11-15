#!/bin/sh
# Startet Chromium im Kiosk-Modus innerhalb des Wayland-Kiosk-Compositors Cage.
# Wird von noc-kiosk.service als Benutzer "kiosk" auf tty1 ausgeführt.
set -eu

URL="http://127.0.0.1:8080/?kiosk=1"
BROWSER="$(command -v chromium || command -v chromium-browser)"
PROFILE="${HOME:-/var/lib/noc-kiosk}/chromium"

# Absturz-Hinweis („Chromium wurde nicht ordnungsgemäß beendet“) unterdrücken
if [ -f "$PROFILE/Default/Preferences" ]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' \
    "$PROFILE/Default/Preferences" || true
fi

exec /usr/bin/cage -d -- "$BROWSER" \
  --user-data-dir="$PROFILE" \
  --kiosk "$URL" \
  --ozone-platform=wayland \
  --noerrdialogs \
  --disable-infobars \
  --no-first-run \
  --disable-session-crashed-bubble \
  --disable-features=Translate,TranslateUI,MediaRouter \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  --autoplay-policy=no-user-gesture-required
