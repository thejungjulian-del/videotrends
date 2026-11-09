"""
tags.py  --  Turn a video into outfit TAGS, then find the consistent themes.

Two jobs:
  1. tags_from_text(text)  -> pull garments/colors/style out of a caption.
     (Used for videos we haven't "watched" with the vision model yet. When the
      watcher HAS looked at a video, we use its richer tags instead.)
  2. aggregate_themes(rows) -> given the tags of many trending videos, count
     which garments/colors/styles keep showing up. The ones that recur across
     lots of trending videos = the TRENDING OUTFITS.
"""

import json
import re
from collections import defaultdict

# --- vocabularies -------------------------------------------------------------

GARMENTS = [
    "blazer", "jacket", "coat", "trench", "hoodie", "sweater", "knit",
    "cardigan", "shirt", "tee", "t-shirt", "blouse", "top", "tank",
    "dress", "gown", "skirt", "jeans", "denim", "trousers", "pants", "cargos",
    "cargo pants", "leggings", "shorts", "suit", "vest", "sneakers",
    "trainers", "boots", "heels", "loafers", "flats", "sandals",
    "bag", "handbag", "purse", "tote", "scarf", "hat", "cap", "belt",
    # outerwear / casual pieces commonly named in captions
    "puffer", "puffer jacket", "bomber", "parka", "gilet", "windbreaker",
    "tracksuit", "joggers", "sweatpants", "cargo", "flannel", "polo", "henley",
    "baby tee", "tube top", "halter top", "maxi skirt", "maxi dress",
    "midi skirt", "midi dress", "slip dress",
    # statement / revealing pieces (thirst-trap signal = what's seen as hot)
    "bikini", "swimsuit", "crop top", "bodysuit", "corset", "bralette",
    "mini skirt", "mini dress", "co-ord", "two piece", "lingerie",
]

COLORS = [
    "black", "white", "cream", "beige", "tan", "brown", "camel", "khaki",
    "grey", "gray", "navy", "blue", "denim blue", "red", "burgundy",
    "pink", "green", "olive", "sage", "yellow", "orange", "purple",
    "pastel", "neutral", "monochrome",
]

STYLES = [
    "old money", "quiet luxury", "streetwear", "y2k", "minimalist",
    "cottagecore", "grunge", "preppy", "athleisure", "vintage", "casual",
    "formal", "feminine", "edgy", "bohemian", "boho", "clean girl",
    "gorpcore", "coquette", "business casual",
]


def _find(text, vocab):
    """Return the vocab terms that appear in text (longest-match-ish, unique)."""
    found = []
    for term in sorted(vocab, key=len, reverse=True):  # longer phrases first
        pattern = r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, text):
            found.append(term)
    return found


# Color words to strip from garment phrases (so "blue bootcut jeans" -> "bootcut
# jeans"). We KEEP cut/silhouette words like bootcut, oversized, cargo, puffer.
_COLOR_WORDS = set()
for _c in COLORS:
    for _w in _c.split():
        _COLOR_WORDS.add(_w)
_COLOR_WORDS.discard("denim")  # denim is a fabric/garment, not just a color

_GARMENT_STOP = {"and", "with", "a", "an", "the", "my", "this", "that", "new",
                 "cute", "nice", "really", "super", "so", "very", "little",
                 "plus", "some", "of", "in", "pair"}


def specific_garment(phrase):
    """'blue bootcut jeans' -> 'bootcut jeans' (strips color + filler)."""
    words = re.findall(r"[a-z\-]+", (phrase or "").lower())
    kept = [w for w in words if w not in _COLOR_WORDS and w not in _GARMENT_STOP]
    out = " ".join(kept).strip()
    return out or (phrase or "").lower().strip()


