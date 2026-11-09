"""
browser_util.py  --  Shared helpers for our own browser-based scrapers.

We use Playwright to drive a real (headless) Chromium browser. Because it's a
real browser, the sites' anti-bot signing mostly "just works" and we don't have
to fake secret request parameters by hand.
"""

import os

# A normal-looking desktop browser fingerprint so we blend in.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Set BROWSER_HEADLESS=0 in .env to WATCH the browser work (great for debugging
# captchas / logins). Default is headless (invisible).
HEADLESS = os.environ.get("BROWSER_HEADLESS", "1") == "1"


def new_context(playwright, storage_state=None):
    """Launch Chromium and return (browser, context) that look like a real user."""
    browser = playwright.chromium.launch(
        headless=HEADLESS,
        args=["--disable-blink-features=AutomationControlled"],  # hide "I'm a bot" flag
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        storage_state=storage_state if storage_state and os.path.exists(storage_state) else None,
    )
    # Extra stealth: remove the navigator.webdriver flag pages check for.
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return browser, context
