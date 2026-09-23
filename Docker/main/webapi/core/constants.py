from pathlib import Path
import os
from typing import Any


RUNTIME_DIR = Path(os.getenv("DATA_UI_RUNTIME_DIR", "/app/runtime/webui"))
SCHEDULE_FILE = RUNTIME_DIR / "schedule.json"
RUN_HISTORY_FILE = RUNTIME_DIR / "run_history.jsonl"
TASK_LOG_DIR = RUNTIME_DIR / "task_logs"
RESTORE_LOG_DIR = RUNTIME_DIR / "restore_logs"
# Keep the newest N restore reports; they are diagnostics, not user documents.
MAX_RESTORE_LOGS = 20
APP_CONFIG_FILE = RUNTIME_DIR / "app_config.json"
APP_CONFIG_KEY_FILE = RUNTIME_DIR / ".app_config.key"
THUMB_CACHE_DIR = RUNTIME_DIR / "thumb_cache"
THUMB_GALLARY_DIR = Path(os.getenv("DATA_UI_THUMB_GALLARY_DIR", "/app/runtime/thumb_gallary"))
GALLERY_CACHE_DIR = RUNTIME_DIR / "gallery_cache"
TRANSLATION_DIR = RUNTIME_DIR / "translations"
LOCAL_LIB_DIR = Path(os.getenv("DATA_UI_LOCAL_LIB_DIR", "/app/runtime/local_lib"))
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Largest `limit` the home feeds accept. It has to cover the biggest page size
# the settings offer (100), otherwise asking for a 100-row page comes back 422.
MAX_HOME_FEED_LIMIT = 100

CONFIG_SCOPE = "global"

DEFAULT_SCHEDULE = {
    "local_ingest": {"enabled": False, "cron": "10 * * * *"},
}

