"""SQLite storage for Vital Touch readings and SOS events."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    heart_rate  INTEGER NOT NULL,
    spo2        INTEGER NOT NULL,
    temperature REAL,
    status      TEXT    NOT NULL,
    issues      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_device ON readings (device_id, id);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def init_db(path):
    with closing(connect(path)) as con:
        con.executescript(SCHEMA)
        con.commit()


def _reading_to_dict(row):
    data = dict(row)
    data["issues"] = json.loads(data["issues"])
    return data


def insert_reading(path, reading, status, issues, source):
    with closing(connect(path)) as con:
        cur = con.execute(
            """INSERT INTO readings
               (device_id, heart_rate, spo2, temperature, status, issues, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reading["device_id"],
                reading["heart_rate"],
                reading["spo2"],
                reading["temperature"],
                status,
                json.dumps(issues),
                source,
                _now(),
            ),
        )
        con.commit()
        row = con.execute("SELECT * FROM readings WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _reading_to_dict(row)


def list_readings(path, after_id=0, limit=50):
    """Readings in ascending id order.

    With after_id > 0: readings newer than after_id (for polling).
    Otherwise: the most recent `limit` readings.
    """
    with closing(connect(path)) as con:
        if after_id > 0:
            rows = con.execute(
                "SELECT * FROM readings WHERE id > ? ORDER BY id ASC LIMIT ?",
                (after_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM (SELECT * FROM readings ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (limit,),
            ).fetchall()
    return [_reading_to_dict(r) for r in rows]


def latest_reading(path):
    with closing(connect(path)) as con:
        row = con.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 1").fetchone()
    return _reading_to_dict(row) if row else None


def insert_event(path, event_type, message, created_by):
    with closing(connect(path)) as con:
        cur = con.execute(
            "INSERT INTO events (type, message, created_by, created_at) VALUES (?, ?, ?, ?)",
            (event_type, message, created_by, _now()),
        )
        con.commit()
        row = con.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_events(path, limit=20):
    with closing(connect(path)) as con:
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
