"""
ig_graph_setup.py  --  Helper to find your IG_USER_ID for the Graph API.

After you have an access token (from the Graph API Explorer), run:

    ./venv/bin/python ig_graph_setup.py YOUR_ACCESS_TOKEN

It lists the Facebook Pages on your account and, for each, the linked Instagram
Business account id. Copy that id into .env as IG_USER_ID (and the token as
IG_GRAPH_TOKEN). It also exchanges your short-lived token for a long-lived one
if you pass your app id + secret as extra arguments:

    ./venv/bin/python ig_graph_setup.py SHORT_TOKEN APP_ID APP_SECRET
"""

import json
import sys
import urllib.parse
import urllib.request

VERSION = "v21.0"
GRAPH = f"https://graph.facebook.com/{VERSION}"


def get(path, params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    token = sys.argv[1]

    # Optional: exchange for a long-lived (~60 day) token.
    if len(sys.argv) >= 4:
        app_id, app_secret = sys.argv[2], sys.argv[3]
        try:
            res = get("oauth/access_token", {
                "grant_type": "fb_exchange_token", "client_id": app_id,
                "client_secret": app_secret, "fb_exchange_token": token,
            })
            token = res.get("access_token", token)
            print("\n=== LONG-LIVED TOKEN (put in .env as IG_GRAPH_TOKEN) ===")
            print(token)
        except Exception as e:
            print(f"token exchange failed: {e}")

    print("\n=== Your Pages and linked Instagram Business accounts ===")
    try:
        pages = get("me/accounts", {
            "fields": "name,instagram_business_account{id,username}",
            "access_token": token,
        })
    except Exception as e:
        print(f"failed to list pages: {e}")
        return

    found = False
    for p in pages.get("data", []):
        iba = p.get("instagram_business_account")
        if iba:
            found = True
            print(f"  Page: {p.get('name')}")
            print(f"    IG_USER_ID = {iba.get('id')}  (@{iba.get('username')})")
    if not found:
        print("  No linked Instagram Business account found. Make sure your IG")
        print("  account is a Business/Creator account linked to a Facebook Page.")


if __name__ == "__main__":
    main()
