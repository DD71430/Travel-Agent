from __future__ import annotations

from typing import Any


class HybridRetriever:
    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        bm25 = [{'content': f'BM25 result for {query}', 'score': 0.91}]
        vector = [{'content': f'Vector result for {query}', 'score': 0.88}]
        merged = bm25 + vector
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in merged:
            content = item['content']
            if content not in seen:
                seen.add(content)
                deduped.append(item)
        return deduped[:top_k]
