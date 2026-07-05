from __future__ import annotations

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
backend_dir_str = str(backend_dir)
if backend_dir_str not in sys.path:
    sys.path.insert(0, backend_dir_str)

from travel_agent.main import app

__all__ = ['app']
