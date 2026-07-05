from __future__ import annotations

from typing import Any


class RecursiveSplitter:
    def split(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for doc in documents:
            content = doc.get('content', '')
            for idx in range(0, len(content), 500):
                chunks.append({'content': content[idx:idx + 500], 'source': doc.get('source')})
        return chunks


class SemanticSplitter:
    def split(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [chunk for chunk in chunks if chunk.get('content')]
