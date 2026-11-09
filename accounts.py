"""
accounts.py  --  Curated fashionable creators per style (the human-taste part).

These lists decide WHOSE posts we analyze for each style. The quality of your
trends depends entirely on this list, so CURATE IT: add the fashionable young
(16-26) creators you actually want to track, remove ones that don't fit.

Handles below are STARTER SEEDS from research -- VERIFY and replace them with
creators you trust. Just put the Instagram handle (without the @).
"""

STYLE_ACCOUNTS = {
    # --- seeded from research; please verify/expand each list ---
    "streetwear":  ["sangiev", "gullyguyleo", "wisdm8"],
    "y2k":         [],   # add y2k creators you follow
    "old money":   [],   # add old-money / quiet-luxury creators
    "minimalist":  [],   # add minimalist / clean creators
    "coquette":    [],   # add coquette creators
    "gorpcore":    [],   # add gorpcore / techwear creators
    "grunge":      [],   # add grunge creators
    "athleisure":  [],   # add athleisure / sporty creators
    "cottagecore": [],   # add cottagecore creators
    "preppy":      [],   # add preppy creators
}


def accounts_for(style):
    return STYLE_ACCOUNTS.get((style or "").strip().lower(), [])
