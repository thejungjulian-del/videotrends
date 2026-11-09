"""
brands.py  --  Pull SPECIFIC brands and items out of a video.

Goal: turn "hoodie" into "Scuffers Hoodie".

Where the brand comes from:
  - the caption text, hashtags, and @mentions (most reliable -- creators name
    the brand themselves)
  - visible logos / on-screen text the vision model reads (added separately)

A small local vision model can't reliably guess a brand just by looking, so if
nobody names it and no logo is visible, the item stays generic. That's expected.
"""

import re

from tags import GARMENTS  # reuse the garment vocabulary

# A Gen-Z / streetwear-heavy brand list. Add your own niche brands here.
# Multi-word names are matched before single words.
BRANDS = [
    "scuffers", "jaded london", "broken planet", "corteiz", "trapstar",
    "represent", "fear of god", "essentials", "stussy", "stüssy", "supreme",
    "palace", "kith", "aime leon dore", "aimé leon dore", "carhartt",
    "the north face", "north face", "patagonia", "arc'teryx", "arcteryx",
    "salomon", "nike", "adidas", "jordan", "yeezy", "new balance", "converse",
    "vans", "dr martens", "doc martens", "ugg", "crocs", "samba", "sambas",
    "gymshark", "alphalete", "lululemon", "champion", "dickies", "levis",
    "levi's", "tommy hilfiger", "calvin klein", "ralph lauren", "polo ralph lauren",
    "brandy melville", "aritzia", "urban outfitters", "abercrombie", "hollister",
    "shein", "zara", "uniqlo", "pull and bear", "bershka", "stradivarius",
    "edikted", "oh polly", "white fox", "princess polly", "motel rocks",
    "djerf avenue", "reformation", "free people", "skims", "fashion nova",
    "prettylittlething", "boohoo", "asos", "cider", "collusion", "jacquemus",
    "prada", "gucci", "miu miu", "bottega veneta", "balenciaga", "louis vuitton",
    "dior", "chanel", "loewe", "celine", "burberry", "moncler", "stone island",
]

# Match longer (multi-word) brand names first so "north face" wins over "face".
_BRANDS_SORTED = sorted(set(BRANDS), key=len, reverse=True)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def find_brands(text):
    """Return the brands mentioned in the caption/hashtags/mentions, in order."""
    t = _norm(text)
    # Treat hashtags and @mentions as plain words too (#scuffers -> scuffers).
    t = t.replace("#", " ").replace("@", " ")
    found = []
    for b in _BRANDS_SORTED:
        # match the spaced name ("north face") OR the squished @handle/#tag form
        # ("northface", "brandymelville")
        spaced = r"\b" + re.escape(b).replace(r"\ ", r"\s+") + r"\b"
        squished = r"\b" + re.escape(b.replace(" ", "")) + r"\b"
        if (re.search(spaced, t) or re.search(squished, t)) and b not in found:
            found.append(b)
    return found


def _base_noun(garment):
    """'brown oversized hoodie' -> 'hoodie' (last known garment word)."""
    words = garment.lower().split()
    for w in reversed(words):
        if w in GARMENTS:
            return w
    return words[-1] if words else garment


def specific_items(text, vision_garments=None):
    """
    Build specific 'Brand Garment' strings, e.g. 'Scuffers Hoodie'.

    For each brand mentioned, we look for a garment word right after it in the
    caption (best case: 'scuffers hoodie'); otherwise we pair it with the most
    prominent garment the vision model saw.
    """
    t = _norm(text)
    brands = find_brands(text)
    vision_garments = vision_garments or []
    items = []

    for b in brands:
        garment = None
        # Look in a window of text right after the brand name (spaced or squished).
        m = (re.search(re.escape(b).replace(r"\ ", r"\s+"), t)
             or re.search(re.escape(b.replace(" ", "")), t))
        if m:
            window = t[m.end(): m.end() + 40]
            for g in sorted(GARMENTS, key=len, reverse=True):
                if re.search(r"\b" + re.escape(g) + r"\b", window):
                    garment = g
                    break
        if not garment and vision_garments:
            garment = _base_noun(vision_garments[0])

        item = f"{b} {garment}" if garment else b
        items.append(_titlecase(item))

    return brands, items


def _titlecase(s):
    """Nice display: 'scuffers hoodie' -> 'Scuffers Hoodie' (keeps & etc.)."""
    return " ".join(w.upper() if w in ("ck",) else w.capitalize() for w in s.split())
