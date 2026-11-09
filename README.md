# VideoTrends

A fashion trend recognizer. It pulls popular outfit posts from Instagram fashion hashtags, has a vision model running on my laptop name the exact garments in each one, weights every item by likes and tracks which pieces are gaining from scan to scan. A look needs 100k likes before it counts as vetted. It also scores its own past forecasts, so you can check whether it was right. The vision model is a 7B Qwen2.5-VL model run through Ollama, so there's no vision API bill.

## Run it

```
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scanner.py --sources mock   # fake demo posts, no login needed
python dashboard.py                # http://localhost:8775
```

Run the mock scan a few times so the dashboard has history to compare. For real scans you also need `pip install playwright ollama`, `playwright install chromium`, and Ollama with `ollama pull qwen2.5vl:7b`. Instagram needs a login in `.env`; use a throwaway account, not your real one. `run_scan.sh` and `run_dashboard.sh` are the wrappers I ran from launchd on macOS.

## Status

Built, with scans paused. The scrapers drive a real browser and break when TikTok or Instagram change their pages, and scraping may go against those platforms' terms, so use it on your own judgment. Scan data and the login session stay local and aren't in this repo.

Portfolio: https://thejungjulian-del.github.io/portfolio/
