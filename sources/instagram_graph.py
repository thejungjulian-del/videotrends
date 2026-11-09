"""
instagram_graph.py  --  Instagram's OFFICIAL Graph API (no scraping, no bans).

This uses Meta's sanctioned Hashtag Search API to pull the top + recent posts for
each fashion hashtag, with like counts, captions, and image URLs. It's free and
durable -- nothing here violates Instagram's terms or risks an account ban.

You need two things in your .env (see README / ig_graph_setup.py):
  IG_GRAPH_TOKEN = a (long-lived) user access token
  IG_USER_ID     = your Instagram Business/Creator account's user id

Only posts from PUBLIC Business/Creator accounts appear in hashtag results
(that's an Instagram rule, not ours) -- which still covers most fashion creators.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

VERSION = os.environ.get("GRAPH_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"

TOKEN = os.environ.get("IG_GRAPH_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "")
HASHTAGS = [h.strip() for h in os.environ.get(
    "IG_HASHTAGS", "ootd,outfitinspo,fashion,streetwear,thriftflip,grwm,styleinspo"
).split(",") if h.strip()]

MEDIA_FIELDS = ("id,caption,media_type,media_url,thumbnail_url,permalink,"
                "like_count,comments_count,timestamp")


def _get(path, params):
    """GET a Graph API endpoint, return parsed JSON (or None on error)."""
    params = dict(params)
    params["access_token"] = TOKEN
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {}).get("message", str(e))
        except Exception:
            err = str(e)
        print(f"  [ig-graph] API error on {path}: {err}")
        return None
    except Exception as e:
        print(f"  [ig-graph] request failed on {path}: {e}")
        return None
    if isinstance(data, dict) and data.get("error"):
        print(f"  [ig-graph] {data['error'].get('message')}")
        return None
    return data


def _hashtag_id(tag):
    """Resolve a hashtag name to its Graph API id (required before fetching media)."""
    data = _get("ig_hashtag_search", {"user_id": USER_ID, "q": tag})
    edges = (data or {}).get("data") or []
    return edges[0]["id"] if edges else None


def _parse(m, source_tag):
    """Turn one Graph API media object into our standard shape."""
    code = m.get("id")
    if not code:
        return None

    mtype = m.get("media_type")
    img = m.get("media_url")
    if mtype == "VIDEO":
        img = m.get("thumbnail_url") or img
    if not img:
        return None

    # timestamp like "2026-06-05T12:34:56+0000"
    ts = m.get("timestamp")
    try:
        post_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        post_time = time.time()

    return {
        "id": f"instagram:{code}",
        "platform": "instagram",
        "author": None,  # Graph API hashtag media doesn't expose the owner
        "title": (m.get("caption") or "")[:200],
        "url": m.get("permalink") or f"https://www.instagram.com/p/{code}/",
        "image_url": img,
        "source_tag": source_tag,
        "post_time": float(post_time),
        "views": 0,  # not provided for hashtag media
        "likes": int(m.get("like_count") or 0),
        "comments": int(m.get("comments_count") or 0),
        "shares": 0,
    }


def fetch(limit=None):
    if not TOKEN or not USER_ID:
        print("  [ig-graph] IG_GRAPH_TOKEN / IG_USER_ID not set -- skipping. "
              "(Run ig_graph_setup.py; see README.)")
        return []

    results = []
    for tag in HASHTAGS:
        hid = _hashtag_id(tag)
        if not hid:
            continue
        # top_media = most-engaged (vetted), recent_media = freshest. Use both.
        for edge in ("top_media", "recent_media"):
            data = _get(f"{hid}/{edge}", {"user_id": USER_ID, "fields": MEDIA_FIELDS})
            for m in (data or {}).get("data", []):
                parsed = _parse(m, tag)
                if parsed:
                    results.append(parsed)
        print(f"  [ig-graph] #{tag}: {sum(1 for r in results if r['source_tag']==tag)} posts")

    # De-dupe (a post can appear in both top and recent, or across tags).
    seen, unique = set(), []
    for v in results:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        unique.append(v)
    return unique[:limit] if limit else unique
