#!/bin/bash
# Launcher for the dashboard web server (used by the LaunchAgent).
# Wrapping in bash + exec avoids launchd's trouble exec'ing the venv symlink.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python dashboard.py
