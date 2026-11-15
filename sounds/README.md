Hier die Alarm-Datei (`.wav`) ablegen, z. B. `sounds/alarm.wav`.
Beim Deployment wird die erste `.wav`-Datei aus diesem Ordner als `/opt/noc-dashboard/sounds/alarm.wav` auf den Pi kopiert.
Sie wird abgespielt, sobald ein neues kritisches Problem auftritt (siehe `ALARM_*` in `config/config.example.env`).
