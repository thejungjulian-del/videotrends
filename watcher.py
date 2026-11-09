"""
watcher.py  --  The bot that actually WATCHES a video. 100% free, 100% local.

No paid API. It uses tools already on your Mac:
  - ffmpeg  -> chops the video into a few still frames and tiles them into ONE
               image (a "contact sheet"), so the vision model sees the whole
               video at a glance.
  - ollama  -> runs your local vision model (llama3.2-vision) to look at that
               image and describe the CLOTHING in it.

It returns a structured summary you can act on:
    {
      "is_clothing": true,
      "summary": "Try-on haul showing an oversized beige blazer...",
      "garments": ["blazer", "jeans", "sneakers"],
      "colors": ["beige", "dark blue", "white"],
      "style": "old money / minimalist"
    }

Because this runs on your computer it's free, but it's slower than a cloud API,
so the scanner only runs it on the few videos that are already trending.
"""

import json
import os
import re
import subprocess
import tempfile

import ollama

VISION_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")

# Cloud vision (fast + scales to thousands). If GEMINI_API_KEY is set we use
# Gemini Flash (~1-2s/image, parallel-friendly); otherwise fall back to local
# Ollama (~30s/image). This is the switch that makes thousands-scale possible.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# We ask the model to describe each garment as SPECIFICALLY as possible by
# combining its attributes into one phrase (e.g. "high-waisted wide-leg dark-wash
# jeans"). We demand strict JSON so the rest of the program can use it.
PROMPT = """You are a fashion analyst looking at frames from one short fashion video tiled into a single image.

Identify each clothing item as SPECIFICALLY as possible. For every garment, combine its visible attributes into ONE descriptive phrase, drawing from:
- garment type: jeans, blazer, hoodie, midi dress, cargo pants, tennis skirt, baby tee, trench coat...
- cut / silhouette: bootcut, wide-leg, flared, skinny, straight-leg, oversized, cropped, fitted, baggy, bodycon, A-line, pleated
- rise / length: high-waisted, low-rise, mini, midi, maxi, ankle-length
- fabric / material: denim, leather, linen, knit, satin, mesh, corduroy, fleece, lace
- denim wash / finish: dark-wash, light-wash, acid-wash, raw, distressed
- pattern: striped, plaid, floral, graphic, ribbed, houndstooth, animal-print
- neckline / sleeve when notable: halter, square-neck, puff-sleeve, strapless, off-shoulder
Do NOT put plain colors (black, white, blue, etc.) in the phrase.

Answer with ONE JSON object, nothing else:
{
  "is_clothing": true or false,
  "has_person": true or false,    // is a real PERSON wearing/posing in the outfit? false if it's a flatlay / product-only shot of clothing with no person
  "quality": 0.0 to 1.0,          // how polished & stylish: HIGH = real fashionable person, good lighting, intentional on-trend styling; LOW = tacky, cluttered, low-effort, spammy ad, watermark/text-heavy, or AI-generated/fake-looking
  "confidence": 0.0 to 1.0,
  "summary": "one sentence describing the outfit",
  "garments": ["e.g. 'high-waisted wide-leg dark-wash jeans', 'cropped puffer jacket', 'ribbed bodycon midi dress', 'oversized graphic tee', 'pleated tennis skirt', 'baggy cargo pants'"],
  "style": "aesthetic label, e.g. streetwear, old money, y2k, coquette, minimalist, grunge",
  "brands": ["brand names/logos you can READ on the clothing or in on-screen text; empty if none"]
}
Be as specific as the image actually allows; if a detail isn't visible, leave it out rather than guess. Only list a brand you can literally READ. If any outfit/clothing is shown at all (even a thirst-trap), set is_clothing true."""


