"""
styles.py  --  The curated fashion-style menu and the Instagram hashtags each
one scrapes.

Ten dominant 2026 aesthetics, chosen to cover every base (street, outdoor,
feminine, edgy, luxe, clean, sporty, preppy) without clutter. When the user
picks a style and hits Find, we scrape its hashtags live, tag every post with
that style, then show the specific garments trending in it.
"""

STYLE_HASHTAGS = {
    "streetwear":  ["streetwear", "streetstyle", "streetwearfashion"],
    "y2k":         ["y2k", "y2kfashion", "y2kstyle"],
    "old money":   ["oldmoney", "oldmoneyaesthetic", "quietluxury"],
    "minimalist":  ["minimalstyle", "minimalfashion", "cleanfit"],
    "coquette":    ["coquette", "coquettecore", "coquetteaesthetic"],
    "gorpcore":    ["gorpcore", "techwear", "outdoorstyle"],
    "grunge":      ["grunge", "grungefashion", "grungestyle"],
    "athleisure":  ["athleisure", "athleisurestyle", "sportychic"],
    "cottagecore": ["cottagecore", "cottagecorefashion"],
    "preppy":      ["preppy", "preppystyle", "preppyfashion"],
}


def all_styles():
    return list(STYLE_HASHTAGS.keys())


def hashtags_for(style):
    return STYLE_HASHTAGS.get((style or "").strip().lower(), [])
