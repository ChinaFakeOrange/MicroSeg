"""Pytest configuration: make the ``app`` package importable.

Allows running ``pytest`` from either the repository root or the ``backend``
directory.
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent  # .../backend
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
