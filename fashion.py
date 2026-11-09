"""
fashion.py  --  The "is this video actually about CLOTHES?" detector.

We can't watch the video on a free setup, so we judge by its words: the
caption/title and which hashtag it came from. We score each video 0.0 -> 1.0
on how clothing-centered it looks. The scanner then keeps only videos above a
threshold, so your dashboard shows fashion trends -- not random viral stuff.

How the score works:
  - STRONG terms (outfit, ootd, dress, sneakers...) are worth a lot.
  - MEDIUM terms (style, haul, aesthetic...) are worth a little.
  - Coming FROM a fashion hashtag (e.g. it was scraped from #ootd) is a big
    head-start, because the whole feed is clothing.
"""

import re

# Words that strongly mean "this is about clothing/an outfit".
STRONG_TERMS = [
    "outfit", "ootd", "fit check", "fitcheck", "lookbook", "what i wore",
    "grwm", "get ready with me", "thrift", "thrifted", "thrift flip",
    "haul", "try on", "tryon", "try-on", "capsule wardrobe", "wardrobe",
    "styling", "how to style", "style this", "dress", "dresses", "skirt",
    "jeans", "denim", "trousers", "pants", "blazer", "jacket", "coat",
    "hoodie", "sweater", "knit", "cardigan", "shirt", "tee", "t-shirt",
    "top", "blouse", "sneakers", "sneaker", "shoes", "boots", "heels",
    "loafers", "bag", "handbag", "purse", "accessories", "jewelry",
    "streetwear", "menswear", "womenswear", "aesthetic outfit",
    "cottagecore", "old money", "quiet luxury", "y2k", "vintage fashion",
    # statement / revealing pieces -- thirst-trap videos still signal what
    # people consider attractive clothing, so we count these too.
    "bikini", "swimsuit", "crop top", "bodysuit", "corset", "bralette",
    "mini skirt", "mini dress", "co-ord", "two piece", "lingerie",
]

# Words that hint at fashion but are weaker on their own.
MEDIUM_TERMS = [
    "style", "styled", "fashion", "trend", "trending", "aesthetic", "look",
    "wear", "wearing", "closet", "fit", "drip", "brand", "designer",
    "luxury", "minimalist", "color palette", "season", "fall", "spring",
    "summer", "winter", "autumn", "capsule", "layering", "layer",
]

# Off-topic content that slips through fashion hashtags but ISN'T about clothes
# (e.g. pregnancy/baby updates, food, fitness). If a caption hits one of these,
# we skip the video. Keep this conservative so real fashion isn't lost.
EXCLUDE_TERMS = [
    "pregnant", "pregnancy", "maternity", "baby bump", "babybump", "bumpdate",
    "gender reveal", "genderreveal", "trimester", "postpartum", "expecting",
    "newborn", "ultrasound", "momlife", "mom life", "pregnancy journey",
    "maternity shoot", "baby shower", "my pregnancy", "weeks pregnant",
    "mukbang", "what i eat", "recipe", "cooking", "weight loss", "workout routine",
]


def is_excluded(text):
    """True if the caption is clearly off-topic (pregnancy, food, etc.)."""
    t = (text or "").lower()
    return any(term in t for term in EXCLUDE_TERMS)


# Hashtags that mean the WHOLE feed is clothing -- a big head start.
FASHION_HASHTAGS = {
    "ootd", "outfit", "outfits", "fashion", "fashiontiktok", "fashionreels",
    "style", "styleinspo", "outfitinspo", "grwm", "thrift", "thriftflip",
    "streetwear", "menswear", "womensfashion", "mensfashion", "lookbook",
    "fitcheck", "tryonhaul", "fashionhaul", "whatiwore", "capsulewardrobe",
    "vintagefashion", "y2kfashion", "quietluxury", "oldmoney", "cottagecore",
}


def _count_hits(text, terms):
    """How many of these terms appear in the text (word-boundary-ish match)."""
    hits = []
    for t in terms:
        # escape spaces/dashes into a loose match
        pattern = r"\b" + re.escape(t).replace(r"\ ", r"\s*") + r"\b"
        if re.search(pattern, text):
            hits.append(t)
    return hits


def relevance(title, source_tag=None):
    """
    Return how clothing-centered a video looks.

    Returns: {"score": 0.0-1.0, "matched": [terms that fired]}
    """
    text = (title or "").lower()
    matched = []

    score = 0.0

    # Head start if it came from a fashion hashtag feed.
    if source_tag:
        tag = source_tag.lower().lstrip("#")
        if tag in FASHION_HASHTAGS:
            score += 0.5
            matched.append(f"#{tag}")

    strong = _count_hits(text, STRONG_TERMS)
    medium = _count_hits(text, MEDIUM_TERMS)
    matched += strong + medium

    # Each strong term adds a lot, each medium a little. Diminishing via cap.
    score += min(0.8, 0.35 * len(strong))
    score += min(0.3, 0.1 * len(medium))

    return {"score": round(min(score, 1.0), 3), "matched": matched}


def is_clothing(title, source_tag=None, threshold=0.35):
    """Quick yes/no using the default threshold."""
    return relevance(title, source_tag)["score"] >= threshold
