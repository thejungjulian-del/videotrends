"""
dashboard.py  --  The website.

Run it:   python dashboard.py
Then open: http://localhost:8775  in your browser.

It reads from the same database the scanner writes to, so as the scanner logs
new scans, refreshing the page shows the latest trends.
"""

import os
import json
import time
import subprocess
from flask import Flask, render_template, jsonify, request

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

import db
import tags as tagger
import styles as style_menu
import accounts as account_menu

app = Flask(__name__)

PROJECT = os.path.dirname(os.path.abspath(__file__))
FIND_STATUS = os.path.join(PROJECT, "find_status.json")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _scan_running():
    """True if ANY scan (scheduled or on-demand) is currently running."""
    try:
        out = subprocess.run(["pgrep", "-f", "scanner.py"], capture_output=True)
        return out.returncode == 0
    except Exception:
        return False


@app.route("/")
def home():
    return render_template("dashboard.html", styles=style_menu.all_styles())


@app.route("/api/trending")
def api_trending():
    """The dashboard fetches this to get the ranked list of trends."""
    platform = request.args.get("platform", "all")
    sort = request.args.get("sort", "trend_score")  # trend_score | velocity | views | acceleration | fashion_score
    max_age = request.args.get("max_age_hours", type=float)
    # Only show videos that are at least this clothing-relevant (0..1).
    min_fashion = request.args.get("min_fashion", default=0.2, type=float)

    rows = db.top_trending(limit=100, platform=platform, max_age_hours=max_age,
                           min_fashion=min_fashion)

    # Optional re-sort by a different column.
    if sort in ("velocity", "views", "acceleration", "fashion_score"):
        rows.sort(key=lambda r: (r.get(sort) or 0), reverse=True)

    return jsonify({"stats": db.stats(), "items": rows})


@app.route("/api/themes")
def api_themes():
    """The trending OUTFITS: which garments/colors/styles recur across trending videos."""
    min_fashion = request.args.get("min_fashion", default=0.2, type=float)
    max_age = request.args.get("max_age_hours", type=float)
    style = request.args.get("style") or None
    rows = db.clothing_rows_with_tags(min_fashion=min_fashion, max_age_hours=max_age,
                                      style=style, vetted_only=True)
    result = tagger.aggregate_themes(rows, top=30, now=time.time())
    result["stats"] = db.stats()
    result["forecast"] = db.forecast_report()
    result["style"] = style
    return jsonify(result)


@app.route("/api/find", methods=["POST", "GET"])
def api_find():
    """Kick off an on-demand live scrape of one style's hashtags."""
    style = (request.args.get("style") or "").strip()
    tags = style_menu.hashtags_for(style)
    if not tags:
        return jsonify({"error": f"unknown style '{style}'"}), 400
    if _scan_running():
        return jsonify({"status": "busy"})

    cloud = bool(os.environ.get("APIFY_TOKEN", "").strip())
    handles = account_menu.accounts_for(style)
    env = os.environ.copy()
    env["FORCE_STYLE"] = style
    env["VISION_TOP_N"] = "20"
    if cloud and handles:
        source = "instagram_accounts"
        env["IG_ACCOUNTS"] = ",".join(handles)
    elif cloud:
        source = "instagram_apify"
        env["IG_HASHTAGS"] = ",".join(tags)
        env["SCRAPE_LIMIT"] = "1000"
    else:
        source = "instagram"
        env["IG_HASHTAGS"] = ",".join(tags)
        env["SCRAPE_LIMIT"] = "200"
    env["SOURCES"] = source

    py = os.path.join(PROJECT, "venv", "bin", "python")
    logf = open(os.path.join(PROJECT, "find.log"), "a")
    proc = subprocess.Popen([py, os.path.join(PROJECT, "scanner.py"), "--sources", source],
                            cwd=PROJECT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    json.dump({"style": style, "pid": proc.pid, "started": time.time()},
              open(FIND_STATUS, "w"))
    return jsonify({"status": "started", "style": style})


@app.route("/api/find_status")
def api_find_status():
    """Tell the dashboard whether the on-demand scan has finished."""
    try:
        s = json.load(open(FIND_STATUS))
    except Exception:
        return jsonify({"running": False, "style": None})
    return jsonify({"running": _pid_alive(s["pid"]), "style": s["style"],
                    "elapsed": round(time.time() - s["started"])})


@app.route("/api/history/<path:video_id>")
def api_history(video_id):
    """Trend-over-time data for one video (used for the mini chart)."""
    return jsonify(db.video_history(video_id))


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", "8775"))
    print(f"\n🌐 Dashboard running -> http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