def make_contact_sheet(video_path, out_path, frames=4, cols=2):
    """
    Use ffmpeg to grab evenly-spaced frames and tile them into one image.
    `frames` total frames, arranged in `cols` columns.
    """
    rows = max(1, (frames + cols - 1) // cols)
    # 'thumbnail' picks representative frames; 'tile' arranges them in a grid.
    vf = f"thumbnail,scale=400:-1,tile={cols}x{rows}"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf, "-frames:v", "1",
        out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path


def _extract_json(text):
    """Pull the first {...} JSON object out of the model's reply (it may add chatter)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# Phrases the model writes when there's NO brand -- we must NOT treat these as brands.
_NO_BRAND = ("none", "no brand", "not visible", "n/a", "unknown", "cannot", "can't",
             "no logo", "not sure", "nothing", "no visible", "not applicable", "n a")


def _clean_brands(brands):
    """Drop 'no brand visible' style noise; keep only short, real-looking names."""
    out = []
    for b in brands or []:
        s = str(b).strip().strip('."()[]')
        low = s.lower()
        if not s or any(n in low for n in _NO_BRAND):
            continue
        if len(s) > 25 or len(s.split()) > 4:  # a real brand name is short
            continue
        out.append(s)
    return out


def _parse_list(raw):
    """Turn '["a", "b"]' OR 'a, b' into a clean Python list."""
    if not raw:
        return []
    items = re.findall(r'"([^"]+)"', raw)          # quoted items first
    if not items:
        items = [p.strip(" []'\"") for p in raw.split(",")]
    return [i for i in items if i and i.lower() not in ("none", "n/a")]


def _parse_loose(text):
    """
    Fallback for when the local model answers in markdown/bullets instead of
    JSON (llama3.2-vision often does). Pulls each field out with regex.
    """
    def grab(field):
        # matches  is_clothing: x   |   **is_clothing**: x   |   "is_clothing": x
        m = re.search(rf'["*]*\b{field}\b["*]*\s*[:=]\s*(.+)', text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    is_c = grab("is_clothing").lower()
    hp = grab("has_person").lower()
    conf = re.search(r'[01]?\.\d+|\b[01]\b', grab("confidence"))
    q = re.search(r'[01]?\.\d+|\b[01]\b', grab("quality"))
    return {
        "is_clothing": is_c.startswith("true") or is_c.startswith("yes"),
        # default True -- only drop when the model EXPLICITLY says no person
        "has_person": not (hp.startswith("false") or hp.startswith("no")),
        "quality": float(q.group(0)) if q else 0.7,  # default passes; only explicit-low drops
        "confidence": float(conf.group(0)) if conf else 0.0,
        "summary": grab("summary").strip(' *"'),
        "garments": _parse_list(grab("garments")),
        "colors": _parse_list(grab("colors")),
        "style": grab("style").strip(' *"'),
        "brands": _parse_list(grab("brands")),
    }


def _gemini_text(image_path):
    """Fast cloud vision via Gemini Flash. Returns the raw model reply."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    data = open(image_path, "rb").read()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=data, mime_type="image/jpeg"), PROMPT],
    )
    return resp.text or ""


def _ollama_text(image_path):
    """Local vision via Ollama. Returns the raw model reply."""
    resp = ollama.chat(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": PROMPT, "images": [image_path]}],
        options={"temperature": 0.1},
    )
    return resp["message"]["content"]


def analyze_image(image_path):
    """Describe the clothing in one image (Gemini if configured, else local)."""
    text = _gemini_text(image_path) if GEMINI_API_KEY else _ollama_text(image_path)
    parsed = _extract_json(text)        # try clean JSON first
    if parsed is None:
        parsed = _parse_loose(text)     # fall back to markdown/bullet parsing
    # Make sure all keys exist so callers don't crash.
    parsed.setdefault("is_clothing", False)
    parsed.setdefault("has_person", True)  # only False when model explicitly says so
    parsed.setdefault("quality", 0.7)      # default passes; only explicit-low drops
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("summary", "")
    parsed.setdefault("garments", [])
    parsed.setdefault("colors", [])
    parsed.setdefault("style", "")
    parsed["brands"] = _clean_brands(parsed.get("brands"))

    # Robustness: local models phrase the is_clothing/confidence fields
    # inconsistently. If it actually listed garments, it IS about clothing.
    if parsed["garments"] and not parsed["is_clothing"]:
        parsed["is_clothing"] = True
    if parsed["is_clothing"] and not parsed["confidence"]:
        # confidence scales a bit with how many garments it spotted
        parsed["confidence"] = round(min(0.9, 0.5 + 0.1 * len(parsed["garments"])), 2)
    return parsed


def watch_video(video_path):
    """Full pipeline: video file -> contact sheet -> clothing summary."""
    with tempfile.TemporaryDirectory() as tmp:
        sheet = os.path.join(tmp, "sheet.jpg")
        make_contact_sheet(video_path, sheet)
        return analyze_image(sheet)


if __name__ == "__main__":
    # Quick manual test: pass a video file OR an image.
    import sys
    if len(sys.argv) < 2:
        print("Usage: python watcher.py <video-or-image-file>")
        raise SystemExit(1)
    path = sys.argv[1]
    ext = os.path.splitext(path)[1].lower()
    print(f"Watching {path} with {VISION_MODEL} (this can take 10-40s locally)...\n")
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        result = analyze_image(path)
    else:
        result = watch_video(path)
    print(json.dumps(result, indent=2))
