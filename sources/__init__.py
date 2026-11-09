"""
Data sources package.

Each source knows how to fetch a list of videos from one place (TikTok,
Instagram, or fake "mock" data). They all return the SAME shape of data so the
scanner doesn't care where it came from:

    {
        "id":        "tiktok:1234567890",   # platform:native_id, must be unique
        "platform":  "tiktok",
        "author":    "@someuser",
        "title":     "short description / caption",
        "url":       "https://...",
        "post_time": 1700000000.0,           # unix timestamp it was POSTED
        "views":     123456,
        "likes":     7890,
        "comments":  321,
        "shares":    45,
    }

If a source fails (TikTok/Instagram scrapers are fragile), it should print a
warning and return an empty list -- NEVER crash the whole scan.
"""

from .mock_source import fetch as fetch_mock
# Apify cloud scrapers (paid, scale):
from .instagram_apify import fetch as fetch_instagram_apify          # by hashtag
from .instagram_accounts import fetch as fetch_instagram_accounts    # by curated creators
# Official Instagram Graph API (sanctioned, no bans):
from .instagram_graph import fetch as fetch_instagram_graph
# Our own browser-based scrapers:
from .tiktok_playwright import fetch as fetch_tiktok_web
from .instagram_playwright import fetch as fetch_instagram_web
# Old third-party-library scrapers, kept as fallbacks:
from .tiktok_source import fetch as fetch_tiktok_lib
from .instagram_source import fetch as fetch_instagram_lib

# The scanner reads this dict to know which sources exist.
SOURCES = {
    "mock": fetch_mock,
    "instagram_apify": fetch_instagram_apify,  # cloud scraper by hashtag (paid)
    "instagram_accounts": fetch_instagram_accounts,  # cloud scraper, curated creators (paid)
    "instagram_graph": fetch_instagram_graph,  # official Graph API (App Review)
    "tiktok": fetch_tiktok_web,          # our own Playwright scraper
    "instagram": fetch_instagram_web,    # our own Playwright scraper (login)
    "tiktok_lib": fetch_tiktok_lib,      # fallback: TikTokApi library
    "instagram_lib": fetch_instagram_lib,  # fallback: instaloader library
}
