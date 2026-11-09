"""
scanner.py  --  The engine. Run this to do ONE scan.

What it does, in order:
  1. Loads your settings from .env
  2. Asks each enabled source (mock / tiktok / instagram) for current videos
  3. Scores each video (velocity + freshness -> trend_score)
  4. Compares to the last time we saw it (acceleration: climbing or fading?)
  5. Logs everything to the database

Run it by hand:        python scanner.py
Run only some sources:  python scanner.py --sources tiktok,instagram
Use the mock data:      python scanner.py --sources mock

To run it automatically every 30 minutes, see the README (cron section).
"""

import argparse
import os
import sys
import time

# Load .env if python-dotenv is available (optional but convenient).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

import db
import scoring
import fashion
import audience
import tags as tagger
import brands as brand_finder
from sources import SOURCES

# If a real video file is available, watch it with the local vision model.
# (mock videos have no file, so they fall back to caption tags.)
WATCH_VIDEOS = os.environ.get("WATCH_VIDEOS", "1") == "1"
# The funnel: run the slow vision model on only the top N videos per scan
# (by trend score). Everything else gets fast caption tags. Keeps scans quick
# while still logging LOTS of videos for trustworthy trend counts.
VISION_TOP_N = int(os.environ.get("VISION_TOP_N", "15"))
# With cloud vision (Gemini, ~1-2s/img) we can afford to vision EVERY kept post,
# so commonality is computed across hundreds/thousands, not just the top N.
CLOUD_VISION = bool(os.environ.get("GEMINI_API_KEY", "").strip())

# Only keep videos whose clothing-relevance is at least this (0..1).
# Kept LOW so we also catch thirst-trap / general videos where an outfit is
# shown but the caption isn't "about fashion" -- those still signal what people
# consider good clothes. The vision model does the real outfit detection.
FASHION_MIN = float(os.environ.get("FASHION_MIN", "0.2"))

# --- Quality gates (a video must pass ALL of these to be logged) ---
# Newest-only: skip anything older than this many hours. 168 = 1 week (the cap).
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "168"))
# Must have at least this many likes (real engagement, not a dud).
MIN_LIKES = int(os.environ.get("MIN_LIKES", "500"))
# Must be rising at least this fast (engagement per hour). 0 = off.
MIN_VELOCITY = float(os.environ.get("MIN_VELOCITY", "0"))
# Keep content aimed at teens / early adults. 0..1; ~0.5 is neutral.
# 0.5 = only clearly young-skewing content; 0 = off (any audience).
MIN_YOUTH = float(os.environ.get("MIN_YOUTH", "0.5"))

# When set (by the on-demand "Find a style" feature), every kept post is stamped
# with this style so the dashboard can show that style's trends exactly.
FORCE_STYLE = os.environ.get("FORCE_STYLE", "").strip()

# Drop posts the vision model rates below this quality (0..1): tacky / low-effort
# / spammy / AI-fake get cut. 0.5 = normal; raise to be pickier; 0 = off.
QUALITY_MIN = float(os.environ.get("QUALITY_MIN", "0.5"))


def _watch_if_possible(v):
    """
    Try to have the local vision model LOOK at this video.
    - If we have a downloaded video file (local_path), watch the whole thing.
    - Else if we have a cover image URL (from our scraper), download + analyze it.
    Returns the vision tags dict, or None if we couldn't watch it.
    """
    import tempfile, urllib.request
    try:
        import watcher
    except Exception:
        return None

    local_path = v.get("local_path")
    if local_path and os.path.exists(local_path):
        try:
            return watcher.watch_video(local_path)
        except Exception as e:
            print(f"  [watch] video failed for {v['id']} ({e})")
            return None

    image_url = v.get("image_url")
    if image_url:
        try:
            referer = ("https://www.instagram.com/" if v.get("platform") == "instagram"
                       else "https://www.tiktok.com/")
            req = urllib.request.Request(image_url, headers={
                "User-Agent": "Mozilla/5.0", "Referer": referer})
            data = urllib.request.urlopen(req, timeout=15).read()
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(data)
                tmp = f.name
            result = watcher.analyze_image(tmp)
            os.unlink(tmp)
            return result
        except Exception as e:
            print(f"  [watch] cover image failed for {v['id']} ({e})")
            return None
    return None


