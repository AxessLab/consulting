#!/usr/bin/env bash
set -euo pipefail

# Cursor Cloud images may not provide a `python` command — only `python3`.
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  sudo apt-get update
  sudo apt-get install -y python3 python3-pip python3-venv
  PYTHON=python3
fi

# Provide `python` for prompts/scripts that call it explicitly.
if ! command -v python >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    sudo apt-get install -y python-is-python3 2>/dev/null || true
  fi
fi

$PYTHON -m pip install -r requirements.txt
$PYTHON -m playwright install chromium
sudo apt-get update
sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
