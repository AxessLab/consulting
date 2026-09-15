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
    sudo ln -sf "$(command -v python3)" /usr/local/bin/python 2>/dev/null || {
      mkdir -p "$HOME/.local/bin"
      ln -sf "$(command -v python3)" "$HOME/.local/bin/python"
      export PATH="$HOME/.local/bin:$PATH"
    }
  fi
fi

$PYTHON -m pip install -r requirements.txt
$PYTHON -m playwright install chromium

# Avoid Ubuntu's snap-backed chromium/chromium-browser packages in Cloud builds:
# they can pull snapd/fuse and stop at interactive dpkg conffile prompts.
# Cursor Cloud provides Google Chrome, and render-cv.py can also use the
# Playwright-managed Chromium installed above.
