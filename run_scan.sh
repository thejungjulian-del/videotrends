#!/bin/bash
# Wrapper that the LaunchAgent runs every 30 minutes.
# It sets the PATH (launchd starts with a bare PATH that lacks Homebrew),
# moves into the project, and runs one scan, logging everything to scan.log.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")" || exit 1

echo "" >> scan.log
echo "===== scan started: $(date '+%Y-%m-%d %H:%M:%S') =====" >> scan.log
./venv/bin/python scanner.py --sources instagram >> scan.log 2>&1
