from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Literal, Optional

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
    gemini_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY"))
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        validation_alias=AliasChoices("GEMINI_BASE_URL"),
    )

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
    image_provider: Literal["openai", "gemini", "stability", "none"] = Field(
        default="none", validation_alias=AliasChoices("IMAGE_PROVIDER")
    )
    image_size: str = Field(default="1024x1024", validation_alias=AliasChoices("IMAGE_SIZE"))
    vision_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("VISION_MODEL"))
    image_model: str = Field(default="gpt-image-1", validation_alias=AliasChoices("IMAGE_MODEL"))
    gemini_vision_model: str = Field(
        default="gemini-1.5-flash", validation_alias=AliasChoices("GEMINI_VISION_MODEL")
    )
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
    tool_timeout_seconds: float = Field(
        default=25.0,
        validation_alias=AliasChoices("TOOL_TIMEOUT_SECONDS"),
    )
    tool_max_concurrency: int = Field(default=3, validation_alias=AliasChoices("TOOL_MAX_CONCURRENCY"))
    tool_enable_list: Optional[str] = Field(default=None, validation_alias=AliasChoices("TOOL_ENABLE_LIST"))
    tool_disable_list: Optional[str] = Field(default=None, validation_alias=AliasChoices("TOOL_DISABLE_LIST"))
    group_tool_enable_list: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("GROUP_TOOL_ENABLE_LIST")
    )
    group_tool_disable_list: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("GROUP_TOOL_DISABLE_LIST")
    )
    private_tool_enable_list: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("PRIVATE_TOOL_ENABLE_LIST")
    )
    private_tool_disable_list: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("PRIVATE_TOOL_DISABLE_LIST")
    )
    admin_only_tool_list: Optional[str] = Field(
        default="note.delete,note.update",
        validation_alias=AliasChoices("ADMIN_ONLY_TOOL_LIST"),
    )
    plugin_enable_list: Optional[str] = Field(default=None, validation_alias=AliasChoices("PLUGIN_ENABLE_LIST"))

    # Governance / Permission
    admin_user_ids: Optional[str] = Field(default=None, validation_alias=AliasChoices("ADMIN_USER_IDS"))
    blacklist_user_ids: Optional[str] = Field(default=None, validation_alias=AliasChoices("BLACKLIST_USER_IDS"))
    blacklist_group_ids: Optional[str] = Field(default=None, validation_alias=AliasChoices("BLACKLIST_GROUP_IDS"))
    group_reply_max_chars_undirected: int = Field(
        default=60, validation_alias=AliasChoices("GROUP_REPLY_MAX_CHARS_UNDIRECTED")
    )

    # Cost control
    cost_control_enabled: bool = Field(default=True, validation_alias=AliasChoices("COST_CONTROL_ENABLED"))
    daily_cost_limit_global: float = Field(default=3.0, validation_alias=AliasChoices("DAILY_COST_LIMIT_GLOBAL"))
    daily_cost_limit_user: float = Field(default=0.3, validation_alias=AliasChoices("DAILY_COST_LIMIT_USER"))
    llm_cost_per_1k_chars_input: float = Field(
        default=0.0015, validation_alias=AliasChoices("LLM_COST_PER_1K_CHARS_INPUT")
    )
    llm_cost_per_1k_chars_output: float = Field(
        default=0.0020, validation_alias=AliasChoices("LLM_COST_PER_1K_CHARS_OUTPUT")
    )
    tool_cost_overrides: Optional[str] = Field(default=None, validation_alias=AliasChoices("TOOL_COST_OVERRIDES"))

    # Proactive follow-up
    proactive_enabled: bool = Field(default=True, validation_alias=AliasChoices("PROACTIVE_ENABLED"))
    proactive_scan_minutes: int = Field(default=20, validation_alias=AliasChoices("PROACTIVE_SCAN_MINUTES"))
    proactive_default_hours: int = Field(default=24, validation_alias=AliasChoices("PROACTIVE_DEFAULT_HOURS"))

    def build_redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @staticmethod
    def parse_name_list(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def parse_int_list(raw: Optional[str]) -> List[int]:
        values: List[int] = []
        for item in Settings.parse_name_list(raw):
            try:
                values.append(int(item))
            except ValueError:
                continue
        return values

    @staticmethod
    def parse_cost_overrides(raw: Optional[str]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        if not raw:
            return result
        for pair in raw.split(","):
            if ":" not in pair:
                continue
            key, value = pair.split(":", 1)
            key = key.strip()
            try:
                result[key] = float(value.strip())
            except ValueError:
                continue
        return result


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.redis_url:
        settings.redis_url = settings.build_redis_url()
    return settings
