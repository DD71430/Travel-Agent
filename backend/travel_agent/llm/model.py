from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config.settings import get_settings


@dataclass(frozen=True)
class LLMResponse:
    content: str
    metadata: dict[str, Any] | None = None


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate(self, prompt: str, system_prompt: str = '') -> LLMResponse:
        _ = self.settings
        content = f'[{system_prompt}] {prompt}'.strip()
        return LLMResponse(content=content, metadata={'provider': 'mock-qwen'})