def run_scan(source_names):
    db.init_db()
    conn = db.connect()
    now = time.time()
    total_logged = 0
    total_skipped = 0

    for name in source_names:
        fetch = SOURCES.get(name)
        if not fetch:
            print(f"[skip] unknown source '{name}'")
            continue

        print(f"[{name}] fetching...")
        try:
            videos = fetch()
        except Exception as e:
            print(f"[{name}] FAILED entirely ({e}) -- skipping, system OK.")
            continue

        print(f"[{name}] got {len(videos)} videos")
        kept = 0
        kept_videos = []  # (video, trend_score) -- used to pick what to watch
        skips = {"old": 0, "likes": 0, "offtopic": 0, "notclothes": 0,
                 "noperson": 0, "lowquality": 0, "mature": 0, "slow": 0}
        for v in videos:
            # GATE 1 — age cap: nothing older than the limit (default 1 week).
            age_h = scoring.age_hours(v.get("post_time", now), now=now)
            if age_h > MAX_AGE_HOURS:
                skips["old"] += 1
                continue

            # GATE 2 — minimum likes: must have real engagement.
            if (v.get("likes", 0) or 0) < MIN_LIKES:
                skips["likes"] += 1
                continue

            # GATE 2.5 — drop off-topic content (pregnancy, food, etc.).
            if fashion.is_excluded(v.get("title", "")):
                skips["offtopic"] += 1
                continue

            # GATE 3 — is this actually about clothes?
            fash = fashion.relevance(v.get("title", ""), v.get("source_tag"))
            if fash["score"] < FASHION_MIN:
                skips["notclothes"] += 1
                continue

            # GATE 4 — is it aimed at teens / early adults? (drop older-skewing)
            youth = audience.youth_score(v.get("title", ""), v.get("source_tag"))
            if youth < MIN_YOUTH:
                skips["mature"] += 1
                continue

            # Score how fast/fresh it's trending.
            scored = scoring.trend_score(
                v.get("views", 0), v.get("likes", 0),
                v.get("comments", 0), v.get("shares", 0),
                v.get("post_time", now), now=now,
            )

            # GATE 5 — minimum velocity: must actually be rising.
            if scored["velocity"] < MIN_VELOCITY:
                skips["slow"] += 1
                continue

            # Is it speeding up or slowing down vs last time?
            prev_v = db.get_last_velocity(conn, v["id"])
            accel = scoring.acceleration(scored["velocity"], prev_v)

            # Save the video + this measurement.
            db.upsert_video(conn, v)
            db.insert_snapshot(conn, v["id"], scored, v, accel, fash["score"])

            # FAST caption-based tags + brands for EVERY kept video.
            t = tagger.tags_from_text(v.get("title", ""))
            db.set_tags(conn, v["id"], t["garments"], t["colors"],
                        FORCE_STYLE or t["style"], "caption")
            cbrands, citems = brand_finder.specific_items(v.get("title", ""), t["garments"])
            db.set_brands(conn, v["id"], [b.title() for b in cbrands], citems)

            kept_videos.append((v, scored["trend_score"]))
            total_logged += 1
            kept += 1

        # FUNNEL: run the slow vision model on only the top videos this scan,
        # upgrading their tags from caption -> vision (richer garments/colors/brands).
        if WATCH_VIDEOS and kept_videos:
            top = sorted(kept_videos, key=lambda x: x[1], reverse=True)
            if not CLOUD_VISION:          # local vision is slow -> only top N
                top = top[:VISION_TOP_N]
            print(f"[{name}] watching {len(top)} of {len(kept_videos)} with vision model...")
            for v, _ in top:
                seen = _watch_if_possible(v)
                if not seen:
                    continue
                # VISION VETTING: drop (with a specific reason) if it isn't
                # clothing, has no person posing, or looks tacky/fake.
                reason = None
                if not seen.get("is_clothing") or not seen.get("garments"):
                    reason = "notclothes"
                elif not seen.get("has_person", True):
                    reason = "noperson"
                elif seen.get("quality", 1.0) < QUALITY_MIN:
                    reason = "lowquality"
                if reason:
                    db.delete_video(conn, v["id"])
                    total_logged -= 1
                    kept -= 1
                    skips[reason] += 1
                    conn.commit()
                    continue
                db.set_tags(conn, v["id"], seen.get("garments", []),
                            seen.get("colors", []),
                            FORCE_STYLE or seen.get("style", ""), "vision")
                cbrands, citems = brand_finder.specific_items(
                    v.get("title", ""), seen.get("garments", []))
                vbrands = [b.lower() for b in seen.get("brands", [])]
                allb = cbrands + [b for b in vbrands if b not in cbrands]
                db.set_brands(conn, v["id"], [b.title() for b in allb], citems)
                conn.commit()  # save after each video so the DB isn't locked for minutes
            conn.commit()

        total_skipped += sum(skips.values())
        print(f"[{name}] kept {kept} | skipped: "
              f"{skips['old']} old, {skips['likes']} <likes, {skips['offtopic']} offtopic, "
              f"{skips['notclothes']} notclothes, {skips['noperson']} no-person, "
              f"{skips['lowquality']} tacky/low-quality, {skips['mature']} mature, "
              f"{skips['slow']} slow")
        conn.commit()

    # Record this scan's trend state so we can later check forecast accuracy
    # (did the garments we called "rising" actually keep gaining?).
    try:
        rows = db.clothing_rows_with_tags(min_fashion=FASHION_MIN, max_age_hours=MAX_AGE_HOURS)
        themes = tagger.aggregate_themes(rows, top=60, now=now)
        db.record_trend_history(conn, themes.get("garments", []), now)
        conn.commit()
    except Exception as e:
        print(f"[trend-history] skipped ({e})")

    conn.close()
    print(f"\n✅ Scan complete: {total_logged} videos logged, "
          f"{total_skipped} skipped (old / low-engagement / non-clothing), at "
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    return total_logged


def main():
    parser = argparse.ArgumentParser(description="Video trend scanner")
    parser.add_argument(
        "--sources",
        default=os.environ.get("SOURCES", "mock"),
        help="comma-separated: mock,tiktok,instagram (default: mock)",
    )
    args = parser.parse_args()
    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    print(f"Sources this scan: {', '.join(source_names)}\n")
    run_scan(source_names)


if __name__ == "__main__":
    main()
