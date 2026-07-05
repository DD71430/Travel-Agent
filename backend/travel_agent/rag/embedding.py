from __future__ import annotations

from typing import Any


class EmbeddingService:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 10)] * 8 for text in texts]
