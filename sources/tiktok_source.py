"""
tiktok_source.py  --  Free TikTok scraping via the TikTokApi library.

⚠️  This is the fragile part. TikTok actively fights scraping, so this can break
    when they change their site. When it does, it prints a warning and returns
    an empty list -- your database and dashboard keep working fine.

SETUP (see README for the friendly version):
  1. pip install TikTokApi
  2. python -m playwright install chromium
  3. Get an "ms_token": open tiktok.com in a browser, log in, open DevTools
     -> Application -> Cookies -> copy the value of the cookie named "msToken".
  4. Put it in your .env file as:  TIKTOK_MS_TOKEN=that_long_value
"""

import os
import time
import asyncio

# Comma-separated hashtags to scan if the "trending" feed isn't available.
# e.g. TIKTOK_HASHTAGS=fyp,viral,news
# Default to FASHION hashtags so we mostly pull clothing videos. Override in .env.
HASHTAGS = [h.strip() for h in os.environ.get(
    "TIKTOK_HASHTAGS", "ootd,outfit,fashiontiktok,thriftflip,streetwear,grwm"
).split(",") if h.strip()]
MS_TOKEN = os.environ.get("TIKTOK_MS_TOKEN", "")


def _parse(video_dict):
    """Turn TikTok's raw video dict into our standard shape."""
    stats = video_dict.get("stats", {}) or video_dict.get("statsV2", {})
    author = video_dict.get("author", {})
    author_name = author.get("uniqueId") if isinstance(author, dict) else str(author)
    return {
        "id": f"tiktok:{video_dict.get('id')}",
        "platform": "tiktok",
        "author": f"@{author_name}" if author_name else None,
        "title": (video_dict.get("desc") or "")[:200],
        "url": f"https://www.tiktok.com/@{author_name}/video/{video_dict.get('id')}",
        "post_time": float(video_dict.get("createTime", time.time())),
        "views": int(stats.get("playCount", 0) or 0),
        "likes": int(stats.get("diggCount", 0) or 0),
        "comments": int(stats.get("commentCount", 0) or 0),
        "shares": int(stats.get("shareCount", 0) or 0),
    }


async def _fetch_async(limit):
    from TikTokApi import TikTokApi  # imported here so a missing lib doesn't crash import

    results = []
    ms_tokens = [MS_TOKEN] if MS_TOKEN else None
    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=ms_tokens, num_sessions=1, sleep_after=3,
                                  headless=True)
        # First try the global trending feed.
        try:
            async for video in api.trending.videos(count=limit):
                results.append(_parse(video.as_dict))
                if len(results) >= limit:
                    break
        except Exception as e:
            print(f"  [tiktok] trending feed unavailable ({e}); falling back to hashtags")

        # If trending gave us little/nothing, pull from hashtags instead.
        if len(results) < limit:
            for tag in HASHTAGS:
                try:
                    htag = api.hashtag(name=tag)
                    async for video in htag.videos(count=limit):
                        parsed = _parse(video.as_dict)
                        parsed["source_tag"] = tag  # which fashion hashtag it came from
                        results.append(parsed)
                        if len(results) >= limit:
                            break
                except Exception as e:
                    print(f"  [tiktok] hashtag #{tag} failed: {e}")
                if len(results) >= limit:
                    break
    return results


def fetch(limit=30):
    try:
        return asyncio.run(_fetch_async(limit))
    except ModuleNotFoundError:
        print("  [tiktok] TikTokApi not installed -- skipping. (pip install TikTokApi)")
        return []
    except Exception as e:
        print(f"  [tiktok] scrape failed ({e}) -- skipping this scan, system OK.")
        return []