CONFIG_SPECS: dict[str, dict[str, Any]] = {
    "POSTGRES_DSN": {"type": "text", "default": "", "secret": True},
    "POSTGRES_HOST": {"type": "text", "default": "pgvector-db"},
    "POSTGRES_PORT": {"type": "int", "default": 5432, "min": 1, "max": 65535},
    "POSTGRES_DB": {"type": "text", "default": "lrr_library"},
    "POSTGRES_USER": {"type": "text", "default": "postgres"},
    "POSTGRES_PASSWORD": {"type": "text", "default": "", "secret": True},
    "POSTGRES_SSLMODE": {"type": "text", "default": "prefer"},
    "OPENAI_API_KEY": {"type": "text", "default": "", "secret": True},
    "OPENAI_HEALTH_URL": {"type": "url", "default": ""},
    "DATA_UI_LANG": {"type": "text", "default": "zh"},
    "DATA_UI_TIMEZONE": {"type": "text", "default": "UTC"},
    "DATA_UI_THEME_MODE": {"type": "text", "default": "system"},
    "DATA_UI_THEME_PRESET": {"type": "text", "default": "modern"},
    "DATA_UI_THEME_OLED": {"type": "bool", "default": False},
    "AUTH_SESSION_TTL_HOURS": {"type": "int", "default": 72, "min": 1, "max": 720},
    "AUTH_COOKIE_SECURE": {"type": "bool", "default": False},
    "DATA_UI_THEME_CUSTOM_PRIMARY": {"type": "text", "default": "#6750A4"},
    "DATA_UI_THEME_CUSTOM_SECONDARY": {"type": "text", "default": "#625B71"},
    "DATA_UI_THEME_CUSTOM_ACCENT": {"type": "text", "default": "#7D5260"},
    "REC_PROFILE_DAYS": {"type": "int", "default": 30, "min": 1, "max": 365},
    "REC_CANDIDATE_HOURS": {"type": "int", "default": 24, "min": 1, "max": 720},
    "REC_CLUSTER_K": {"type": "int", "default": 3, "min": 1, "max": 8},
    "REC_CLUSTER_CACHE_TTL_S": {"type": "int", "default": 900, "min": 60, "max": 86400},
    "REC_TAG_WEIGHT": {"type": "float", "default": 0.55, "min": 0.0, "max": 1.0},
    "REC_VISUAL_WEIGHT": {"type": "float", "default": 0.45, "min": 0.0, "max": 1.0},
    "REC_FEEDBACK_WEIGHT": {"type": "float", "default": 0.0, "min": 0.0, "max": 1.0},
    "REC_PROFILE_WEIGHT": {"type": "float", "default": 0.18, "min": 0.0, "max": 1.0},
    "REC_TEMPERATURE": {"type": "float", "default": 0.3, "min": 0.05, "max": 2.0},
    "REC_CANDIDATE_LIMIT": {"type": "int", "default": 400, "min": 50, "max": 2000},
    "REC_TAG_FLOOR_SCORE": {"type": "float", "default": 0.08, "min": 0.0, "max": 0.4},
    "REC_TAG_ZERO_LIST": {"type": "text", "default": ""},
    "REC_TOUCH_PENALTY_PCT": {"type": "int", "default": 35, "min": 0, "max": 100},
    "REC_IMPRESSION_PENALTY_PCT": {"type": "int", "default": 3, "min": 0, "max": 100},
    "REC_DYNAMIC_EXPAND_ENABLED": {"type": "bool", "default": True},
    "REC_DEBUG_DETAILS": {"type": "bool", "default": False},
    "REC_SHOW_JPN_TITLE": {"type": "bool", "default": False},
    "REC_USE_TRANSLATED_TAGS": {"type": "bool", "default": False},
    "REC_PREVIEW_UI_MODE": {"type": "text", "default": "auto"},
    "REC_PREVIEW_DRAWER_SIDE": {"type": "text", "default": "right"},
    "SEARCH_TEXT_WEIGHT": {"type": "float", "default": 0.6, "min": 0.0, "max": 1.0},
    "SEARCH_VISUAL_WEIGHT": {"type": "float", "default": 0.4, "min": 0.0, "max": 1.0},
    "SEARCH_MIXED_TEXT_WEIGHT": {"type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
    "SEARCH_MIXED_VISUAL_WEIGHT": {"type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
    "SEARCH_FORCE_LLM": {"type": "bool", "default": False},
    "SEARCH_NL_ENABLED": {"type": "bool", "default": False},
    "SEARCH_TAG_SMART_ENABLED": {"type": "bool", "default": False},
    "SEARCH_TAG_HARD_FILTER": {"type": "bool", "default": True},
    "SEARCH_RESULT_SIZE": {"type": "int", "default": 20, "min": 20, "max": 100},
    "SEARCH_RESULT_INFINITE": {"type": "bool", "default": False},
    "SEARCH_WEIGHT_VISUAL": {"type": "float", "default": 2.0, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_PAGE_VISUAL": {"type": "float", "default": 1.2, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_DESC": {"type": "float", "default": 0.8, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_TEXT": {"type": "float", "default": 0.7, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_PLOT_VISUAL": {"type": "float", "default": 0.6, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_PLOT_PAGE_VISUAL": {"type": "float", "default": 0.4, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_PLOT_DESC": {"type": "float", "default": 2.0, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_PLOT_TEXT": {"type": "float", "default": 0.9, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_MIXED_VISUAL": {"type": "float", "default": 1.2, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_MIXED_PAGE_VISUAL": {"type": "float", "default": 0.9, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_MIXED_DESC": {"type": "float", "default": 1.4, "min": 0.0, "max": 5.0},
    "SEARCH_WEIGHT_MIXED_TEXT": {"type": "float", "default": 0.9, "min": 0.0, "max": 5.0},
    "SEARCH_TAG_FUZZY_THRESHOLD": {"type": "float", "default": 0.62, "min": 0.2, "max": 1.0},
    "SEARCH_WORK_COVER_WEIGHT": {"type": "float", "default": 0.6, "min": 0.0, "max": 1.0},
    "SEARCH_WORK_PAGE_WEIGHT": {"type": "float", "default": 0.4, "min": 0.0, "max": 1.0},
    "TEXT_INGEST_PRUNE_NOT_SEEN": {"type": "bool", "default": True},
    "WORKER_ONLY_MISSING": {"type": "bool", "default": True},
    "LOCAL_LIB_SHOW_JPN_TITLE": {"type": "bool", "default": False},
    "LOCAL_LIB_USE_TRANSLATED_TAGS": {"type": "bool", "default": True},
    # How the library feeds present their rows. `infinite` keeps the original
    # append-on-scroll behaviour (24 per request); `paged` shows one page at a
    # time with a pager, so the page size and the pull-at-the-bottom affordance
    # only mean anything in that mode -- the settings UI greys them out otherwise.
    "LOCAL_LIB_FEED_MODE": {"type": "text", "default": "infinite"},
    "LOCAL_LIB_PAGE_SIZE": {"type": "int", "default": 20, "min": 10, "max": 100},
    "LOCAL_LIB_PULL_TO_PAGE": {"type": "bool", "default": False},
    "LOCAL_LIB_CUSTOM_CATEGORIES": {"type": "text", "default": "[]"},
    "LOCAL_LIB_PINNED_CATEGORY_KEYS": {"type": "text", "default": "[]"},
    "LOCAL_LIB_CUSTOM_NAMESPACES": {"type": "text", "default": "[]"},
    "TEXT_INGEST_BATCH_SIZE": {"type": "int", "default": 1000, "min": 100, "max": 5000},
    "LLM_API_BASE": {"type": "url", "default": "http://llm-router:8000/v1"},
    "LLM_API_KEY": {"type": "text", "default": "", "secret": True},
    "LLM_TIMEOUT_S": {"type": "int", "default": 45, "min": 5, "max": 600},
    "LLM_MAX_TOKENS_TAG_EXTRACT": {"type": "int", "default": 1200, "min": 64, "max": 8192},
    "LLM_MODEL": {"type": "text", "default": ""},
    "EMB_MODEL": {"type": "text", "default": ""},
    "INGEST_API_BASE": {"type": "url", "default": ""},
    "INGEST_API_KEY": {"type": "text", "default": "", "secret": True},
    "INGEST_VL_MODEL": {"type": "text", "default": ""},
    "INGEST_EMB_MODEL": {"type": "text", "default": ""},
    "INGEST_VL_MODEL_CUSTOM": {"type": "text", "default": ""},
    "INGEST_EMB_MODEL_CUSTOM": {"type": "text", "default": ""},
    "LLM_MODEL_CUSTOM": {"type": "text", "default": ""},
    "EMB_MODEL_CUSTOM": {"type": "text", "default": ""},
    "SIGLIP_MODEL": {"type": "text", "default": "google/siglip-so400m-patch14-384"},
    "SIGLIP_WORKER_ENABLED": {"type": "bool", "default": True},
    "SIGLIP_DEVICE": {"type": "text", "default": "cpu"},
    "WORKER_BATCH": {"type": "int", "default": 32, "min": 1, "max": 512},
    "WORKER_SLEEP": {"type": "float", "default": 0.0, "min": 0.0, "max": 60.0},
    "WORKS_PAGE_SAMPLE_COUNT": {"type": "int", "default": 4, "min": 1, "max": 8},
    "TAG_TRANSLATION_REPO": {"type": "text", "default": ""},
    "TAG_TRANSLATION_AUTO_UPDATE_HOURS": {"type": "int", "default": 24, "min": 1, "max": 720},
    "PROMPT_TAG_EXTRACT_SYSTEM": {
        "type": "text",
        "default": "你是本地漫画库的标签检索助手。请将用户的自然语言查询映射到 allowed_tags 中最相关的标签。只能选择已提供的标签，并仅输出 {\"tags\": [...]} 格式的 JSON。",
    },    # Recovery codes (comma-separated SHA256 hashes, burn-on-use)
    "DATA_UI_RECOVERY_CODES": {"type": "text", "default": ""},
    "READER_DIRECTION": {"type": "text", "default": "ltr"},
    "READER_MODE": {"type": "text", "default": "paged"},
    "READER_SPREAD_MODE": {"type": "text", "default": "single"},
    "READER_FIT_MODE": {"type": "text", "default": "contain"},
    "READER_FILTER_PRESET": {"type": "text", "default": "none"},
    "READER_SWIPE_ENABLED": {"type": "bool", "default": True},
    "READER_TAP_TO_TURN": {"type": "bool", "default": True},
    "READER_PAGE_ANIM_ENABLED": {"type": "bool", "default": True},
    "READER_PRELOAD_COUNT": {"type": "int", "default": 10, "min": 10, "max": 20},
    "READER_IMAGE_QUALITY_MODE": {"type": "text", "default": "high"},
    "LOCAL_THUMB_PRESET": {"type": "text", "default": "mid"},
    "READER_WHEEL_RADIUS": {"type": "float", "default": 320.0, "min": 120.0, "max": 1000000.0},
    "READER_WHEEL_CURVE": {"type": "int", "default": 55, "min": 0, "max": 100},
    "READER_WHEEL_RANGE": {"type": "int", "default": 4, "min": 2, "max": 20},
    "READER_WHEEL_EXTENT_PCT": {"type": "int", "default": 100, "min": 60, "max": 220},
    "READER_WHEEL_THUMB_SCALE_PCT": {"type": "int", "default": 100, "min": 60, "max": 220},
    "READER_WHEEL_THUMB_WIDTH": {"type": "int", "default": 74, "min": 44, "max": 220},
    "READER_WHEEL_THUMB_HEIGHT": {"type": "int", "default": 96, "min": 56, "max": 280},
    "READER_WHEEL_POSITION": {"type": "text", "default": "bottom"},
    "READER_HIDE_START_BUTTON": {"type": "bool", "default": False},
    "READER_HIDE_APP_UI": {"type": "bool", "default": True},
    "READER_VIEWPORT_FIT_COVER": {"type": "bool", "default": True},
    # End-of-gallery "guess you like" strip. The two weights are normalised
    # against each other, so only their ratio matters: the reference is the
    # gallery's own `visual_embedding` plus its tags, never the page vectors
    # (a final page is usually blank credits, so it carries no signal).
    "READER_REC_ENABLED": {"type": "bool", "default": True},
    "READER_REC_VISUAL_WEIGHT": {"type": "float", "default": 0.6, "min": 0.0, "max": 1.0},
    "READER_REC_TAG_WEIGHT": {"type": "float", "default": 0.4, "min": 0.0, "max": 1.0},
    "READER_REC_LIMIT": {"type": "int", "default": 6, "min": 3, "max": 12},
    "REC_SHOW_PAGE_COUNT": {"type": "bool", "default": True},
}

TASK_COMMANDS = {"local_ingest": ["__local_ingest__"]}
