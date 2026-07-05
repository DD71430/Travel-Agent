from __future__ import annotations

from pathlib import Path
from typing import Any


class DocumentLoader:
    def load(self, path: str) -> list[dict[str, Any]]:
        file_path = Path(path)
        if not file_path.exists():
            return []
        return [{'content': file_path.read_text(encoding='utf-8'), 'source': str(file_path)}]
