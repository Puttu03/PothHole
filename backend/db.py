"""SQLite storage. One file, three tables:
   detections  = DB1 (raw sightings, one row per box the model found)
   potholes    = DB.F (one row per real pothole, after post-processing)
   feedback    = driver "still there" / "gone" reports
Run `python -m server.db init` to create the tables."""
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    captured_at     TEXT,
    device_id       TEXT,
    user_id         TEXT,
    lat             REAL NOT NULL,
    lon             REAL NOT NULL,
    gps_accuracy_m  REAL,
    heading_deg     REAL,
    speed_kmh       REAL,
    camera_height_m REAL,
    camera_tilt_deg REAL,
    hfov_deg        REAL,
    img_w           INTEGER,
    img_h           INTEGER,
    photo_path      TEXT NOT NULL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    confidence      REAL,
    processed       INTEGER NOT NULL DEFAULT 0,
    process_note    TEXT,
    pothole_id      INTEGER REFERENCES potholes(id)
);
CREATE INDEX IF NOT EXISTS idx_det_processed ON detections(processed);

CREATE TABLE IF NOT EXISTS potholes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    lat              REAL NOT NULL,
    lon              REAL NOT NULL,
    loc_accuracy_m   REAL,
    severity         TEXT,
    ride_score       REAL,
    width_m          REAL,
    area_m2          REAL,
    surface          TEXT,
    lane_position    TEXT,
    description      TEXT,
    best_photo_path  TEXT,
    crop_path        TEXT,
    times_seen       INTEGER NOT NULL DEFAULT 0,
    weight_sum       REAL NOT NULL DEFAULT 0,
    first_seen       TEXT,
    last_seen        TEXT,
    status           TEXT NOT NULL DEFAULT 'open',
    scored_by        TEXT,
    slm_model        TEXT,
    needs_review     INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_ph_latlon ON potholes(lat, lon);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pothole_id  INTEGER NOT NULL REFERENCES potholes(id),
    kind        TEXT NOT NULL CHECK (kind IN ('still_there', 'gone')),
    created_at  TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    path = path or settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path=None):
    with session(path) as conn:
        conn.executescript(SCHEMA)
        for table in ('detections', 'potholes'):
            columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
            if 'damage_type' not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN damage_type TEXT NOT NULL DEFAULT 'pothole'")


# ---------- DB1 ----------
DET_FIELDS = [
    "captured_at", "device_id", "user_id", "lat", "lon", "gps_accuracy_m",
    "heading_deg", "speed_kmh", "camera_height_m", "camera_tilt_deg", "hfov_deg",
    "img_w", "img_h", "photo_path", "x1", "y1", "x2", "y2", "confidence", "damage_type",
]


def insert_detection(conn, row: dict) -> int:
    cols = ["created_at"] + DET_FIELDS
    vals = [now_iso()] + [(row.get(c) or "pothole") if c == "damage_type" else row.get(c) for c in DET_FIELDS]
    cur = conn.execute(
        f"INSERT INTO detections ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals
    )
    return cur.lastrowid


# ---------- DB.F ----------
def potholes_in_box(conn, min_lat, max_lat, min_lon, max_lon, statuses=("open",), limit=5000):
    q = f"""SELECT * FROM potholes
            WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
              AND status IN ({','.join('?' * len(statuses))})
            LIMIT ?"""
    return [dict(r) for r in conn.execute(q, (min_lat, max_lat, min_lon, max_lon, *statuses, limit))]


def all_potholes(conn, statuses=("open",), limit=5000):
    q = f"SELECT * FROM potholes WHERE status IN ({','.join('?' * len(statuses))}) LIMIT ?"
    return [dict(r) for r in conn.execute(q, (*statuses, limit))]


def add_feedback(conn, pothole_id: int, kind: str) -> dict:
    ph = conn.execute("SELECT id, last_seen, status FROM potholes WHERE id=?", (pothole_id,)).fetchone()
    if not ph:
        raise KeyError(pothole_id)
    conn.execute(
        "INSERT INTO feedback (pothole_id, kind, created_at) VALUES (?,?,?)",
        (pothole_id, kind, now_iso()),
    )
    status = ph["status"]
    if kind == "still_there":
        conn.execute("UPDATE potholes SET last_seen=?, status='open', updated_at=? WHERE id=?",
                     (now_iso(), now_iso(), pothole_id))
        status = "open"
    else:
        # count "gone" reports since the pothole was last confirmed
        n = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE pothole_id=? AND kind='gone' AND created_at >= ?",
            (pothole_id, ph["last_seen"] or ""),
        ).fetchone()[0]
        if n >= settings.GONE_REPORTS_TO_CLOSE:
            conn.execute("UPDATE potholes SET status='repaired', updated_at=? WHERE id=?",
                         (now_iso(), pothole_id))
            status = "repaired"
    return {"pothole_id": pothole_id, "status": status}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init()
        print(f"Database ready at {settings.DB_PATH}")
    else:
        print("usage: python -m server.db init")
