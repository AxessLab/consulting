#!/usr/bin/env python3
"""Backward-compatible wrapper — use scripts/list-assignments.py instead."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from list_assignments import main

if __name__ == "__main__":
    if "--platform" not in sys.argv and "-h" not in sys.argv and "--help" not in sys.argv:
        sys.argv.extend(["--platform", "allakonsultuppdrag.se"])
    raise SystemExit(main())
