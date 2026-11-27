"""Baut aus dem Roh-JSON in data/garmin.db flache pandas-Tabellen (ein Eintrag pro Tag/Aktivität)."""
import json
import sqlite3

import pandas as pd

from .config import DB_PATH


def _range_rows(db, metric):
    """Liefert (fetched_at, json) aller Abschnitte; neuere überschreiben ältere pro Tag."""
    return db.execute(
        "SELECT fetched_at, json FROM range_data WHERE metric=? ORDER BY fetched_at", (metric,)
    ).fetchall()


def _by_day(db, metric, items_fn, row_fn):
    out = {}
    for _, js in _range_rows(db, metric):
        j = json.loads(js)
        for it in (items_fn(j) if j else None) or []:
            r = row_fn(it)
            if r and r.get("day"):
                out[r["day"]] = {**out.get(r["day"], {}), **r}
    return pd.DataFrame(out.values())


def daily(db_path=DB_PATH) -> pd.DataFrame:
    db = sqlite3.connect(db_path)

    def summ(d):
        hr, st, bb, im = (d.get(k) or {} for k in ("heartRate", "stress", "bodyBattery", "intensityMinutes"))
        mv = (d.get("movement") or {}).get("steps") or {}
        return {"day": d.get("calendarDate"), "rhr": hr.get("restingValue"),
                "stress_avg": st.get("avgLevel"), "bb_max": bb.get("maxValue"),
                "bb_min": bb.get("minValue"), "bb_charged": bb.get("chargedValue"),
                "bb_drained": bb.get("drainedValue"), "steps": mv.get("value"),
                "im_moderate": im.get("moderate"), "im_vigorous": im.get("vigorous"),
                "resp_avg": (d.get("respiration") or {}).get("avgValue")}

    def sleep(s):
        sc = s.get("sleepScores") or {}
        return {"day": s.get("calendarDate"),
                "sleep_h": (s.get("sleepTimeSeconds") or 0) / 3600 or None,
                "deep_h": (s.get("deepSleepSeconds") or 0) / 3600,
                "rem_h": (s.get("remSleepSeconds") or 0) / 3600,
                "awake_h": (s.get("awakeSleepSeconds") or 0) / 3600,
                "sleep_score": (sc.get("overall") or {}).get("value"),
                "sleep_hr": s.get("avgHeartRate"), "sleep_stress": s.get("avgSleepStress"),
                "sleep_start_local_ms": s.get("sleepStartTimestampLocal"),
                "sleep_end_local_ms": s.get("sleepEndTimestampLocal"),
                "sleep_need_min": (s.get("sleepNeed") or {}).get("actual")}

    def hrv(h):
        b = h.get("baseline") or {}
        return {"day": h.get("calendarDate"), "hrv": h.get("lastNightAvg"),
                "hrv_week": h.get("weeklyAvg"), "hrv_bal_low": b.get("balancedLow"),
                "hrv_bal_up": b.get("balancedUpper"), "hrv_status": h.get("status")}

    def vo2(v):
        g = v.get("generic") or {}
        return {"day": g.get("calendarDate"), "vo2max": g.get("vo2MaxPreciseValue")}

    parts = [
        _by_day(db, "daily_summaries", lambda j: j.get("data"), summ),
        _by_day(db, "sleep_summaries", lambda j: j, sleep),
        _by_day(db, "hrv_summaries", lambda j: j.get("hrvSummaries"), hrv),
        _by_day(db, "vo2max", lambda j: j, vo2),
    ]
    df = parts[0]
    for p in parts[1:]:
        if not p.empty:
            df = df.merge(p, on="day", how="outer")
    df["day"] = pd.to_datetime(df["day"])
    for c in ("sleep_start_local_ms", "sleep_end_local_ms"):
        df[c.replace("_ms", "")] = pd.to_datetime(df.pop(c), unit="ms")
    return df.sort_values("day").set_index("day")


def activities(db_path=DB_PATH) -> pd.DataFrame:
    db = sqlite3.connect(db_path)
    rows = []
    for aid, js in db.execute("SELECT activity_id, summary_json FROM activities"):
        a = json.loads(js)
        r = {"id": aid, "start": pd.to_datetime(a.get("startTimeLocal")),
             "type": (a.get("activityType") or {}).get("typeKey"), "name": a.get("activityName"),
             "dist_km": (a.get("distance") or 0) / 1000, "dur_min": (a.get("duration") or 0) / 60,
             "avg_hr": a.get("averageHR"), "max_hr": a.get("maxHR"),
             "avg_speed": a.get("averageSpeed"), "gap_speed": a.get("avgGradeAdjustedSpeed"),
             "cadence": a.get("averageRunningCadenceInStepsPerMinute"),
             "power": a.get("avgPower"), "gct": a.get("avgGroundContactTime"),
             "vo": a.get("avgVerticalOscillation"), "stride": a.get("avgStrideLength"),
             "elev_gain": a.get("elevationGain"), "load": a.get("activityTrainingLoad"),
             "te_aer": a.get("aerobicTrainingEffect"), "te_ana": a.get("anaerobicTrainingEffect"),
             "te_label": a.get("trainingEffectLabel"), "bb_diff": a.get("differenceBodyBattery")}
        for z in range(1, 6):
            r[f"z{z}_min"] = (a.get(f"hrTimeInZone_{z}") or 0) / 60
        rows.append(r)
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)
