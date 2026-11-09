"""
db.py  --  The logbook.

We use SQLite, which is just a single file on disk (videotrends.db). No server
to install, no setup. Two tables:

  videos    -> one row per unique video we've ever seen (its identity + when we
               first/last saw it)
  snapshots -> one row EVERY TIME we scan a video. This is the time-series log
               that lets us draw "rising vs fading" over time.
"""

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "videotrends.db")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row  # lets us read columns by name
    # Wait (up to 15s) for locks instead of erroring, so the scanner and the
    # dashboard can hit the DB at the same time without "database is locked".
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db():
    """Create the tables if they don't exist yet. Safe to run every time."""
    conn = connect()
    # WAL mode lets reads happen during writes -- key for concurrent scan+dashboard.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id          TEXT PRIMARY KEY,   -- platform:native_id, e.g. "tiktok:12345"
            platform    TEXT NOT NULL,
            author      TEXT,
            title       TEXT,
            url         TEXT,
            post_time   REAL,               -- unix timestamp the video was posted
            first_seen  REAL,               -- first time OUR scanner saw it
            last_seen   REAL                -- most recent scan
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id    TEXT NOT NULL,
            scanned_at  REAL NOT NULL,
            views       INTEGER,
            likes       INTEGER,
            comments    INTEGER,
            shares      INTEGER,
            age_hours   REAL,
            velocity    REAL,
            freshness   REAL,
            trend_score REAL,
            acceleration REAL,              -- % change in velocity vs previous scan
            fashion_score REAL,             -- 0..1 how clothing-centered the video is
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_video ON snapshots(video_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snap_time ON snapshots(scanned_at)")
    _migrate(c)
    conn.commit()
    conn.close()


def _migrate(c):
    """Add newer columns to databases created before they existed. Safe to re-run."""
    snap_cols = [r["name"] for r in c.execute("PRAGMA table_info(snapshots)").fetchall()]
    if "fashion_score" not in snap_cols:
        c.execute("ALTER TABLE snapshots ADD COLUMN fashion_score REAL")

    vid_cols = [r["name"] for r in c.execute("PRAGMA table_info(videos)").fetchall()]
    for col in ("garments", "colors", "style", "tag_source", "brands", "items"):
        if col not in vid_cols:
            c.execute(f"ALTER TABLE videos ADD COLUMN {col} TEXT")

    # Time series of each trend, recorded once per scan -- lets us check later
    # whether things we called "rising" actually kept gaining (forecast accuracy).
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS trend_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tag         TEXT,
            kind        TEXT,
            scanned_at  REAL,
            videos      INTEGER,
            weight      REAL,
            momentum    TEXT
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_th_tag ON trend_history(tag, scanned_at)")


def set_tags(conn, video_id, garments, colors, style, source):
    """
    Save outfit tags for a video. 'source' is 'vision' (the bot watched it) or
    'caption' (guessed from text). We never overwrite richer 'vision' tags with
    weaker 'caption' tags.
    """
    import json
    row = conn.execute("SELECT tag_source FROM videos WHERE id=?", (video_id,)).fetchone()
    if row and row["tag_source"] == "vision" and source != "vision":
        return  # keep the better tags we already have
    conn.execute(
        "UPDATE videos SET garments=?, colors=?, style=?, tag_source=? WHERE id=?",
        (json.dumps(garments), json.dumps(colors), style or "", source, video_id),
    )


def set_brands(conn, video_id, brands, items):
    """Save the specific brands + 'Brand Garment' items found for a video."""
    import json
    conn.execute(
        "UPDATE videos SET brands=?, items=? WHERE id=?",
        (json.dumps(brands), json.dumps(items), video_id),
    )


def get_last_velocity(conn, video_id):
    """The velocity from the most recent previous snapshot of this video, if any."""
    row = conn.execute(
        "SELECT velocity FROM snapshots WHERE video_id=? ORDER BY scanned_at DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    return row["velocity"] if row else None


def upsert_video(conn, video):
    """Insert the video's identity, or update last_seen if we've seen it before."""
    now = time.time()
    existing = conn.execute("SELECT id FROM videos WHERE id=?", (video["id"],)).fetchone()
    if existing:
        conn.execute("UPDATE videos SET last_seen=?, title=?, author=? WHERE id=?",
                     (now, video.get("title"), video.get("author"), video["id"]))
    else:
        conn.execute(
            """INSERT INTO videos (id, platform, author, title, url, post_time, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?)""",
            (video["id"], video["platform"], video.get("author"), video.get("title"),
             video.get("url"), video.get("post_time"), now, now),
        )


def insert_snapshot(conn, video_id, scored, raw, acceleration_val, fashion_score=None):
    """Log one measurement of this video."""
    conn.execute(
        """INSERT INTO snapshots
           (video_id, scanned_at, views, likes, comments, shares,
            age_hours, velocity, freshness, trend_score, acceleration, fashion_score)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            video_id, time.time(),
            raw.get("views", 0), raw.get("likes", 0),
            raw.get("comments", 0), raw.get("shares", 0),
            scored["age_hours"], scored["velocity"], scored["freshness"],
            scored["trend_score"], acceleration_val, fashion_score,
        ),
    )


def delete_video(conn, video_id):
    """Remove a video and all its snapshots (e.g. vision says it's not clothing)."""
    conn.execute("DELETE FROM snapshots WHERE video_id=?", (video_id,))
    conn.execute("DELETE FROM videos WHERE id=?", (video_id,))


def record_trend_history(conn, items, now):
    """Save this scan's trend state (one row per garment) for accuracy tracking."""
    for it in items:
        conn.execute(
            """INSERT INTO trend_history (tag, kind, scanned_at, videos, weight, momentum)
               VALUES (?,?,?,?,?,?)""",
            (it.get("tag"), it.get("kind", "garment"), now,
             it.get("videos", 0), it.get("weight", 0.0), it.get("momentum", "")),
        )


def forecast_report(lookahead_hours=24, limit=12):
    """
    Did our "rising" calls actually keep gaining?

    For each time we flagged a tag "rising", we look ~lookahead_hours later:
      - confirmed: its weight grew
      - missed:    it didn't
      - pending:   not enough time has passed yet to judge
    Returns an overall hit-rate plus a recent track record.
    """
    from collections import defaultdict
    conn = connect()
    rows = conn.execute(
        "SELECT tag, scanned_at, weight, momentum FROM trend_history ORDER BY tag, scanned_at"
    ).fetchall()
    conn.close()

    series = defaultdict(list)
    for r in rows:
        series[r["tag"]].append(dict(r))

    look = lookahead_hours * 3600
    hits = total = pending = 0
    calls = []
    for tag, arr in series.items():
        for i, rec in enumerate(arr):
            if rec["momentum"] != "rising":
                continue
            future = [a for a in arr[i + 1:]
                      if a["scanned_at"] - rec["scanned_at"] >= look]
            if not future:
                calls.append({"tag": tag, "called_at": rec["scanned_at"], "outcome": "pending"})
                pending += 1
                continue
            grew = (future[0]["weight"] or 0) > (rec["weight"] or 0)
            total += 1
            hits += 1 if grew else 0
            calls.append({"tag": tag, "called_at": rec["scanned_at"],
                          "outcome": "confirmed" if grew else "missed"})

    calls.sort(key=lambda c: c["called_at"], reverse=True)
    rate = round(hits / total * 100, 1) if total else None
    return {"rate": rate, "hits": hits, "total": total, "pending": pending,
            "calls": calls[:limit]}


# ---- Read helpers used by the dashboard ----

def top_trending(limit=50, platform=None, max_age_hours=None, min_fashion=None):
    """
    The latest snapshot for each video, ranked by trend_score.
    Optionally filter by platform, recency, or minimum clothing relevance.
    """
    conn = connect()
    # Grab the most recent snapshot per video, joined to its identity.
    query = """
        SELECT v.*, s.views, s.likes, s.comments, s.shares, s.age_hours,
               s.velocity, s.freshness, s.trend_score, s.acceleration,
               s.fashion_score, s.scanned_at
        FROM videos v
        JOIN snapshots s ON s.id = (
            SELECT id FROM snapshots WHERE video_id = v.id
            ORDER BY scanned_at DESC LIMIT 1
        )
        WHERE 1=1
    """
    params = []
    if platform and platform != "all":
        query += " AND v.platform = ?"
        params.append(platform)
    if max_age_hours:
        query += " AND s.age_hours <= ?"
        params.append(max_age_hours)
    if min_fashion is not None:
        query += " AND COALESCE(s.fashion_score, 0) >= ?"
        params.append(min_fashion)
    query += " ORDER BY s.trend_score DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clothing_rows_with_tags(min_fashion=0.35, max_age_hours=None, style=None,
                            vetted_only=False):
    """
    The latest snapshot of every trending CLOTHING video, with its outfit tags.
    This is what we feed into tags.aggregate_themes() to find trending outfits.
    """
    conn = connect()
    query = """
        SELECT v.garments, v.colors, v.style, v.brands, v.items,
               v.url, v.author, v.title, v.first_seen, v.last_seen,
               s.trend_score, s.fashion_score, s.age_hours, s.likes
        FROM videos v
        JOIN snapshots s ON s.id = (
            SELECT id FROM snapshots WHERE video_id = v.id
            ORDER BY scanned_at DESC LIMIT 1
        )
        WHERE COALESCE(s.fashion_score, 0) >= ?
    """
    params = [min_fashion]
    if max_age_hours:
        query += " AND s.age_hours <= ?"
        params.append(max_age_hours)
    if style:
        query += " AND LOWER(v.style) = ?"
        params.append(style.strip().lower())
    if vetted_only:
        # Only posts the vision model actually checked (person + quality + specific).
        query += " AND v.tag_source = 'vision'"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def video_history(video_id):
    """Every snapshot for one video, oldest first -- used to draw its trend line."""
    conn = connect()
    rows = conn.execute(
        "SELECT scanned_at, trend_score, velocity, views FROM snapshots WHERE video_id=? ORDER BY scanned_at ASC",
        (video_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def stats():
    """Quick numbers for the dashboard header."""
    conn = connect()
    v = conn.execute("SELECT COUNT(*) n FROM videos").fetchone()["n"]
    s = conn.execute("SELECT COUNT(*) n FROM snapshots").fetchone()["n"]
    last = conn.execute("SELECT MAX(scanned_at) t FROM snapshots").fetchone()["t"]
    conn.close()
    return {"videos": v, "snapshots": s, "last_scan": last}
