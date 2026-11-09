"""
audience.py  --  Guess whether a video is aimed at TEENS / EARLY ADULTS.

IMPORTANT: we can't see who actually watches a video (their ages aren't public).
So this is an INFERENCE of the content's apparent target audience, based on:
  - the hashtag it came from   (y2k/grwm skew young; old-money skews older)
  - the aesthetic/style         (from the vision model)
  - the caption language         (youth slang)

It returns a 0.0-1.0 "youth score":
   ~0.5 = neutral (could be any age) -> kept by default
   high = clearly young-skewing
   low  = clearly older-skewing      -> filtered out
"""

# Hashtags that skew young vs. older.
YOUTH_HASHTAGS = {
    "y2k", "y2kfashion", "grwm", "fitcheck", "thriftflip", "thrift", "streetwear",
    "coquette", "grunge", "ootd", "outfit", "fashiontiktok", "altfashion",
    "ootdfashion", "fyp", "downtowngirl", "balletcore", "cleangirl",
}
OLDER_HASHTAGS = {
    "oldmoney", "quietluxury", "businesscasual", "workwear", "classicstyle",
    "over40fashion", "maturefashion", "corporatestyle", "officewear",
}

# Aesthetics (from the vision model OR the caption text).
YOUTH_STYLES = [
    "y2k", "coquette", "grunge", "streetwear", "e-girl", "egirl", "indie",
    "cottagecore", "downtown", "skater", "emo", "alt", "balletcore",
    "fairycore", "clean girl", "indie sleaze", "mob wife", "grwm",
]
OLDER_STYLES = [
    "old money", "quiet luxury", "business casual", "business", "formal",
    "corporate", "classic", "sophisticated", "mature", "elegant", "timeless",
    "professional", "tailored",
]

# Caption words.
YOUTH_TERMS = [
    "grwm", "fit check", "fitcheck", "core", "slay", "haul", "thrift",
    "back to school", "for school", "college", "dorm", "prom", "festival",
    "concert fit", "obsessed", "tiktok made me", "trend", "ootd", "fyp",
]
OLDER_TERMS = [
    "office", "workwear", "work outfit", "9 to 5", "9-5", "corporate",
    "business meeting", "mature", "over 40", "professional",
]


def _hit(text, terms):
    return sum(1 for w in terms if w in text)


def youth_score(text, source_tag=None, style=None):
    """Return 0.0-1.0 estimate that this video targets teens / early adults."""
    t = (text or "").lower()
    score = 0.5  # start neutral

    tag = (source_tag or "").lower().lstrip("#")
    if tag in YOUTH_HASHTAGS:
        score += 0.25
    if tag in OLDER_HASHTAGS:
        score -= 0.30

    st = (style or "").lower()
    if any(s in st for s in YOUTH_STYLES):
        score += 0.30
    if any(s in st for s in OLDER_STYLES):
        score -= 0.40

    # Same aesthetics mentioned in the caption text count too (weaker).
    if any(s in t for s in YOUTH_STYLES):
        score += 0.15
    if any(s in t for s in OLDER_STYLES):
        score -= 0.25

    score += min(0.30, 0.10 * _hit(t, YOUTH_TERMS))
    score -= min(0.40, 0.15 * _hit(t, OLDER_TERMS))

    return max(0.0, min(1.0, round(score, 3)))
