from __future__ import annotations

from typing import Any


class Reranker:
    def rerank(self, documents: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        return sorted(documents, key=lambda item: item.get('score', 0), reverse=True)[:top_k]
