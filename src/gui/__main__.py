"""Run the Driftgram desktop app: python -m src.gui"""
from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
