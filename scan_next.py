"""
scan_next.py  --  Background rotation worker.

Each time it runs it scrapes the NEXT style in the rotation, keeping every
style's data fresh in the database. That way the dashboard never scrapes on a
click -- it just reads pre-collected data instantly.

The LaunchAgent calls this on a timer; over a few hours it cycles all styles.
"""

import json
import os
import subprocess

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

import styles
import accounts

PROJECT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(PROJECT, "rotation.json")


def next_style():
    order = styles.all_styles()
    try:
        idx = json.load(open(STATE)).get("idx", 0)
    except Exception:
        idx = 0
    style = order[idx % len(order)]
    json.dump({"idx": (idx + 1) % len(order)}, open(STATE, "w"))
    return style


def main():
    # Don't start if a scan is already running (avoids DB-lock collisions).
    if subprocess.run(["pgrep", "-f", "scanner.py"], capture_output=True).returncode == 0:
        print("[rotation] a scan is already running -- skipping this tick")
        return
    style = next_style()
    cloud = bool(os.environ.get("APIFY_TOKEN", "").strip())
    handles = accounts.accounts_for(style)
    env = os.environ.copy()
    env["FORCE_STYLE"] = style
    env["VISION_TOP_N"] = "18"   # only used when NOT cloud (cloud visions all)
    if cloud and handles:
        # Best: pull from curated fashionable creators (high-like, on-trend).
        source = "instagram_accounts"
        env["IG_ACCOUNTS"] = ",".join(handles)
    elif cloud:
        # No curated accounts for this style yet -> fall back to hashtag scrape.
        source = "instagram_apify"
        env["IG_HASHTAGS"] = ",".join(styles.hashtags_for(style))
        env["SCRAPE_LIMIT"] = "1000"
    else:
        source = "instagram"   # local browser fallback
        env["IG_HASHTAGS"] = ",".join(styles.hashtags_for(style))
        env["SCRAPE_LIMIT"] = "150"
    env["SOURCES"] = source
    print(f"[rotation] scanning style: {style} via {source}")
    py = os.path.join(PROJECT, "venv", "bin", "python")
    subprocess.run([py, os.path.join(PROJECT, "scanner.py"), "--sources", source],
                   cwd=PROJECT, env=env)


if __name__ == "__main__":
    main()