# One key descriptor (cut/silhouette/pattern/fabric), priority order. Used to
# bucket verbose vision phrases into SPECIFIC-but-RECURRING pieces so counts add
# up (otherwise every post is a unique phrase and every count is 1).
CUT_DESCRIPTORS = [
    "wide-leg", "wide leg", "straight-leg", "straight leg", "bootcut", "baggy",
    "flared", "skinny", "cargo", "oversized", "cropped", "puffer", "varsity",
    "bomber", "trench", "pleated", "mini", "midi", "maxi", "graphic", "striped",
    "plaid", "leather", "denim", "knit", "ribbed", "halter", "off-shoulder",
    "tube", "corset", "high-waisted", "low-rise",
]


def canonical_piece(phrase):
    """
    Reduce a verbose vision phrase to a specific-but-shared piece, e.g.
    'high-waisted straight-leg dark-wash jeans' -> 'straight-leg jeans'.
    Keeps ONE defining descriptor + the garment noun so similar posts stack.
    """
    p = (phrase or "").lower()
    noun = None
    for g in sorted(GARMENTS, key=len, reverse=True):   # longest garment match
        if re.search(r"\b" + re.escape(g) + r"\b", p):
            noun = g
            break
    if not noun:
        words = re.findall(r"[a-z\-]+", p)
        noun = words[-1] if words else p
    for d in CUT_DESCRIPTORS:
        if re.search(r"\b" + re.escape(d).replace(r"\ ", r"\s+") + r"\b", p):
            desc = d.replace(" ", "-")
            return f"{desc} {noun}" if desc not in noun else noun
    return noun


def _dedupe_garments(items):
    """Collapse near-duplicates (e.g. 'denim' under 'jeans', 't-shirt' under 'tee')."""
    alias = {"denim": "jeans", "t-shirt": "tee", "trainers": "sneakers",
             "cargos": "cargo pants", "handbag": "bag", "purse": "bag", "tote": "bag"}
    out = []
    for it in items:
        it = alias.get(it, it)
        if it not in out:
            out.append(it)
    return out


def tags_from_text(text):
    """Extract outfit tags from a caption/title."""
    t = (text or "").lower()
    return {
        "garments": _dedupe_garments(_find(t, GARMENTS)),
        "colors": _find(t, COLORS),
        "style": (_find(t, STYLES) or [""])[0],  # one main style label
    }


# --- aggregation: the "consistent theme = trend" part -------------------------

def _loads(maybe_json):
    if not maybe_json:
        return []
    if isinstance(maybe_json, list):
        return maybe_json
    try:
        return json.loads(maybe_json)
    except Exception:
        return []


