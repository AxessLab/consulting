#!/usr/bin/env bash
set -euo pipefail
pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser