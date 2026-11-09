"""
scoring.py  --  The "brain" of the trend scanner.

This is the part you specifically asked for: instead of just ranking by views
and likes, we reward videos that are gaining engagement FAST and were posted
RECENTLY. A video with 200k views in 1 day is a hotter trend than one with
200k views over 3 months.

Three numbers do the work:
  1. velocity   = engagement per hour since it was posted  ("how fast is it rising")
  2. freshness  = a bonus for being posted recently        ("how new is it")
  3. trend_score= velocity boosted by freshness            (the final ranking number)

Plus, when we've seen a video in a previous scan, we compute:
  4. acceleration = is its velocity going UP or DOWN since last time we looked
     (this is what actually tells you a trend is climbing vs. fading)
"""

import math
import time

# How much each type of engagement is "worth" when we add it all up.
# A comment is a stronger signal than a like, a share stronger still,
# because they take more effort and spread the video further.
ENGAGEMENT_WEIGHTS = {
    "views": 1.0,
    "likes": 5.0,
    "comments": 10.0,
    "shares": 15.0,
}

# Freshness half-life in hours. Lower = the scanner cares more about brand-new
# posts. 72 hours (3 days) means a 3-day-old post gets about half the freshness
# bonus of a brand-new one. Tweak this to make the scanner more/less "newsy".
FRESHNESS_HALFLIFE_HOURS = 72.0


def total_engagement(views, likes, comments, shares):
    """Combine the raw counts into one weighted engagement number."""
    return (
        (views or 0) * ENGAGEMENT_WEIGHTS["views"]
        + (likes or 0) * ENGAGEMENT_WEIGHTS["likes"]
        + (comments or 0) * ENGAGEMENT_WEIGHTS["comments"]
        + (shares or 0) * ENGAGEMENT_WEIGHTS["shares"]
    )


def age_hours(post_time_unix, now=None):
    """How many hours ago this was posted. Floored at 1 so we never divide by ~0."""
    now = now or time.time()
    hours = (now - post_time_unix) / 3600.0
    return max(hours, 1.0)


def velocity(engagement, age_h):
    """Engagement gained per hour. This is the core 'how fast is it rising' number."""
    return engagement / age_h


def freshness(age_h):
    """
    A multiplier between ~0 and 1 that rewards recent posts.
    Brand new  -> close to 1.0
    Very old   -> close to 0.0
    Uses exponential decay with the half-life set above.
    """
    return math.exp(-age_h / FRESHNESS_HALFLIFE_HOURS)


def trend_score(views, likes, comments, shares, post_time_unix, now=None):
    """
    The final ranking number for a single video snapshot.

    Returns a dict with all the pieces so the database and dashboard can show
    WHY something is trending, not just the final score.
    """
    eng = total_engagement(views, likes, comments, shares)
    a = age_hours(post_time_unix, now)
    v = velocity(eng, a)
    f = freshness(a)

    # The score is velocity, boosted by freshness. The (1 + f) means even an
    # older-but-fast-rising video still scores on its velocity, while a fresh
    # one gets up to a 2x boost.
    score = v * (1.0 + f)

    return {
        "engagement": round(eng, 2),
        "age_hours": round(a, 2),
        "velocity": round(v, 4),
        "freshness": round(f, 4),
        "trend_score": round(score, 4),
    }


def acceleration(current_velocity, previous_velocity):
    """
    Compare velocity now vs. the last time we scanned this video.

    Positive  -> the trend is speeding up (climbing)   🔼
    Near zero -> steady
    Negative  -> the trend is slowing down (fading)    🔽

    Returned as a percent change so it's easy to read on the dashboard.
    """
    if not previous_velocity or previous_velocity == 0:
        return None  # we have nothing to compare to yet
    return round((current_velocity - previous_velocity) / previous_velocity * 100.0, 1)
