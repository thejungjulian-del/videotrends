"""
instagram_playwright.py  --  OUR OWN Instagram scraper (no third-party lib).

⚠️  Instagram is the HARD one. It almost always requires being logged in, and it
    aggressively challenges automated logins. To use this:
      1. Make a THROWAWAY Instagram account (don't risk your real one).
      2. Put it in .env:  IG_USERNAME=...   IG_PASSWORD=...
    We log in once and save the session to ig_session.json so we don't have to
    log in every time.

How it works (once logged in):
  1. Open the hashtag page, e.g. https://www.instagram.com/explore/tags/ootd/
  2. Listen for the GraphQL/API responses that contain the posts (likes,
     comments, date, caption, video views).
  3. Keep only VIDEO posts (reels), since this is a video trend scanner.

If login fails or IG challenges us, this returns nothing and the rest of the
system keeps working. Run with BROWSER_HEADLESS=0 to watch / solve a challenge.
"""

import os
import time

HASHTAGS = [h.strip() for h in os.environ.get(
    "IG_HASHTAGS", "ootd,outfitinspo,fashionreels,styleinspo,thriftflip"
).split(",") if h.strip()]
IG_USERNAME = os.environ.get("IG_USERNAME", "")
IG_PASSWORD = os.environ.get("IG_PASSWORD", "")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "ig_session.json")

# IG endpoints that carry post data.
_DATA_MARKERS = ("/graphql/query", "/api/v1/tags/", "/api/v1/feed/")

# How many posts to try to pull per scan, and how hard to scroll each hashtag.
SCRAPE_LIMIT = int(os.environ.get("SCRAPE_LIMIT", "150"))
SCROLLS = int(os.environ.get("IG_SCROLLS", "8"))


