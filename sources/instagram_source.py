"""
instagram_source.py  --  Free Instagram scraping via the instaloader library.

⚠️  Even more fragile than TikTok. Instagram rate-limits hard and may require a
    login. If it fails, it prints a warning and returns an empty list -- the
    rest of the system keeps working.

    We only look at VIDEO posts (reels) for hashtags you choose, since this is a
    *video* trend scanner.

SETUP (see README for the friendly version):
  1. pip install instaloader
  2. (Recommended) log in once so IG trusts you more:
     instaloader --login=YOUR_IG_USERNAME
     then set in .env:  IG_USERNAME=YOUR_IG_USERNAME
  3. Choose hashtags in .env:  IG_HASHTAGS=reels,viral,trending
"""

import os
import time

# Default to FASHION hashtags so we mostly pull clothing reels. Override in .env.
HASHTAGS = [h.strip() for h in os.environ.get(
    "IG_HASHTAGS", "ootd,outfitinspo,fashionreels,styleinspo,thriftflip"
).split(",") if h.strip()]
IG_USERNAME = os.environ.get("IG_USERNAME", "")
# How many posts to pull per hashtag before moving on (keep small to avoid bans).
PER_HASHTAG = int(os.environ.get("IG_PER_HASHTAG", "15"))


def _parse(post):
    """Turn an instaloader Post into our standard shape."""
    return {
        "id": f"instagram:{post.shortcode}",
        "platform": "instagram",
        "author": f"@{post.owner_username}",
        "title": (post.caption or "")[:200],
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "post_time": post.date_utc.timestamp() if post.date_utc else time.time(),
        # IG doesn't expose view counts for everything; use what we can get.
        "views": int(getattr(post, "video_view_count", 0) or 0),
        "likes": int(getattr(post, "likes", 0) or 0),
        "comments": int(getattr(post, "comments", 0) or 0),
        "shares": 0,  # Instagram doesn't expose share counts publicly.
    }


def fetch(limit=30):
    try:
        import instaloader
    except ModuleNotFoundError:
        print("  [instagram] instaloader not installed -- skipping. (pip install instaloader)")
        return []

    L = instaloader.Instaloader(quiet=True, download_pictures=False,
                                download_videos=False, download_comments=False,
                                save_metadata=False)

    # Try to use a saved login session so IG trusts us more.
    if IG_USERNAME:
        try:
            L.load_session_from_file(IG_USERNAME)
        except Exception as e:
            print(f"  [instagram] no saved session for {IG_USERNAME} ({e}); continuing anonymously")

    results = []
    for tag in HASHTAGS:
        if len(results) >= limit:
            break
        try:
            hashtag = instaloader.Hashtag.from_name(L.context, tag)
            count = 0
            for post in hashtag.get_posts():
                if not post.is_video:
                    continue  # video trends only
                parsed = _parse(post)
                parsed["source_tag"] = tag  # which fashion hashtag it came from
                results.append(parsed)
                count += 1
                if count >= PER_HASHTAG or len(results) >= limit:
                    break
        except Exception as e:
            print(f"  [instagram] hashtag #{tag} failed ({e}) -- skipping it.")

    return results[:limit]
