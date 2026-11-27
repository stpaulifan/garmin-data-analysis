<img src="assets/icon.svg" width="64" height="64" alt="">

# Garmin-data-anlysis

Created in [T3 Code](https://t3.codes).

## Garmin-Sync

Lädt eigene Daten über die offizielle **Garmin Connect Personal API** in `data/garmin.db` (SQLite, Roh-JSON).

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# API-Key aus https://connect.garmin.com/app/settings/personalApiToken
install -m 600 /dev/stdin ~/.config/garmin/connect-personal-api-key   # Key einfügen, Ctrl-D
.venv/bin/python -m garmin_sync.sync --days 365   # Erstbefüllung
```

Cron (täglich 06:30 und 20:30): `.venv/bin/python -m garmin_sync.sync --days 14`

Tabellen: `range_data` (Tagesübersichten, Stress, Schritte, Body Battery, Schlaf, HRV, VO2max, Gewicht),
`daily` (Detailkurven Schlaf/HRV/Puls/SpO2), `activities` (Zusammenfassung, Details, FIT-ZIP in `data/fit/`), `meta`.

Hinweis: Der Key läuft je nach Wahl nach 30 Tagen bis 1 Jahr ab, danach neu erstellen und Datei ersetzen.