def _login(context):
    """Log in with the throwaway account and save the session for next time.

    Returns True only if a real session (sessionid cookie) was established.
    """
    page = context.new_page()
    page.goto("https://www.instagram.com/accounts/login/", timeout=45000,
              wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Dismiss a cookie-consent banner if one blocks the form.
    for label in ("Allow all cookies", "Decline optional cookies",
                  "Only allow essential cookies"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click(timeout=2500)
                page.wait_for_timeout(1200)
                break
        except Exception:
            pass

    def first_present(selectors):
        for s in selectors:
            try:
                if page.query_selector(s):
                    return s
            except Exception:
                pass
        return None

    # Instagram's field names changed (now email/pass); try several.
    user_sel = first_present(["input[name='username']", "input[name='email']",
                              "input[autocomplete='username']"])
    pass_sel = first_present(["input[name='password']", "input[name='pass']",
                              "input[type='password']"])
    if not user_sel or not pass_sel:
        page.screenshot(path="ig_login_fail.png")
        print("  [instagram] could not find login fields (saved ig_login_fail.png)")
        page.close()
        return False

    page.fill(user_sel, IG_USERNAME)
    page.fill(pass_sel, IG_PASSWORD)
    clicked = False
    for s in ("button[type='submit']", "input[type='submit']"):
        try:
            el = page.query_selector(s)
            if el:
                el.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        page.press(pass_sel, "Enter")
    page.wait_for_timeout(8000)

    # Dismiss "Save login info?" / "Turn on notifications" popups.
    for label in ("Not now", "Not Now", "Save info", "Cancel", "Dismiss"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(800)
        except Exception:
            pass

    ok = any(c["name"] == "sessionid" for c in context.cookies())
    page.screenshot(path="ig_login_result.png")
    if ok:
        try:
            context.storage_state(path=SESSION_FILE)
        except Exception:
            pass
        print("  [instagram] login OK -- session saved")
    else:
        print(f"  [instagram] login NOT confirmed (now at {page.url}); "
              f"likely a verification challenge -- see ig_login_result.png")
    page.close()
    return ok


def _is_video(node):
    """True if this is a reel / video post (we want PHOTO posts only)."""
    if node.get("is_video") is True:
        return True
    if node.get("media_type") in (2, "VIDEO"):
        return True
    if node.get("product_type") in ("clips", "igtv"):
        return True
    if node.get("video_versions") or node.get("video_url"):
        return True
    return False


def _parse_node(node, source_tag=None):
    """
    Turn an IG media node into our standard shape. PHOTO posts ONLY -- reels and
    video posts are skipped. Handles both IG response formats: old web GraphQL
    (display_url/edge_*) and newer api/v1 (image_versions2/caption.text/user).
    """
    code = node.get("shortcode") or node.get("code")
    if not code:
        return None
    if _is_video(node):
        return None  # skip reels / videos -- we only want photo posts

    # caption (two formats)
    caption = ""
    cap = node.get("caption")
    if isinstance(cap, dict):
        caption = cap.get("text", "")
    elif isinstance(cap, str):
        caption = cap
    else:
        edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
        if edges:
            caption = edges[0].get("node", {}).get("text", "")

    owner = node.get("owner") or node.get("user") or {}
    username = owner.get("username", "") if isinstance(owner, dict) else ""
    ts = (node.get("taken_at") or node.get("taken_at_timestamp")
          or node.get("device_timestamp") or time.time())

    # image url (two formats)
    img = node.get("display_url") or node.get("thumbnail_src")
    if not img:
        cands = (node.get("image_versions2") or {}).get("candidates") or []
        if cands:
            img = cands[0].get("url")

    def count(v):
        if isinstance(v, dict):
            v = v.get("count")
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    likes = node.get("like_count")
    likes = count(likes) if likes is not None else count(
        node.get("edge_liked_by") or node.get("edge_media_preview_like"))
    comments = node.get("comment_count")
    comments = count(comments) if comments is not None else count(
        node.get("edge_media_to_comment"))
    views = count(node.get("video_view_count") or node.get("view_count")
                  or node.get("play_count"))

    if not img or (likes == 0 and comments == 0):
        return None  # not a usable post

    return {
        "id": f"instagram:{code}",
        "platform": "instagram",
        "author": f"@{username}" if username else None,
        "title": (caption or "")[:200],
        "url": f"https://www.instagram.com/p/{code}/",
        "image_url": img,
        "source_tag": source_tag,
        "post_time": float(ts),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": 0,
    }


def _walk_for_nodes(obj, out):
    """Recursively find post 'node' dicts anywhere in IG's nested JSON."""
    if isinstance(obj, dict):
        if obj.get("shortcode") or obj.get("code"):
            out.append(obj)
        for v in obj.values():
            _walk_for_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_for_nodes(v, out)


def _scrape_tag(context, tag, want):
    captured = []
    page = context.new_page()

    def on_response(resp):
        if any(m in resp.url for m in _DATA_MARKERS):
            try:
                data = resp.json()
            except Exception:
                return
            _walk_for_nodes(data, captured)

    page.on("response", on_response)
    try:
        page.goto(f"https://www.instagram.com/explore/tags/{tag}/", timeout=45000,
                  wait_until="domcontentloaded")
        for _ in range(SCROLLS):
            if len(captured) >= want:
                break
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  [instagram] page issue for #{tag}: {e}")
    page.close()

    out = []
    seen = set()
    for node in captured:
        parsed = _parse_node(node, source_tag=tag)
        if parsed and parsed["id"] not in seen:
            seen.add(parsed["id"])
            out.append(parsed)
    return out[:want]


def fetch(limit=None):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("  [instagram] playwright not installed -- skipping.")
        return []
    from . import browser_util as bu

    if not (IG_USERNAME and IG_PASSWORD) and not os.path.exists(SESSION_FILE):
        print("  [instagram] no IG_USERNAME/IG_PASSWORD and no saved session -- skipping. "
              "(Use a throwaway account; see README.)")
        return []

    limit = limit or SCRAPE_LIMIT
    per_tag = max(20, limit // max(1, len(HASHTAGS)))
    results = []
    try:
        with sync_playwright() as pw:
            browser, context = bu.new_context(pw, storage_state=SESSION_FILE)
            # Log in if we don't have a saved session yet.
            if not os.path.exists(SESSION_FILE) and IG_USERNAME and IG_PASSWORD:
                print("  [instagram] logging in (first time)...")
                _login(context)
            for tag in HASHTAGS:
                if len(results) >= limit:
                    break
                got = _scrape_tag(context, tag, per_tag)
                print(f"  [instagram] #{tag}: {len(got)} videos")
                results.extend(got)
            context.close()
            browser.close()
    except Exception as e:
        print(f"  [instagram] scraper failed ({e}) -- skipping, system OK.")
        return []

    seen, unique = set(), []
    for v in results:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        unique.append(v)
    return unique[:limit]
