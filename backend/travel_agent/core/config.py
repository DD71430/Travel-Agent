from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
        populate_by_name=True,
    )

    qwen_api_key: str = Field(...)
    qwen_api_base: str = Field(...)
    qwen_multimodal_base: str = Field(...)
    qwen_model: str = Field(...)
    audio_understanding_model: str = Field(...)
    asr_model: str = Field(...)
    dashscope_workspace_id: str = Field(...)
    dashscope_region: str = Field(...)
    fun_asr_sample_rate: int = Field(...)
    fun_asr_language_hint: str = Field(...)
    tencent_maps_key: str = Field(...)
    tencent_maps_base_url: str = Field(...)
    redis_url: str = Field(...)
    redis_prefix: str = Field(...)
    memory_ttl_seconds: int = Field(...)
    cors_origins_raw: str = Field(default='http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000', alias='CORS_ORIGINS')
    debug: bool = Field(default=True, alias='DEBUG')

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw
        origins = [item.strip() for item in raw.split(',') if item.strip()]
        expanded: list[str] = []
        for origin in origins:
            if origin not in expanded:
                expanded.append(origin)
            if origin.startswith('http://localhost:'):
                alias = origin.replace('http://localhost:', 'http://127.0.0.1:')
                if alias not in expanded:
                    expanded.append(alias)
            elif origin.startswith('http://127.0.0.1:'):
                alias = origin.replace('http://127.0.0.1:', 'http://localhost:')
                if alias not in expanded:
                    expanded.append(alias)
        return expanded


@lru_cache
def get_settings() -> Settings:
    return Settings()
