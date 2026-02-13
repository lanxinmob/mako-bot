from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # NoneBot
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("HOST", "NB_HOST"))
    port: int = Field(default=8080, validation_alias=AliasChoices("PORT", "NB_PORT"))
    onebot_access_token: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("ONEBOT_ACCESS_TOKEN")
    )

    # Logging
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "NB_LOG_LEVEL"))
    log_file: str = Field(default="logs/mako-bot.log", validation_alias=AliasChoices("LOG_FILE", "NB_LOG_FILE"))
    log_rotation: str = Field(default="10 MB", validation_alias=AliasChoices("LOG_ROTATION", "NB_LOG_ROTATION"))
    log_retention: str = Field(default="7 days", validation_alias=AliasChoices("LOG_RETENTION", "NB_LOG_RETENTION"))

    # Redis
    redis_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("REDIS_URL"))
    redis_host: str = Field(default="localhost", validation_alias=AliasChoices("REDIS_HOST"))
    redis_port: int = Field(default=6379, validation_alias=AliasChoices("REDIS_PORT"))
    redis_db: int = Field(default=0, validation_alias=AliasChoices("REDIS_DB"))

    # LLM / AI
    deepseek_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", validation_alias=AliasChoices("DEEPSEEK_BASE_URL"))
    openai_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    openai_base_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_BASE_URL"))

    # RAG / Embedding
    embedding_model: str = Field(default="moka-ai/m3e-base", validation_alias=AliasChoices("EMBEDDING_MODEL"))
    vector_index_name: str = Field(default="Long_term_memory", validation_alias=AliasChoices("VECTOR_INDEX_NAME"))
    vector_prefix: str = Field(default="memory:", validation_alias=AliasChoices("VECTOR_PREFIX"))

    # QWeather
    qweather_host: Optional[str] = Field(default=None, validation_alias=AliasChoices("your_api_host", "QWEATHER_HOST"))
    qweather_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("your_api", "QWEATHER_KEY"))
    qweather_icon_dir: Optional[str] = Field(default=None, validation_alias=AliasChoices("QWEATHER_ICON_DIR"))

    # Tianxin
    tianxin_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("tianxin_key", "TIANXIN_KEY"))

    # Google Custom Search
    google_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("GOOGLE_API_KEY"))
    google_cx: Optional[str] = Field(default=None, validation_alias=AliasChoices("GOOGLE_CX", "GOOGLE_CSE_ID"))
    google_result_count: int = Field(default=5, validation_alias=AliasChoices("GOOGLE_RESULT_COUNT"))

    # Amap
    amap_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("AMAP_KEY"))

    # Image
    image_provider: Literal["openai", "stability", "none"] = Field(
        default="none", validation_alias=AliasChoices("IMAGE_PROVIDER")
    )
    image_size: str = Field(default="1024x1024", validation_alias=AliasChoices("IMAGE_SIZE"))
    vision_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("VISION_MODEL"))
    image_model: str = Field(default="gpt-image-1", validation_alias=AliasChoices("IMAGE_MODEL"))
    stability_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("STABILITY_API_KEY"))

    # Language
    deepl_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("DEEPL_KEY", "DEEPL_API_KEY"))
    baidu_translate_appid: Optional[str] = Field(default=None, validation_alias=AliasChoices("BAIDU_TRANSLATE_APPID"))
    baidu_translate_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("BAIDU_TRANSLATE_KEY"))
    tts_voice: str = Field(default="alloy", validation_alias=AliasChoices("TTS_VOICE"))
    tts_model: str = Field(default="gpt-4o-mini-tts", validation_alias=AliasChoices("TTS_MODEL"))
    stt_model: str = Field(default="whisper-1", validation_alias=AliasChoices("STT_MODEL"))

    # Affinity
    affinity_min: int = Field(default=0, validation_alias=AliasChoices("AFFINITY_MIN"))
    affinity_max: int = Field(default=100, validation_alias=AliasChoices("AFFINITY_MAX"))
    affinity_initial: int = Field(default=50, validation_alias=AliasChoices("AFFINITY_INITIAL"))
    affinity_daily_cap: int = Field(default=20, validation_alias=AliasChoices("AFFINITY_DAILY_CAP"))

    # Scheduler
    default_group_id: Optional[int] = Field(default=None, validation_alias=AliasChoices("GROUP_ID", "DEFAULT_GROUP_ID"))

    # Chat
    max_history_turns: int = Field(default=50, validation_alias=AliasChoices("MAX_HISTORY_TURNS"))
    reply_random_chance: float = Field(default=0.001, validation_alias=AliasChoices("REPLY_RANDOM_CHANCE"))

    def build_redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.redis_url:
        settings.redis_url = settings.build_redis_url()
    return settings
