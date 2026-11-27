"""Holt Garmin-Daten über die offizielle Personal API in eine lokale SQLite-DB.

  python -m garmin_sync.sync --days 365     # Erstbefüllung
  python -m garmin_sync.sync                # Täglicher Lauf (Standard: 30 Tage, nur Fehlendes + letzte 3 Tage)
"""
import argparse
import json
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

from garmin_personal_api import GarminPersonalApiClient, PersonalApiAuthenticator, resolve_api_key
from garmin_personal_api.errors import HttpError

from .config import DATA_DIR, DB_PATH, FIT_DIR

CHUNK = 28  # kleinste beobachtete maximale Spanne der Range-Endpunkte

# Range-Endpunkte: (start, end) -> Daten für mehrere Tage, gespeichert pro Abschnitt
RANGE = {
    "daily_summaries": lambda c, s, e: c.get_daily_summaries(s, e),
    "stress": lambda c, s, e: c.get_daily_stress(s, e),
    "steps": lambda c, s, e: c.get_daily_steps(s, e),
    "body_battery": lambda c, s, e: c.get_daily_body_battery(s, e),
    "sleep_summaries": lambda c, s, e: c.get_daily_sleep_summaries(s, e),
    "hrv_summaries": lambda c, s, e: c.get_daily_hrv_summaries(s, e),
    "vo2max": lambda c, s, e: c.get_daily_vo2_max(s, e),
    "weight": lambda c, s, e: c.get_weight_measurements(s, e),
    "wellness_activities": lambda c, s, e: c.get_wellness_activity_summaries(s, e),
}

# Tages-Endpunkte mit Detailkurven
DAILY = {
    "sleep": lambda c, d: c.get_daily_sleep(d),
    "hrv": lambda c, d: c.get_daily_hrv(d),
    "heart_rate": lambda c, d: c.get_daily_heart_rate(d),
    "spo2": lambda c, d: c.get_daily_spo2(d),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS range_data (
  metric TEXT, start_day TEXT, end_day TEXT, json TEXT, fetched_at TEXT,
  PRIMARY KEY (metric, start_day));
CREATE TABLE IF NOT EXISTS daily (
  day TEXT, metric TEXT, json TEXT, fetched_at TEXT,
  PRIMARY KEY (day, metric));
CREATE TABLE IF NOT EXISTS activities (
  activity_id INTEGER PRIMARY KEY, start_local TEXT, type TEXT,
  summary_json TEXT, detail_json TEXT, fit_path TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, json TEXT, fetched_at TEXT);
"""

REFRESH_DAYS = 3  # jüngste Tage immer neu holen (Uhr synct oft verspätet)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def call(fn, *args):
    for wait in (30, 120, 300):
        try:
            return fn(*args)
        except HttpError as e:
            if e.status_code != 429 and e.status_code < 500:
                raise
            print(f"  HTTP {e.status_code}, warte {wait}s …")
            time.sleep(wait)
    return fn(*args)


def store(db, sql, args):
    db.execute(sql, args)
    db.commit()


def sync_range(c, db, start, end, refresh_from):
    have = {(r[0], r[1]) for r in db.execute("SELECT metric, start_day FROM range_data")}
    s = start
    while s <= end:
        e = min(s + timedelta(days=CHUNK - 1), end)
        for m, fn in RANGE.items():
            if (m, s.isoformat()) in have and e < refresh_from:
                continue
            try:
                data = call(fn, c, s, e)
            except HttpError as err:
                print(f"  {m} {s}..{e}: HTTP {err.status_code}")
                continue
            store(db, "INSERT OR REPLACE INTO range_data VALUES (?,?,?,?,?)",
                  (m, s.isoformat(), e.isoformat(), json.dumps(data), now()))
            time.sleep(0.3)
        print(f"Zeitraum {s}..{e} fertig")
        s = e + timedelta(days=1)


def sync_daily(c, db, start, end, refresh_from):
    have = {(r[0], r[1]) for r in db.execute("SELECT day, metric FROM daily")}
    d = start
    while d <= end:
        ds = d.isoformat()
        todo = [m for m in DAILY if (ds, m) not in have or d >= refresh_from]
        for m in todo:
            try:
                data = call(DAILY[m], c, ds)
            except HttpError as err:
                print(f"  {ds} {m}: HTTP {err.status_code}")
                continue
            store(db, "INSERT OR REPLACE INTO daily VALUES (?,?,?,?)",
                  (ds, m, json.dumps(data), now()))
            time.sleep(0.3)
        if todo:
            print(f"{ds}: {len(todo)} Tageswerte")
        d += timedelta(days=1)


def sync_activities(c, db, start, end, with_fit):
    acts, offset = [], 0
    while True:
        page = call(lambda: c.search_activities(start=offset, limit=100,
                                                start_date=start, end_date=end))
        if not page:
            break
        acts += page
        offset += len(page)
        if len(page) < 100:
            break
    have = {r[0]: r[1] for r in db.execute("SELECT activity_id, fit_path FROM activities")}
    FIT_DIR.mkdir(parents=True, exist_ok=True)
    new = 0
    for a in acts:
        aid = a["activityId"]
        if aid in have and (have[aid] or not with_fit):
            continue
        try:
            detail = call(c.get_activity, aid)
        except HttpError as err:
            print(f"  Aktivität {aid}: HTTP {err.status_code}")
            detail = None
        fit_path = None
        if with_fit:
            try:
                p = FIT_DIR / f"{aid}.zip"
                p.write_bytes(call(c.download_activity, aid))
                fit_path = str(p.relative_to(DATA_DIR))
            except HttpError as err:
                print(f"  FIT {aid}: HTTP {err.status_code}")
        store(db, "INSERT OR REPLACE INTO activities VALUES (?,?,?,?,?,?,?)",
              (aid, a.get("startTimeLocal"), (a.get("activityType") or {}).get("typeKey"),
               json.dumps(a), json.dumps(detail), fit_path, now()))
        new += 1
        time.sleep(0.3)
    print(f"Aktivitäten: {len(acts)} im Zeitraum, {new} neu geladen")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Wie weit zurück (Tage)")
    ap.add_argument("--no-fit", action="store_true", help="Keine FIT-Dateien laden")
    a = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)

    with PersonalApiAuthenticator() as auth:
        token = auth.obtain_token(resolve_api_key())

    end = date.today()
    start = end - timedelta(days=a.days - 1)
    refresh_from = end - timedelta(days=REFRESH_DAYS - 1)
    with GarminPersonalApiClient(token.access_token) as c:
        for key, fn in {"profile_settings": c.get_user_profile_settings,
                        "hr_zones": c.get_heart_rate_zones}.items():
            try:
                store(db, "INSERT OR REPLACE INTO meta VALUES (?,?,?)",
                      (key, json.dumps(call(fn)), now()))
            except HttpError as err:
                print(f"  {key}: HTTP {err.status_code}")
        sync_range(c, db, start, end, refresh_from)
        sync_daily(c, db, start, end, refresh_from)
        sync_activities(c, db, start, end, not a.no_fit)
    print(f"Fertig. DB: {DB_PATH}")


if __name__ == "__main__":
    main()
