from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Literal, Optional

from pydantic import AliasChoices, Field, model_validator
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
    redis_retry_seconds: float = Field(
        default=30.0, validation_alias=AliasChoices("REDIS_RETRY_SECONDS")
    )
    redis_health_check_seconds: float = Field(
        default=5.0, validation_alias=AliasChoices("REDIS_HEALTH_CHECK_SECONDS")
    )
    global_memory_max_records: int = Field(
        default=50_000, validation_alias=AliasChoices("GLOBAL_MEMORY_MAX_RECORDS")
    )
    redis_required: bool = Field(default=True, validation_alias=AliasChoices("REDIS_REQUIRED"))
    llm_required: bool = Field(default=True, validation_alias=AliasChoices("LLM_REQUIRED"))

    # LLM / AI
    deepseek_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1", validation_alias=AliasChoices("DEEPSEEK_BASE_URL"))
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias=AliasChoices("DEEPSEEK_MODEL"),
    )
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

    # Web Search
    search_provider: Literal["google", "searxng"] = Field(
        default="google", validation_alias=AliasChoices("SEARCH_PROVIDER")
    )
    google_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("GOOGLE_API_KEY"))
    google_cx: Optional[str] = Field(default=None, validation_alias=AliasChoices("GOOGLE_CX", "GOOGLE_CSE_ID"))
    google_result_count: int = Field(default=5, validation_alias=AliasChoices("GOOGLE_RESULT_COUNT"))
    searxng_base_url: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("SEARXNG_BASE_URL")
    )
    searxng_result_count: int = Field(
        default=5, validation_alias=AliasChoices("SEARXNG_RESULT_COUNT", "SEARCH_RESULT_COUNT")
    )
    search_cost_per_call: float = Field(
        default=0.0, validation_alias=AliasChoices("SEARCH_COST_PER_CALL")
    )

    # Amap
    amap_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("AMAP_KEY"))

    # Image
    image_provider: Literal["openai", "gemini", "qwen", "stability", "none"] = Field(
        default="none", validation_alias=AliasChoices("IMAGE_PROVIDER")
    )
    image_size: str = Field(default="1024x1024", validation_alias=AliasChoices("IMAGE_SIZE"))
    vision_model: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("VISION_MODEL"))
    image_model: str = Field(default="gpt-image-1", validation_alias=AliasChoices("IMAGE_MODEL"))
    gemini_vision_model: str = Field(
        default="gemini-1.5-flash", validation_alias=AliasChoices("GEMINI_VISION_MODEL")
    )
    qwen_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("QWEN_API_KEY", "DASHSCOPE_API_KEY")
    )
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
    )
    qwen_vision_model: str = Field(
        default="qwen-vl-plus",
        validation_alias=AliasChoices("QWEN_VISION_MODEL", "DASHSCOPE_VISION_MODEL"),
    )
    stability_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("STABILITY_API_KEY"))

    # Image safety (prevent OOM on low-memory instances)
    image_max_download_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        validation_alias=AliasChoices("IMAGE_MAX_DOWNLOAD_BYTES"),
    )
    image_max_width: int = Field(
        default=4096,
        validation_alias=AliasChoices("IMAGE_MAX_WIDTH"),
    )
    image_max_height: int = Field(
        default=4096,
        validation_alias=AliasChoices("IMAGE_MAX_HEIGHT"),
    )
    image_max_pixels: int = Field(
        default=8_847_360,  # ~4K (4096×2160)
        validation_alias=AliasChoices("IMAGE_MAX_PIXELS"),
    )
    image_download_timeout: float = Field(
        default=15.0,
        validation_alias=AliasChoices("IMAGE_DOWNLOAD_TIMEOUT"),
    )
    image_rate_limit_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices("IMAGE_RATE_LIMIT_SECONDS"),
    )

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

    # Dashboard
    dashboard_token: Optional[str] = Field(default=None, validation_alias=AliasChoices("DASHBOARD_TOKEN"))

    # Chat
    max_history_turns: int = Field(default=50, validation_alias=AliasChoices("MAX_HISTORY_TURNS"))
    reply_random_chance: float = Field(default=0.001, validation_alias=AliasChoices("REPLY_RANDOM_CHANCE"))
    record_undirected_group_messages: bool = Field(
        default=False,
        validation_alias=AliasChoices("RECORD_UNDIRECTED_GROUP_MESSAGES"),
    )
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
        default=400, validation_alias=AliasChoices("GROUP_REPLY_MAX_CHARS_UNDIRECTED")
    )
    known_bot_user_ids: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("KNOWN_BOT_USER_IDS")
    )
    chat_rhythm_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("CHAT_RHYTHM_ENABLED")
    )
    chat_rhythm_fast_turn_seconds: float = Field(
        default=6.0, validation_alias=AliasChoices("CHAT_RHYTHM_FAST_TURN_SECONDS")
    )
    chat_rhythm_window_seconds: int = Field(
        default=30, validation_alias=AliasChoices("CHAT_RHYTHM_WINDOW_SECONDS")
    )
    chat_rhythm_cooldown_seconds: int = Field(
        default=90, validation_alias=AliasChoices("CHAT_RHYTHM_COOLDOWN_SECONDS")
    )
    chat_rhythm_max_cooldown_seconds: int = Field(
        default=900, validation_alias=AliasChoices("CHAT_RHYTHM_MAX_COOLDOWN_SECONDS")
    )
    chat_reply_debounce_seconds: float = Field(
        default=1.2, validation_alias=AliasChoices("CHAT_REPLY_DEBOUNCE_SECONDS")
    )
    chat_reply_max_chars_micro: int = Field(
        default=168, validation_alias=AliasChoices("CHAT_REPLY_MAX_CHARS_MICRO")
    )
    chat_reply_max_chars_short: int = Field(
        default=400, validation_alias=AliasChoices("CHAT_REPLY_MAX_CHARS_SHORT")
    )
    chat_reply_max_chars_normal: int = Field(
        default=1120, validation_alias=AliasChoices("CHAT_REPLY_MAX_CHARS_NORMAL")
    )
    chat_reply_max_chars_deep: int = Field(
        default=2560, validation_alias=AliasChoices("CHAT_REPLY_MAX_CHARS_DEEP")
    )
    chat_reply_max_tokens_micro: int = Field(
        default=384, validation_alias=AliasChoices("CHAT_REPLY_MAX_TOKENS_MICRO")
    )
    chat_reply_max_tokens_short: int = Field(
        default=720, validation_alias=AliasChoices("CHAT_REPLY_MAX_TOKENS_SHORT")
    )
    chat_reply_max_tokens_normal: int = Field(
        default=1920, validation_alias=AliasChoices("CHAT_REPLY_MAX_TOKENS_NORMAL")
    )
    chat_reply_max_tokens_deep: int = Field(
        default=4096, validation_alias=AliasChoices("CHAT_REPLY_MAX_TOKENS_DEEP")
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
    proactive_enabled: bool = Field(default=False, validation_alias=AliasChoices("PROACTIVE_ENABLED"))
    proactive_scan_minutes: int = Field(default=20, validation_alias=AliasChoices("PROACTIVE_SCAN_MINUTES"))
    proactive_default_hours: int = Field(default=24, validation_alias=AliasChoices("PROACTIVE_DEFAULT_HOURS"))

    # Autonomy
    autonomy_enabled: bool = Field(default=False, validation_alias=AliasChoices("AUTONOMY_ENABLED"))
    autonomy_owner_id: Optional[int] = Field(default=None, validation_alias=AliasChoices("AUTONOMY_OWNER_ID"))
    autonomy_group_ids: Optional[str] = Field(default=None, validation_alias=AliasChoices("AUTONOMY_GROUP_IDS"))
    autonomy_private_user_ids: Optional[str] = Field(default=None, validation_alias=AliasChoices("AUTONOMY_PRIVATE_USER_IDS"))
    autonomy_scan_minutes: int = Field(default=10, validation_alias=AliasChoices("AUTONOMY_SCAN_MINUTES"))
    autonomy_cooldown_seconds: int = Field(default=600, validation_alias=AliasChoices("AUTONOMY_COOLDOWN_SECONDS"))
    autonomy_dm_cooldown_seconds: int = Field(default=3600, validation_alias=AliasChoices("AUTONOMY_DM_COOLDOWN_SECONDS"))
    autonomy_pending_ttl_seconds: int = Field(default=1800, validation_alias=AliasChoices("AUTONOMY_PENDING_TTL_SECONDS"))
    autonomy_context_hours: int = Field(default=2, validation_alias=AliasChoices("AUTONOMY_CONTEXT_HOURS"))
    autonomy_context_limit: int = Field(default=30, validation_alias=AliasChoices("AUTONOMY_CONTEXT_LIMIT"))

    # Successful outbound-message ledger. Frequency cooldown and semantic
    # repetition are separate controls: a message may be outside the short
    # cooldown and still be too similar to something sent earlier that day.
    outbound_dedup_hours: int = Field(default=18, validation_alias=AliasChoices("OUTBOUND_DEDUP_HOURS"))
    outbound_dedup_similarity: float = Field(
        default=0.82,
        validation_alias=AliasChoices("OUTBOUND_DEDUP_SIMILARITY"),
    )
    outbound_dedup_max_records: int = Field(
        default=200,
        validation_alias=AliasChoices("OUTBOUND_DEDUP_MAX_RECORDS"),
    )
    outbound_greeting_cooldown_hours: int = Field(
        default=36,
        validation_alias=AliasChoices("OUTBOUND_GREETING_COOLDOWN_HOURS"),
    )

    def build_redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> "Settings":
        if not 0.0 <= self.reply_random_chance <= 1.0:
            raise ValueError("REPLY_RANDOM_CHANCE must be between 0 and 1")
        if self.max_history_turns < 1:
            raise ValueError("MAX_HISTORY_TURNS must be positive")
        if self.chat_rhythm_fast_turn_seconds <= 0 or self.chat_rhythm_window_seconds < 1:
            raise ValueError("Chat rhythm intervals must be positive")
        if self.chat_rhythm_cooldown_seconds < 1 or self.chat_rhythm_max_cooldown_seconds < 1:
            raise ValueError("Chat rhythm cooldowns must be positive")
        if self.chat_rhythm_cooldown_seconds > self.chat_rhythm_max_cooldown_seconds:
            raise ValueError("CHAT_RHYTHM_COOLDOWN_SECONDS cannot exceed max cooldown")
        if self.chat_reply_debounce_seconds < 0:
            raise ValueError("CHAT_REPLY_DEBOUNCE_SECONDS cannot be negative")
        for value in (
            self.chat_reply_max_chars_micro,
            self.chat_reply_max_chars_short,
            self.chat_reply_max_chars_normal,
            self.chat_reply_max_chars_deep,
            self.chat_reply_max_tokens_micro,
            self.chat_reply_max_tokens_short,
            self.chat_reply_max_tokens_normal,
            self.chat_reply_max_tokens_deep,
        ):
            if value < 1:
                raise ValueError("Chat reply limits must be positive")
        if self.global_memory_max_records < 1000:
            raise ValueError("GLOBAL_MEMORY_MAX_RECORDS must be at least 1000")
        if self.search_cost_per_call < 0:
            raise ValueError("SEARCH_COST_PER_CALL cannot be negative")
        if self.outbound_greeting_cooldown_hours < 1:
            raise ValueError("OUTBOUND_GREETING_COOLDOWN_HOURS must be positive")
        if self.redis_retry_seconds < 1 or self.redis_health_check_seconds < 1:
            raise ValueError("Redis retry and health-check intervals must be at least one second")
        if self.dashboard_token and len(self.dashboard_token) < 32:
            raise ValueError("DASHBOARD_TOKEN must contain at least 32 characters")
        if self.autonomy_enabled and self.autonomy_owner_id is None:
            raise ValueError("AUTONOMY_OWNER_ID is required when AUTONOMY_ENABLED=true")
        if self.autonomy_enabled and not (
            self.parse_int_list(self.autonomy_group_ids)
            or self.parse_int_list(self.autonomy_private_user_ids)
        ):
            raise ValueError(
                "At least one AUTONOMY_GROUP_IDS or AUTONOMY_PRIVATE_USER_IDS target is required"
            )
        return self

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
