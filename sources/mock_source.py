"""
mock_source.py  --  Fake but realistic data.

This exists so you can SEE the whole system working (scoring, logging,
dashboard) before you finish setting up the real TikTok/Instagram scrapers.

It invents a handful of believable trending videos with varied ages and
engagement, so the trend scores look real. Each run nudges the numbers so that
across multiple scans you can watch trends rise and fall on the dashboard.
"""

import hashlib
import time

# A small library of pretend trending videos. Most are clothing-centered (these
# should show up on the dashboard); the last two are NOT about clothes, so you
# can confirm the fashion filter correctly throws them out.
_TOPICS = [
    # (platform, author, caption, hashtag it came from)
    ("tiktok", "@thriftqueen", "$15 thrift flip into a designer-looking outfit", "thriftflip"),
    ("tiktok", "@menswear.dan", "How to style ONE jacket 5 different ways", "menswear"),
    ("instagram", "@ootd.daily", "Fall OOTD: oversized blazer + baggy jeans + boots", "ootd"),
    ("tiktok", "@sneakerhead", "Unboxing the new sneaker colorway everyone wants", "streetwear"),
    ("instagram", "@denimlove", "The perfect baggy jeans finally exist 👖", "fashion"),
    ("tiktok", "@grwm.lily", "GRWM: quiet luxury dress for dinner", "grwm"),
    ("instagram", "@vintage.vera", "Y2K vintage fashion haul — try-on", "y2kfashion"),
    ("tiktok", "@stylebyme", "Capsule wardrobe: 10 pieces, 30 outfits", "capsulewardrobe"),
    # --- NOT clothing: these should be filtered OUT ---
    ("tiktok", "@chefmika", "60-second one-pan pasta that broke the internet", "fyp"),
    ("tiktok", "@sciencepls", "This optical illusion is melting people's brains", "viral"),
]


def _pseudo(seed_text, lo, hi):
    """Deterministic-ish pseudo number from text, so a given video has stable-ish stats."""
    h = int(hashlib.md5(seed_text.encode()).hexdigest(), 16)
    return lo + (h % (hi - lo))


def fetch(limit=20):
    now = time.time()
    videos = []
    # Use the current 5-minute bucket so numbers drift slowly between scans,
    # letting you watch trends move over time.
    bucket = int(now // 300)

    for i, (platform, author, title, tag) in enumerate(_TOPICS):
        # Vary how long ago each was posted: from 2 hours to ~8 days old.
        age_h = _pseudo(author, 2, 200)
        post_time = now - age_h * 3600

        # Base engagement grows with the drift bucket so the trend "moves".
        base = _pseudo(title, 5000, 900000)
        drift = (bucket % 50) * (i + 1) * 37  # small per-scan change
        views = base + drift * 100
        likes = int(views * 0.08)
        comments = int(views * 0.01)
        shares = int(views * 0.005)

        videos.append({
            "id": f"{platform}:mock{i}",
            "platform": platform,
            "author": author,
            "title": title,
            "source_tag": tag,
            "url": f"https://example.com/{platform}/mock{i}",
            "post_time": post_time,
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
        })

    return videos[:limit]