def aggregate_themes(rows, top=12, now=None, recent_hours=24):
    """
    Recognize TRENDS, not just count tags.

    For each tag we track, across all trending videos:
      - videos : how many videos it appears in        (consistency)
      - score  : total trend_score                    (how hot)
      - recent : videos first seen in the last `recent_hours`
      - prior  : videos first seen in the window before that
      - example: the hottest video showing it (to link to)

    momentum compares recent vs prior so the bot can SAY whether a thing is
    rising, steady, or fading -- that's the actual trend recognition.
    """
    recent_cut = (now - recent_hours * 3600) if now else None
    prior_cut = (now - 2 * recent_hours * 3600) if now else None
    VETTED_LIKES = 100000  # videos past this are treated as strongly "vetted"

    def fresh_counter():
        return defaultdict(lambda: {"videos": 0, "score": 0.0, "recent": 0,
                                    "prior": 0, "weight": 0.0, "vetted": 0,
                                    "example": None, "_best_likes": -1})

    g, c, s, br, it = (fresh_counter(), fresh_counter(), fresh_counter(),
                       fresh_counter(), fresh_counter())

    def add(counter, key, ts, row):
        if not key:
            return
        likes = row.get("likes") or 0
        # Likes weigh heavily: a 100k-like video counts ~2x a low one and scales
        # up (capped), so highly-liked content dominates what we call a trend.
        like_weight = 1.0 + min(likes / VETTED_LIKES, 20.0)
        e = counter[key]
        e["videos"] += 1
        e["score"] += ts
        e["weight"] += like_weight
        if likes >= VETTED_LIKES:
            e["vetted"] += 1
        fs = row.get("first_seen")
        if recent_cut and fs:
            if fs >= recent_cut:
                e["recent"] += 1
            elif fs >= prior_cut:
                e["prior"] += 1
        if likes > e["_best_likes"]:  # link the MOST-LIKED video as the example
            e["_best_likes"] = likes
            e["example"] = {"url": row.get("url"), "author": row.get("author"),
                            "title": (row.get("title") or "")[:80], "likes": likes}

    for r in rows:
        ts = r.get("trend_score") or 0
        # "blue bootcut jeans" -> "bootcut jeans": keep the cut, drop the color.
        seen_g = []
        for garment in _loads(r.get("garments")):
            sg = canonical_piece(garment)   # bucket so similar pieces stack
            if sg and sg not in seen_g:
                seen_g.append(sg)
                add(g, sg, ts, r)
        for color in _loads(r.get("colors")):
            add(c, color, ts, r)
        style = (r.get("style") or "").strip().lower()
        add(s, style, ts, r)
        for brand in _loads(r.get("brands")):
            add(br, brand, ts, r)
        for item in _loads(r.get("items")):
            add(it, item, ts, r)

    def momentum(e):
        r, p = e["recent"], e["prior"]
        if not now:
            return "steady"
        if p == 0 and r > 0:
            return "new"
        if r > p:
            return "rising"
        if r < p:
            return "fading"
        return "steady"

    def rank(counter, kind):
        items = [
            {"tag": k, "kind": kind, "videos": v["videos"],
             "score": round(v["score"], 0), "weight": round(v["weight"], 2),
             "vetted": v["vetted"], "recent": v["recent"], "prior": v["prior"],
             "peak_likes": (v["example"] or {}).get("likes", 0),
             "momentum": momentum(v), "example": v["example"]}
            for k, v in counter.items()
        ]
        # Rank by like-weighted importance (then how many videos show it).
        items.sort(key=lambda x: (x["weight"], x["videos"]), reverse=True)
        return items[:top]

    garments = rank(g, "garment")
    colors = rank(c, "color")
    styles = rank(s, "style")
    brands = rank(br, "brand")
    specific = rank(it, "item")

    # "Rising now" = the trends actually gaining momentum, most specific first.
    # (Colors excluded -- not a trend category we surface anymore.)
    everything = specific + brands + garments + styles
    rising = [x for x in everything if x["momentum"] == "rising"]
    rising.sort(key=lambda x: (x["weight"], x["videos"]), reverse=True)
    emerging = [x for x in everything if x["momentum"] == "new"]
    emerging.sort(key=lambda x: (x["weight"], x["videos"]), reverse=True)

    # Headline = the strongest rising trend; else the biggest commonality.
    if rising:
        headline = rising[0]
    else:
        pool = [lst[0] for lst in (specific, brands, garments, styles) if lst]
        headline = max(pool, key=lambda x: (x["weight"], x["videos"])) if pool else None

    # TOP PIECES = the most common specific pieces, ranked by post count.
    # Merges brand+item ("Scuffers Hoodie") and detailed garments; brand items
    # win when present so "Scuffers Hoodie (300)" beats generic "hoodie".
    combined = {}
    for it in specific + garments:
        k = it["tag"]
        if k not in combined or it["videos"] > combined[k]["videos"]:
            combined[k] = it
    top_pieces = sorted(combined.values(),
                        key=lambda x: (x["videos"], x["score"]), reverse=True)[:10]

    return {
        "total_videos": len(rows),
        "headline": headline,
        "top_pieces": top_pieces,
        "rising": rising[:8],
        "emerging": emerging[:8],
        "specific": specific,
        "brands": brands,
        "garments": garments,
        "colors": colors,
        "styles": styles,
    }
