#!/usr/bin/env python3
"""Entry point so the tool runs straight from a checkout: ./wfb.py report"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weekly_feedback.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
