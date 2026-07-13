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

    qwen_api_key: str = Field(default='')
    qwen_api_base: str = Field(default='https://dashscope.aliyuncs.com/compatible-mode/v1')
    qwen_multimodal_base: str = Field(default='https://dashscope.aliyuncs.com/compatible-mode/v1')
    qwen_model: str = Field(default='qwen-plus')
    audio_understanding_model: str = Field(default='qwen-audio-turbo')
    asr_model: str = Field(default='paraformer-realtime-v2')
    dashscope_workspace_id: str = Field(default='')
    dashscope_region: str = Field(default='cn-beijing')
    fun_asr_sample_rate: int = Field(default=16000)
    fun_asr_language_hint: str = Field(default='zh')
    tencent_maps_key: str = Field(default='')
    tencent_maps_base_url: str = Field(default='https://apis.map.qq.com')
    redis_url: str = Field(default='redis://localhost:6379/0')
    redis_prefix: str = Field(default='travel_agent')
    memory_ttl_seconds: int = Field(default=7 * 24 * 60 * 60)
    cors_origins_raw: str = Field(default='http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000', alias='CORS_ORIGINS')
    debug: bool = Field(default=False, alias='DEBUG')
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, alias='MAX_UPLOAD_BYTES')
    max_extract_chars: int = Field(default=4000, alias='MAX_EXTRACT_CHARS')
    return_debug_meta: bool = Field(default=False, alias='RETURN_DEBUG_META')
    ffmpeg_path: str = Field(default='', alias='FFMPEG_PATH')

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
