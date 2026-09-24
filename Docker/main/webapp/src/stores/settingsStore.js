import { computed, ref, watch } from "vue";
import { defineStore } from "pinia";
import {
  clearReadEvents,
  disableVisualTask,
  enableVisualTask,
  clearRuntimeDeps,
  clearSiglip,
  clearWorksDuplicates,
  downloadAppConfigBackup,
  downloadSiglip,
  getDbHealth,
  getConfig,
  getConfigSchema,
  getModelStatus,
  getHomeTagSuggest,
  getProviderModels,
  getSiglipDownloadStatus,
  getTranslationStatus,
  restoreAppConfigBackup,
  updateConfig,
  uploadTranslationFile,
} from "../api";
import { useToastStore } from "./useToastStore";
import { useControlStore } from "./controlStore";
import { useAppStore } from "./appStore";
import { parseCsv } from "../utils/helpers";
import {
  BUILTIN_LOCAL_CATEGORY_DEFS,
  buildEffectiveCategoryDefs,
  getPinnedCategoryDefs,
  parseCustomCategoryConfig,
  parsePinnedCategoryKeys,
} from "../utils/categoryPresets";
import { BUILTIN_NAMESPACE_DEFS, parseCustomNamespaceConfig } from "../utils/tagNamespaces";

export const useSettingsStore = defineStore("settings", () => {
  const toast = useToastStore();
  const controlStore = useControlStore();
  const appStore = useAppStore();

  const config = ref({});
  const schema = ref({});
  const configMeta = ref({});
  const secretState = ref({});
  const settingsTab = ref("general");
  const llmModelOptions = ref([]);
  const ingestModelOptions = ref([]);
  const appConfigRestoreRef = ref(null);
  const translationStatus = ref({ repo: "", head_sha: "", fetched_at: "-", manual_file: { path: "", exists: false, size: 0, updated_at: "-" } });
  const translationUploadRef = ref(null);
  const modelStatus = ref({
    siglip: { path: "", size_mb: 0, usable: false },
    runtime_deps: { path: "", size_mb: 0, ready: false },
  });
  const dbHealth = ref({ ok: null, error: "", works: 0, timezone: "-" });
  const dbHealthLoading = ref(false);
  const siglipDownload = ref({ task_id: "", status: "", progress: 0, stage: "", error: "", logs: [] });
  const recTagZeroList = ref([]);
  const newRecTag = ref("");
  const recTagSuggestions = ref([]);

  // --- config auto-save ------------------------------------------------------
  // Every settings surface binds `config` (directly, or through a computed setter
  // that writes into it), so the store is the only place that can see all of them
  // at once. Instead of a save button per page, changes are diffed against the
  // last payload the server acknowledged and flushed debounced.
  //
  // Diffing rather than "PUT the whole object" is what makes this safe: the
  // dashboard and the reader keep writing the same object while the user is
  // elsewhere, and a whole-object PUT would push whatever those surfaces had
  // normalised on top of each other. Only genuinely changed keys travel.
  const AUTO_SAVE_DEBOUNCE_MS = 600;
  const AUTO_SAVE_IDLE_MS = 2400;
  // idle | pending | saving | saved | error
  const configSaveState = ref("idle");
  const configSaveError = ref("");
  let _savedConfig = null;
  let _autoSaveTimer = null;
  let _autoSaveIdleTimer = null;
  let _autoSaveInFlight = null;
  let _autoSaveAgain = false;
  const themeOptions = [
    { title: "Modern", value: "modern" },
    { title: "Ocean", value: "ocean" },
    { title: "Sunset", value: "sunset" },
    { title: "Forest", value: "forest" },
    { title: "Slate", value: "slate" },
    { title: "Custom", value: "custom" },
  ];
  const timezoneOptions = ref(["UTC", "Asia/Shanghai", "Asia/Tokyo", "America/New_York", "Europe/Berlin"]);

  let _t = (k, _vars = {}) => k;
  let _setLang = null;
  let siglipPollTimer = null;
  let syncing = false;

  const themeModeOptions = computed(() => [
    { title: _t("theme.mode.system"), value: "system" },
    { title: _t("theme.mode.light"), value: "light" },
    { title: _t("theme.mode.dark"), value: "dark" },
  ]);

  const llmReady = computed(() => false);

  const limitedModeMessages = computed(() => {
    const out = [];
    const ingestBase = String(config.value.INGEST_API_BASE || "").trim();
    const ingestVl = String(config.value.INGEST_VL_MODEL_CUSTOM || config.value.INGEST_VL_MODEL || "").trim();
    const ingestEmb = String(config.value.INGEST_EMB_MODEL_CUSTOM || config.value.INGEST_EMB_MODEL || "").trim();
    if (!ingestBase || !ingestVl || !ingestEmb) out.push(_t("settings.limited_mode.ingest"));
    const llmBase = String(config.value.LLM_API_BASE || "").trim();
    const embModel = String(config.value.EMB_MODEL_CUSTOM || config.value.EMB_MODEL || "").trim();
    if (!llmBase || !embModel) out.push(_t("settings.limited_mode.llm"));
    return out;
  });

  const health = computed(() => controlStore.health || { database: {}, services: {} });
  const accountForm = computed(() => appStore.accountForm);
  const builtinCategoryDefs = computed(() => BUILTIN_LOCAL_CATEGORY_DEFS.map((it) => ({ ...it })));
  const customCategoryDefs = computed(() => parseCustomCategoryConfig(config.value.LOCAL_LIB_CUSTOM_CATEGORIES || "[]"));
  const pinnedCategoryKeys = computed(() => parsePinnedCategoryKeys(config.value.LOCAL_LIB_PINNED_CATEGORY_KEYS || "[]", customCategoryDefs.value));
  const localCategoryDefs = computed(() => buildEffectiveCategoryDefs(customCategoryDefs.value, pinnedCategoryKeys.value));
  const pinnedLocalCategoryDefs = computed(() => getPinnedCategoryDefs(customCategoryDefs.value, pinnedCategoryKeys.value));
  const builtinNamespaceDefs = computed(() => BUILTIN_NAMESPACE_DEFS.map((it) => ({ ...it })));
  const customNamespaceDefs = computed(() => parseCustomNamespaceConfig(config.value.LOCAL_LIB_CUSTOM_NAMESPACES || "[]"));

  function init(deps = {}) {
    if (typeof deps.t === "function") _t = deps.t;
    if (typeof deps.setLang === "function") _setLang = deps.setLang;
  }

  function t(key, vars = {}) {
    return _t(key, vars);
  }

  function parseBool(value, defaultValue = false) {
    if (value === true || value === false) return value;
    if (value === 1 || value === "1") return true;
    if (value === 0 || value === "0") return false;
    const s = String(value ?? "").trim().toLowerCase();
    if (["true", "yes", "on"].includes(s)) return true;
    if (["false", "no", "off"].includes(s)) return false;
    return !!defaultValue;
  }

  function notify(text, color = "success") {
    toast.open(text, color);
  }

  function addRecTag() {
    const v = String(newRecTag.value || "").trim().toLowerCase();
    if (!v) return;
    if (!recTagZeroList.value.includes(v)) recTagZeroList.value.push(v);
    newRecTag.value = "";
  }

  function removeRecTag(tag) {
    recTagZeroList.value = recTagZeroList.value.filter((x) => x !== tag);
  }

  async function loadRecTagSuggestions() {
    const q = String(newRecTag.value || "").trim();
    if (q.length < 2) {
      recTagSuggestions.value = [];
      return;
    }
    try {
      const res = await getHomeTagSuggest({
        q,
        limit: 10,
        ui_lang: String(config.value.DATA_UI_LANG || "zh"),
      });
      recTagSuggestions.value = Array.isArray(res?.items) ? res.items : [];
    } catch {
      recTagSuggestions.value = [];
    }
  }

  function labelFor(key) {
    const map = {
      POSTGRES_HOST: "settings.pg.host",
      POSTGRES_PORT: "settings.pg.port",
      POSTGRES_DB: "settings.pg.db",
      POSTGRES_USER: "settings.pg.user",
      POSTGRES_PASSWORD: "settings.pg.password",
      POSTGRES_SSLMODE: "settings.pg.sslmode",
      OPENAI_HEALTH_URL: "settings.openai.health",
      INGEST_API_KEY: "settings.provider.ingest_api_key",
      DATA_UI_TIMEZONE: "settings.ui.timezone",
      DATA_UI_THEME_MODE: "settings.ui.theme_mode",
      DATA_UI_THEME_PRESET: "settings.ui.theme_preset",
      DATA_UI_THEME_OLED: "settings.ui.theme_oled",
      DATA_UI_THEME_CUSTOM_PRIMARY: "settings.ui.custom_primary",
      DATA_UI_THEME_CUSTOM_SECONDARY: "settings.ui.custom_secondary",
      DATA_UI_THEME_CUSTOM_ACCENT: "settings.ui.custom_accent",
      REC_PROFILE_DAYS: "settings.rec.profile_days",
      REC_CANDIDATE_HOURS: "settings.rec.candidate_hours",
      REC_CLUSTER_K: "settings.rec.cluster_k",
      REC_CLUSTER_CACHE_TTL_S: "settings.rec.cache_ttl",
      REC_TAG_WEIGHT: "settings.rec.tag_weight",
      REC_VISUAL_WEIGHT: "settings.rec.visual_weight",
      REC_FEEDBACK_WEIGHT: "settings.rec.feedback_weight",
      REC_PROFILE_WEIGHT: "settings.rec.profile_weight",
      REC_TEMPERATURE: "settings.rec.temperature",
      REC_CANDIDATE_LIMIT: "settings.rec.candidate_limit",
      REC_TAG_FLOOR_SCORE: "settings.rec.tag_floor",
      REC_TAG_ZERO_LIST: "settings.rec.tag_zero_list",
      REC_TOUCH_PENALTY_PCT: "settings.rec.touch_penalty_pct",
      REC_IMPRESSION_PENALTY_PCT: "settings.rec.impression_penalty_pct",
      REC_DYNAMIC_EXPAND_ENABLED: "settings.rec.dynamic_expand_enabled",
      REC_DEBUG_DETAILS: "settings.rec.debug_details",
      REC_SHOW_JPN_TITLE: "settings.rec.show_jpn_title",
      REC_USE_TRANSLATED_TAGS: "settings.rec.use_translated_tags",
      SEARCH_TEXT_WEIGHT: "settings.search.text_weight",
      SEARCH_VISUAL_WEIGHT: "settings.search.visual_weight",
      SEARCH_MIXED_TEXT_WEIGHT: "settings.search.mixed_text_weight",
      SEARCH_MIXED_VISUAL_WEIGHT: "settings.search.mixed_visual_weight",
      SEARCH_NL_ENABLED: "settings.search.nl_enabled",
      SEARCH_TAG_SMART_ENABLED: "settings.search.tag_smart_enabled",
      SEARCH_TAG_HARD_FILTER: "settings.search.tag_hard_filter",
      SEARCH_RESULT_SIZE: "settings.search.result_size",
      SEARCH_RESULT_INFINITE: "settings.search.result_infinite",
      SEARCH_WEIGHT_VISUAL: "settings.search.weight_visual",
      SEARCH_WEIGHT_PAGE_VISUAL: "settings.search.weight_page_visual",
      SEARCH_WEIGHT_DESC: "settings.search.weight_desc",
      SEARCH_WEIGHT_TEXT: "settings.search.weight_text",
      SEARCH_WEIGHT_PLOT_VISUAL: "settings.search.weight_plot_visual",
      SEARCH_WEIGHT_PLOT_PAGE_VISUAL: "settings.search.weight_plot_page_visual",
      SEARCH_WEIGHT_PLOT_DESC: "settings.search.weight_plot_desc",
      SEARCH_WEIGHT_PLOT_TEXT: "settings.search.weight_plot_text",
      SEARCH_WEIGHT_MIXED_VISUAL: "settings.search.weight_mixed_visual",
      SEARCH_WEIGHT_MIXED_PAGE_VISUAL: "settings.search.weight_mixed_page_visual",
      SEARCH_WEIGHT_MIXED_DESC: "settings.search.weight_mixed_desc",
      SEARCH_WEIGHT_MIXED_TEXT: "settings.search.weight_mixed_text",
      SEARCH_TAG_FUZZY_THRESHOLD: "settings.search.fuzzy_threshold",
      SEARCH_WORK_COVER_WEIGHT: "settings.search.work_cover_weight",
      SEARCH_WORK_PAGE_WEIGHT: "settings.search.work_page_weight",
      TEXT_INGEST_PRUNE_NOT_SEEN: "settings.text_ingest.prune",
      WORKER_ONLY_MISSING: "settings.worker.only_missing",
      LOCAL_LIB_SHOW_JPN_TITLE: "settings.local_lib.show_jpn_title",
      LOCAL_LIB_USE_TRANSLATED_TAGS: "settings.local_lib.use_translated_tags",
      TAG_TRANSLATION_REPO: "settings.translation.repo",
      TAG_TRANSLATION_AUTO_UPDATE_HOURS: "settings.translation.auto_update_hours",
      TEXT_INGEST_BATCH_SIZE: "settings.text_ingest.batch",
      LLM_API_BASE: "settings.provider.llm_api_base",
      LLM_API_KEY: "settings.provider.llm_api_key",
      LLM_TIMEOUT_S: "settings.provider.llm_timeout_s",
      LLM_MAX_TOKENS_CHAT: "settings.provider.llm_max_tokens_chat",
      LLM_MAX_TOKENS_INTENT: "settings.provider.llm_max_tokens_intent",
      LLM_MAX_TOKENS_TAG_EXTRACT: "settings.provider.llm_max_tokens_tag_extract",
      LLM_MAX_TOKENS_PROFILE: "settings.provider.llm_max_tokens_profile",
      LLM_MAX_TOKENS_REPORT: "settings.provider.llm_max_tokens_report",
      LLM_MAX_TOKENS_SEARCH_NARRATIVE: "settings.provider.llm_max_tokens_search_narrative",
      LLM_MODEL: "settings.provider.llm_model",
      LLM_MODEL_CUSTOM: "settings.provider.llm_model_custom",
      EMB_MODEL: "settings.provider.emb_model",
      EMB_MODEL_CUSTOM: "settings.provider.emb_model_custom",
      INGEST_API_BASE: "settings.provider.ingest_api_base",
      INGEST_VL_MODEL: "settings.provider.ingest_vl_model",
      INGEST_EMB_MODEL: "settings.provider.ingest_emb_model",
      INGEST_VL_MODEL_CUSTOM: "settings.provider.ingest_vl_model_custom",
      INGEST_EMB_MODEL_CUSTOM: "settings.provider.ingest_emb_model_custom",
      SIGLIP_MODEL: "settings.provider.siglip_model",
      SIGLIP_WORKER_ENABLED: "settings.provider.siglip_worker_enabled",
      WORKER_BATCH: "settings.provider.worker_batch",
      WORKER_SLEEP: "settings.provider.worker_sleep",
      MEMORY_SHORT_TERM_ENABLED: "settings.memory.short_term_enabled",
      MEMORY_LONG_TERM_ENABLED: "settings.memory.long_term_enabled",
      MEMORY_SEMANTIC_ENABLED: "settings.memory.semantic_enabled",
      MEMORY_SHORT_TERM_LIMIT: "settings.memory.short_term_limit",
      MEMORY_LONG_TERM_TOP_TAGS: "settings.memory.long_term_top_tags",
      MEMORY_SEMANTIC_TOP_FACTS: "settings.memory.semantic_top_facts",
    };
    const tk = map[key];
    return tk ? t(tk) : key;
  }

  function secretHint(key) {
    return secretState.value[key] ? t("settings.secret.present") : t("settings.secret.empty");
  }

  function getGalleryTitle(item) {
    if (config.value.REC_SHOW_JPN_TITLE && item.subtitle) {
      return item.subtitle;
    }
    return item.title || "-";
  }

  function normalizeSearchWeights(prefixA, prefixB, changedKey) {
    const a = Number(config.value[prefixA] ?? 0.5);
    const b = Number(config.value[prefixB] ?? 0.5);
    const ca = Number.isFinite(a) ? Math.max(0, Math.min(1, a)) : 0.5;
    const cb = Number.isFinite(b) ? Math.max(0, Math.min(1, b)) : 0.5;
    if (changedKey === prefixA) {
      config.value[prefixA] = ca;
      config.value[prefixB] = Number((1 - ca).toFixed(4));
    } else if (changedKey === prefixB) {
      config.value[prefixB] = cb;
      config.value[prefixA] = Number((1 - cb).toFixed(4));
    } else {
      const sum = ca + cb;
      config.value[prefixA] = sum <= 0 ? 0.5 : Number((ca / sum).toFixed(4));
      config.value[prefixB] = sum <= 0 ? 0.5 : Number((cb / sum).toFixed(4));
    }
  }

  function normalizeSearchChannelWeights(changedKey, keys = ["SEARCH_WEIGHT_VISUAL", "SEARCH_WEIGHT_PAGE_VISUAL", "SEARCH_WEIGHT_DESC", "SEARCH_WEIGHT_TEXT"]) {
    if (syncing) return;
    syncing = true;
    try {
      const vals = keys.map((k) => {
        const n = Number(config.value[k] ?? 0);
        return Number.isFinite(n) ? Math.max(0, Math.min(5, n)) : 0;
      });
      const idx = keys.indexOf(changedKey);
      const target = idx >= 0 ? vals[idx] : vals[0];
      const restSum = vals.reduce((a, b, i) => a + (i === idx ? 0 : b), 0);
      const budget = Math.max(0, 5 - target);
      const scaled = vals.map((v, i) => {
        if (i === idx) return target;
        if (restSum <= 1e-9) return budget / Math.max(1, keys.length - 1);
        return (v / restSum) * budget;
      });
      keys.forEach((k, i) => {
        config.value[k] = Number(scaled[i].toFixed(4));
      });
    } finally {
      syncing = false;
    }
  }

  function normalizeRecommendWeights(changedKey) {
    const a = Number(config.value.REC_TAG_WEIGHT ?? 0.55);
    const b = Number(config.value.REC_VISUAL_WEIGHT ?? 0.45);
    const c = Number(config.value.REC_FEEDBACK_WEIGHT ?? 0.0);
    const ca = Number.isFinite(a) ? Math.max(0, Math.min(1, a)) : 0.55;
    const cb = Number.isFinite(b) ? Math.max(0, Math.min(1, b)) : 0.45;
    const cc = Number.isFinite(c) ? Math.max(0, Math.min(1, c)) : 0.0;

    if (changedKey === "REC_TAG_WEIGHT") {
      const remaining = 1 - ca;
      config.value.REC_TAG_WEIGHT = ca;
      config.value.REC_VISUAL_WEIGHT = Number((remaining * cb / (cb + cc || 1)).toFixed(4));
      config.value.REC_FEEDBACK_WEIGHT = Number((remaining * cc / (cb + cc || 1)).toFixed(4));
    } else if (changedKey === "REC_VISUAL_WEIGHT") {
      const remaining = 1 - cb;
      config.value.REC_VISUAL_WEIGHT = cb;
      config.value.REC_TAG_WEIGHT = Number((remaining * ca / (ca + cc || 1)).toFixed(4));
      config.value.REC_FEEDBACK_WEIGHT = Number((remaining * cc / (ca + cc || 1)).toFixed(4));
    } else if (changedKey === "REC_FEEDBACK_WEIGHT") {
      const remaining = 1 - cc;
      config.value.REC_FEEDBACK_WEIGHT = cc;
      config.value.REC_TAG_WEIGHT = Number((remaining * ca / (ca + cb || 1)).toFixed(4));
      config.value.REC_VISUAL_WEIGHT = Number((remaining * cb / (ca + cb || 1)).toFixed(4));
    } else {
      const sum = ca + cb + cc;
      if (sum <= 0) {
        config.value.REC_TAG_WEIGHT = 0.55;
        config.value.REC_VISUAL_WEIGHT = 0.45;
        config.value.REC_FEEDBACK_WEIGHT = 0.0;
      } else {
        config.value.REC_TAG_WEIGHT = Number((ca / sum).toFixed(4));
        config.value.REC_VISUAL_WEIGHT = Number((cb / sum).toFixed(4));
        config.value.REC_FEEDBACK_WEIGHT = Number((cc / sum).toFixed(4));
      }
    }
  }

  function resetSearchWeightPresets() {
    config.value.SEARCH_WEIGHT_VISUAL = 2.0;
    config.value.SEARCH_WEIGHT_PAGE_VISUAL = 1.2;
    config.value.SEARCH_WEIGHT_DESC = 0.8;
    config.value.SEARCH_WEIGHT_TEXT = 0.7;
    config.value.SEARCH_WEIGHT_PLOT_VISUAL = 0.6;
    config.value.SEARCH_WEIGHT_PLOT_PAGE_VISUAL = 0.4;
    config.value.SEARCH_WEIGHT_PLOT_DESC = 2.0;
    config.value.SEARCH_WEIGHT_PLOT_TEXT = 0.9;
    config.value.SEARCH_WEIGHT_MIXED_VISUAL = 1.2;
    config.value.SEARCH_WEIGHT_MIXED_PAGE_VISUAL = 0.9;
    config.value.SEARCH_WEIGHT_MIXED_DESC = 1.4;
    config.value.SEARCH_WEIGHT_MIXED_TEXT = 0.9;
    config.value.SEARCH_WORK_COVER_WEIGHT = 0.6;
    config.value.SEARCH_WORK_PAGE_WEIGHT = 0.4;
  }

  function resetRecommendPreset() {
    config.value.REC_TEMPERATURE = 0.3;
    config.value.REC_TAG_WEIGHT = 0.55;
    config.value.REC_VISUAL_WEIGHT = 0.45;
    config.value.REC_FEEDBACK_WEIGHT = 0.0;
    normalizeRecommendWeights();
  }

  async function loadConfigData() {
    const [cfg, sch] = await Promise.all([getConfig(), getConfigSchema()]);
    const schemaMap = sch.schema || {};
    const normalized = {};
    Object.entries(cfg.values || {}).forEach(([key, val]) => {
      normalized[key] = schemaMap[key]?.type === "bool" ? String(val).toLowerCase() === "1" || String(val).toLowerCase() === "true" : val;
    });
    config.value = normalized;
    secretState.value = cfg.secret_state || {};
    configMeta.value = cfg.meta || {};
    schema.value = schemaMap;
    recTagZeroList.value = parseCsv(config.value.REC_TAG_ZERO_LIST || "").map((x) => String(x || "").trim().toLowerCase()).filter((x) => !!x);
    if (_setLang && (config.value.DATA_UI_LANG === "en" || config.value.DATA_UI_LANG === "zh")) _setLang(config.value.DATA_UI_LANG);
    if (!config.value.DATA_UI_THEME_MODE) config.value.DATA_UI_THEME_MODE = "system";
    if (!config.value.DATA_UI_THEME_PRESET) config.value.DATA_UI_THEME_PRESET = "modern";
    if (!config.value.DATA_UI_TIMEZONE) config.value.DATA_UI_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    if (!config.value.DATA_UI_THEME_CUSTOM_PRIMARY) config.value.DATA_UI_THEME_CUSTOM_PRIMARY = "#2563eb";
    if (!config.value.DATA_UI_THEME_CUSTOM_SECONDARY) config.value.DATA_UI_THEME_CUSTOM_SECONDARY = "#0ea5e9";
    if (!config.value.DATA_UI_THEME_CUSTOM_ACCENT) config.value.DATA_UI_THEME_CUSTOM_ACCENT = "#f59e0b";
    if (config.value.REC_TEMPERATURE === undefined || config.value.REC_TEMPERATURE === null || config.value.REC_TEMPERATURE === "") {
      config.value.REC_TEMPERATURE = 0.3;
    }
    if (config.value.REC_PROFILE_WEIGHT === undefined || config.value.REC_PROFILE_WEIGHT === null || config.value.REC_PROFILE_WEIGHT === "") {
      config.value.REC_PROFILE_WEIGHT = 0.18;
    }
    if (config.value.REC_TOUCH_PENALTY_PCT === undefined || config.value.REC_TOUCH_PENALTY_PCT === null || config.value.REC_TOUCH_PENALTY_PCT === "") {
      config.value.REC_TOUCH_PENALTY_PCT = 35;
    }
    if (config.value.REC_IMPRESSION_PENALTY_PCT === undefined || config.value.REC_IMPRESSION_PENALTY_PCT === null || config.value.REC_IMPRESSION_PENALTY_PCT === "") {
      config.value.REC_IMPRESSION_PENALTY_PCT = 3;
    }
    if (config.value.REC_DYNAMIC_EXPAND_ENABLED === undefined) {
      config.value.REC_DYNAMIC_EXPAND_ENABLED = true;
    }
    if (config.value.REC_DEBUG_DETAILS === undefined) {
      config.value.REC_DEBUG_DETAILS = false;
    }
    if (config.value.REC_USE_TRANSLATED_TAGS === undefined) {
      config.value.REC_USE_TRANSLATED_TAGS = false;
    }
    if (config.value.LOCAL_LIB_SHOW_JPN_TITLE === undefined) {
      config.value.LOCAL_LIB_SHOW_JPN_TITLE = false;
    }
    if (config.value.LOCAL_LIB_USE_TRANSLATED_TAGS === undefined) {
      config.value.LOCAL_LIB_USE_TRANSLATED_TAGS = true;
    }
    if (config.value.LOCAL_LIB_CUSTOM_CATEGORIES === undefined || config.value.LOCAL_LIB_CUSTOM_CATEGORIES === null || config.value.LOCAL_LIB_CUSTOM_CATEGORIES === "") {
      config.value.LOCAL_LIB_CUSTOM_CATEGORIES = "[]";
    }
    if (config.value.LOCAL_LIB_PINNED_CATEGORY_KEYS === undefined || config.value.LOCAL_LIB_PINNED_CATEGORY_KEYS === null || config.value.LOCAL_LIB_PINNED_CATEGORY_KEYS === "") {
      config.value.LOCAL_LIB_PINNED_CATEGORY_KEYS = "[]";
    }
    if (config.value.LOCAL_LIB_CUSTOM_NAMESPACES === undefined || config.value.LOCAL_LIB_CUSTOM_NAMESPACES === null || config.value.LOCAL_LIB_CUSTOM_NAMESPACES === "") {
      config.value.LOCAL_LIB_CUSTOM_NAMESPACES = "[]";
    }
    // Memory defaults
    if (config.value.MEMORY_SHORT_TERM_ENABLED === undefined) config.value.MEMORY_SHORT_TERM_ENABLED = true;
    if (config.value.MEMORY_LONG_TERM_ENABLED === undefined) config.value.MEMORY_LONG_TERM_ENABLED = true;
    if (config.value.MEMORY_SEMANTIC_ENABLED === undefined) config.value.MEMORY_SEMANTIC_ENABLED = true;
    if (!config.value.MEMORY_SHORT_TERM_LIMIT) config.value.MEMORY_SHORT_TERM_LIMIT = 12;
    if (config.value.MEMORY_LONG_TERM_TOP_TAGS === undefined || config.value.MEMORY_LONG_TERM_TOP_TAGS === null || config.value.MEMORY_LONG_TERM_TOP_TAGS === "") config.value.MEMORY_LONG_TERM_TOP_TAGS = 8;
    if (config.value.MEMORY_SEMANTIC_TOP_FACTS === undefined || config.value.MEMORY_SEMANTIC_TOP_FACTS === null || config.value.MEMORY_SEMANTIC_TOP_FACTS === "") config.value.MEMORY_SEMANTIC_TOP_FACTS = 8;
    if (!config.value.READER_DIRECTION) config.value.READER_DIRECTION = "ltr";
    if (!config.value.READER_MODE) config.value.READER_MODE = "paged";
    if (!config.value.READER_FIT_MODE) config.value.READER_FIT_MODE = "contain";
    if (!config.value.READER_IMAGE_QUALITY_MODE) config.value.READER_IMAGE_QUALITY_MODE = "high";
    if (!config.value.LOCAL_THUMB_PRESET) config.value.LOCAL_THUMB_PRESET = "mid";
    if (!config.value.READER_WHEEL_POSITION) config.value.READER_WHEEL_POSITION = "bottom";
    if (config.value.READER_SWIPE_ENABLED === undefined) config.value.READER_SWIPE_ENABLED = true;
    if (config.value.READER_TAP_TO_TURN === undefined) config.value.READER_TAP_TO_TURN = true;
    if (config.value.READER_PAGE_ANIM_ENABLED === undefined) config.value.READER_PAGE_ANIM_ENABLED = true;
    config.value.READER_HIDE_START_BUTTON = false;
    if (config.value.READER_HIDE_APP_UI === undefined) config.value.READER_HIDE_APP_UI = true;
    if (config.value.READER_VIEWPORT_FIT_COVER === undefined) config.value.READER_VIEWPORT_FIT_COVER = true;
    if (config.value.READER_WHEEL_CURVE === undefined || config.value.READER_WHEEL_CURVE === null || config.value.READER_WHEEL_CURVE === "") {
      const legacyRadius = Number(config.value.READER_WHEEL_RADIUS ?? 320);
      const minR = 120;
      const maxR = 1000000;
      const safeR = Number.isFinite(legacyRadius) ? Math.max(minR, Math.min(maxR, legacyRadius)) : 320;
      const mapped = Math.round((Math.log(safeR / minR) / Math.log(maxR / minR)) * 100);
      config.value.READER_WHEEL_CURVE = Math.max(0, Math.min(100, mapped));
    }
    if (config.value.READER_WHEEL_RANGE === undefined || config.value.READER_WHEEL_RANGE === null || config.value.READER_WHEEL_RANGE === "") {
      config.value.READER_WHEEL_RANGE = 4;
    }
    if (config.value.READER_WHEEL_EXTENT_PCT === undefined || config.value.READER_WHEEL_EXTENT_PCT === null || config.value.READER_WHEEL_EXTENT_PCT === "") {
      config.value.READER_WHEEL_EXTENT_PCT = 100;
    }
    if (config.value.READER_WHEEL_THUMB_SCALE_PCT === undefined || config.value.READER_WHEEL_THUMB_SCALE_PCT === null || config.value.READER_WHEEL_THUMB_SCALE_PCT === "") {
      config.value.READER_WHEEL_THUMB_SCALE_PCT = 100;
    }
    if (config.value.READER_WHEEL_THUMB_WIDTH === undefined || config.value.READER_WHEEL_THUMB_WIDTH === null || config.value.READER_WHEEL_THUMB_WIDTH === "") {
      config.value.READER_WHEEL_THUMB_WIDTH = 74;
    }
    if (config.value.READER_WHEEL_THUMB_HEIGHT === undefined || config.value.READER_WHEEL_THUMB_HEIGHT === null || config.value.READER_WHEEL_THUMB_HEIGHT === "") {
      config.value.READER_WHEEL_THUMB_HEIGHT = 96;
    }
    if (config.value.REC_SHOW_PAGE_COUNT === undefined) config.value.REC_SHOW_PAGE_COUNT = true;
    if (config.value.SIGLIP_WORKER_ENABLED === undefined) config.value.SIGLIP_WORKER_ENABLED = true;
    if (config.value.READER_PRELOAD_COUNT === undefined || config.value.READER_PRELOAD_COUNT === null || config.value.READER_PRELOAD_COUNT === "") {
      config.value.READER_PRELOAD_COUNT = 10;
    }
    if (typeof Intl.supportedValuesOf === "function") {
      try {
        const zones = Intl.supportedValuesOf("timeZone");
        if (Array.isArray(zones) && zones.length) timezoneOptions.value = zones;
      } catch {
        // ignore
      }
    }
    // Everything above -- the server's values *and* every client-side fallback --
    // is now "what the server has". Taking the snapshot here is what stops the
    // auto-saver from pushing all of those fallbacks the moment the app opens.
    _savedConfig = { ..._desiredConfigValues() };
  }

  async function refreshDbHealth() {
    dbHealthLoading.value = true;
    try {
      const res = await getDbHealth();
      dbHealth.value = { ...(dbHealth.value || {}), ...((res && res.database) || {}) };
    } catch (e) {
      const detail = String(e?.response?.data?.detail || e?.message || e || "unknown error");
      dbHealth.value = { ...(dbHealth.value || {}), ok: false, error: detail };
      notify(detail, "warning");
    } finally {
      dbHealthLoading.value = false;
    }
  }

  // What an `updateConfig` payload would look like right now. `REC_TAG_ZERO_LIST`
  // is edited as a chips array but stored as CSV, so it is joined here the same way
  // the old whole-object save did.
  function _desiredConfigValues() {
    return { ...config.value, REC_TAG_ZERO_LIST: recTagZeroList.value.join(",") };
  }

  // "Did this actually change?" has to be asked per schema type: the backend keeps
  // everything as text (`config_values.normalize_value` always returns `str`), so a
  // `v-select` handing back the number 20 for an int key, or `false` against the
  // stored `"0"`, must not read as a change. A raw `!==` would report both.
  function _configValueChanged(key, a, b) {
    const type = String(schema.value?.[key]?.type || "");
    if (type === "bool") return parseBool(a, false) !== parseBool(b, false);
    if (type === "int" || type === "float") {
      const na = Number(a);
      const nb = Number(b);
      if (Number.isFinite(na) && Number.isFinite(nb)) return na !== nb;
    }
    return String(a ?? "") !== String(b ?? "");
  }

  function _dirtyConfigKeys() {
    const desired = _desiredConfigValues();
    const base = _savedConfig || {};
    const keys = new Set([...Object.keys(desired), ...Object.keys(base)]);
    const dirty = [];
    keys.forEach((key) => {
      if (_configValueChanged(key, desired[key], base[key])) dirty.push(key);
    });
    return { desired, dirty };
  }

  function _markConfigSaved(keys, desired) {
    const next = { ...(_savedConfig || {}) };
    keys.forEach((key) => { next[key] = desired[key]; });
    _savedConfig = next;
  }

  function _scheduleConfigSaveIdle() {
    if (_autoSaveIdleTimer) clearTimeout(_autoSaveIdleTimer);
    _autoSaveIdleTimer = setTimeout(() => {
      _autoSaveIdleTimer = null;
      if (configSaveState.value === "saved") configSaveState.value = "idle";
    }, AUTO_SAVE_IDLE_MS);
  }

  /**
   * Push every key that changed since the last acknowledged save, once.
   *
   * A call made while a request is in flight does not start a second request: it
   * raises a flag and the in-flight one runs again afterwards. Without that a
   * slider drag would open a dozen overlapping PUTs that can land out of order.
   */
  async function flushConfig() {
    if (_autoSaveInFlight) {
      _autoSaveAgain = true;
      return _autoSaveInFlight;
    }
    const { desired, dirty } = _dirtyConfigKeys();
    if (!dirty.length) {
      if (configSaveState.value === "pending") configSaveState.value = "idle";
      return true;
    }
    const payload = {};
    dirty.forEach((key) => { payload[key] = desired[key]; });
    configSaveState.value = "saving";
    configSaveError.value = "";
    _autoSaveInFlight = (async () => {
      try {
        const res = await updateConfig(payload);
        // No database reachable yet (the setup screen, before the wizard has a
        // working DSN): the JSON copy is the whole truth for now. Treating that
        // as a failure put "save failed" in front of a brand-new user, on the
        // first screen, for typing into a form that had nowhere to be stored.
        if (res && res.db_pending) {
          _markConfigSaved(dirty, desired);
          configSaveState.value = "saved";
          _scheduleConfigSaveIdle();
          return true;
        }
        if (res && res.saved_db === false) {
          configSaveState.value = "error";
          configSaveError.value = String(res.db_error || "n/a");
          notify(t("settings.autosave.failed", { reason: configSaveError.value }), "warning");
          return false;
        }
        // Reconcile only the keys we sent, and from the values we *sent*: anything
        // the user changed while the request was in flight stays dirty and goes out
        // with the next flush.
        _markConfigSaved(dirty, desired);
        configSaveState.value = "saved";
        _scheduleConfigSaveIdle();
        return true;
      } catch (e) {
        configSaveState.value = "error";
        configSaveError.value = String(e?.response?.data?.detail || e?.message || e);
        notify(configSaveError.value, "warning");
        return false;
      } finally {
        _autoSaveInFlight = null;
        if (_autoSaveAgain) {
          _autoSaveAgain = false;
          flushConfig().catch(() => null);
        }
      }
    })();
    return _autoSaveInFlight;
  }

  function scheduleConfigAutoSave() {
    if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
    if (configSaveState.value !== "saving") configSaveState.value = "pending";
    _autoSaveTimer = setTimeout(() => {
      _autoSaveTimer = null;
      flushConfig().catch(() => null);
    }, AUTO_SAVE_DEBOUNCE_MS);
  }

  /**
   * Flush any pending change right now.
   *
   * Kept for the few flows that must have the write landed before they continue
   * (the language/theme switch in the top bar, the setup wizard). It no longer
   * reloads the config: the edited values are already the truth, and a re-read
   * would drop whatever is half-typed on another tab.
   */
  async function saveConfig() {
    if (_autoSaveTimer) {
      clearTimeout(_autoSaveTimer);
      _autoSaveTimer = null;
    }
    return flushConfig();
  }

  // One watcher for every settings surface: they all bind this object, and the
  // reader writes into it through computed setters rather than through this store.
  watch(config, () => { scheduleConfigAutoSave(); }, { deep: true });

  async function downloadAppConfigBackupAction() {
    try {
      const blob = await downloadAppConfigBackup();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "app_config.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      notify(t("settings.app_config_backup.downloaded"), "success");
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function onAppConfigRestoreChange(event) {
    const file = event?.target?.files?.[0];
    if (!file) return;
    try {
      const res = await restoreAppConfigBackup(file);
      notify(String(res?.note || t("settings.app_config_backup.restored")), "success");
      await loadConfigData();
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    } finally {
      if (appConfigRestoreRef.value) appConfigRestoreRef.value.value = "";
    }
  }

  async function reloadIngestModels() {
    const base = String(config.value.INGEST_API_BASE || "").trim();
    if (!base) {
      ingestModelOptions.value = [];
      return;
    }
    try {
      const res = await getProviderModels(base, String(config.value.INGEST_API_KEY || "").trim());
      const next = Array.isArray(res?.models) ? res.models : [];
      ingestModelOptions.value = [...next];
      if (!res?.ok) {
        const reason = String(res?.error || "provider unavailable");
        notify(reason, "warning");
      }
    } catch (e) {
      ingestModelOptions.value = [];
      notify(String(e?.response?.data?.detail || e?.message || e), "warning");
    }
  }

  async function reloadLlmModels() {
    const base = String(config.value.LLM_API_BASE || "").trim();
    if (!base) {
      llmModelOptions.value = [];
      return;
    }
    try {
      const res = await getProviderModels(base, String(config.value.LLM_API_KEY || "").trim());
      const next = Array.isArray(res?.models) ? res.models : [];
      llmModelOptions.value = [...next];
      if (!res?.ok) {
        const reason = String(res?.error || "provider unavailable");
        notify(reason, "warning");
      }
    } catch (e) {
      llmModelOptions.value = [];
      notify(String(e?.response?.data?.detail || e?.message || e), "warning");
    }
  }

  async function loadTranslationStatus() {
    translationStatus.value = await getTranslationStatus();
  }

  async function onTranslationUploadChange(event) {
    const file = event?.target?.files?.[0];
    if (!file) return;
    try {
      await uploadTranslationFile(file);
      notify(t("settings.translation.uploaded"), "success");
      await loadTranslationStatus();
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    } finally {
      if (translationUploadRef.value) translationUploadRef.value.value = "";
    }
  }

  async function loadModelStatus() {
    const res = await getModelStatus();
    if (res && typeof res === "object" && res.model) {
      modelStatus.value = res.model || modelStatus.value;
      if (res.download && typeof res.download === "object") {
        siglipDownload.value = { ...siglipDownload.value, ...res.download };
      }
      return;
    }
    modelStatus.value = res || modelStatus.value;
  }

  async function pollSiglipTask(taskId) {
    if (!taskId) return;
    if (siglipPollTimer) clearInterval(siglipPollTimer);
    siglipPollTimer = setInterval(async () => {
      try {
        const res = await getSiglipDownloadStatus(taskId);
        const st = res.status || {};
        siglipDownload.value = { ...siglipDownload.value, ...st };
        modelStatus.value = res.model || modelStatus.value;
        if (st.status === "done" || st.status === "failed") {
          clearInterval(siglipPollTimer);
          siglipPollTimer = null;
          if (st.status === "failed") {
            notify(String(st.error || "download failed"), "warning");
          }
          if (st.status === "done") {
            setTimeout(() => {
              if (String(siglipDownload.value.task_id || "") !== String(taskId)) return;
              if (String(siglipDownload.value.status || "") !== "done") return;
              siglipDownload.value = {
                ...siglipDownload.value,
                status: "",
                stage: "",
                error: "",
                logs: [],
              };
            }, 1200);
          }
        }
      } catch {
        // ignore
      }
    }, 1800);
  }

  async function downloadSiglipAction() {
    try {
      const res = await downloadSiglip({ model_id: String(config.value.SIGLIP_MODEL || "google/siglip-so400m-patch14-384") });
      const tid = String(res.task_id || "");
      if (tid) {
        siglipDownload.value = { ...(res.status || {}), task_id: tid };
        await pollSiglipTask(tid);
      }
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function clearRuntimeDepsAction() {
    try {
      const res = await clearRuntimeDeps();
      if (res?.skipped) {
        notify(t("settings.model.runtime_deps_empty"), "info");
      } else {
        notify(t("settings.model.runtime_deps_cleared", { mb: res.freed_mb ?? 0 }), "success");
      }
      await loadModelStatus();
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function clearSiglipAction() {
    try {
      const res = await clearSiglip();
      if (res?.skipped) {
        notify(t("settings.model.siglip_empty"), "info");
      } else {
        notify(t("settings.model.siglip_cleared", { mb: res.freed_mb ?? 0 }), "success");
      }
      await loadModelStatus();
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function clearWorksDuplicatesAction() {
    try {
      const res = await clearWorksDuplicates();
      notify(t("settings.data_clean.dedup_works_done", { n: Number(res.deleted || 0) }), "success");
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function clearReadEventsAction() {
    try {
      const res = await clearReadEvents();
      notify(t("settings.data_clean.clear_read_events_done", { n: Number(res.deleted || 0) }), "success");
    } catch (e) {
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function toggleSiglipWorkerEnabled(enabled) {
    const next = !!enabled;
    const prev = !!config.value.SIGLIP_WORKER_ENABLED;
    config.value.SIGLIP_WORKER_ENABLED = next;
    try {
      if (next) {
        await enableVisualTask();
      } else {
        await disableVisualTask();
      }
      await saveConfig();
      notify(t(next ? "settings.siglip_worker.enabled_toast" : "settings.siglip_worker.disabled_toast"), next ? "success" : "warning");
    } catch (e) {
      config.value.SIGLIP_WORKER_ENABLED = prev;
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }


  function openSetupWizardManual() {
    appStore.openSetupWizardManual();
  }

  async function updateAccountUsername() {
    await appStore.updateAccountUsername();
  }

  async function updateAccountPassword() {
    await appStore.updateAccountPassword();
  }

  async function deleteAccountNow() {
    await appStore.deleteAccountNow();
  }

  watch(() => config.value.SEARCH_TEXT_WEIGHT, () => normalizeSearchWeights("SEARCH_TEXT_WEIGHT", "SEARCH_VISUAL_WEIGHT", "SEARCH_TEXT_WEIGHT"));
  watch(() => config.value.SEARCH_VISUAL_WEIGHT, () => normalizeSearchWeights("SEARCH_TEXT_WEIGHT", "SEARCH_VISUAL_WEIGHT", "SEARCH_VISUAL_WEIGHT"));
  watch(() => config.value.SEARCH_MIXED_TEXT_WEIGHT, () => normalizeSearchWeights("SEARCH_MIXED_TEXT_WEIGHT", "SEARCH_MIXED_VISUAL_WEIGHT", "SEARCH_MIXED_TEXT_WEIGHT"));
  watch(() => config.value.SEARCH_MIXED_VISUAL_WEIGHT, () => normalizeSearchWeights("SEARCH_MIXED_TEXT_WEIGHT", "SEARCH_MIXED_VISUAL_WEIGHT", "SEARCH_MIXED_VISUAL_WEIGHT"));
  watch(() => config.value.SEARCH_WORK_COVER_WEIGHT, () => normalizeSearchWeights("SEARCH_WORK_COVER_WEIGHT", "SEARCH_WORK_PAGE_WEIGHT", "SEARCH_WORK_COVER_WEIGHT"));
  watch(() => config.value.SEARCH_WORK_PAGE_WEIGHT, () => normalizeSearchWeights("SEARCH_WORK_COVER_WEIGHT", "SEARCH_WORK_PAGE_WEIGHT", "SEARCH_WORK_PAGE_WEIGHT"));
  watch(() => config.value.SEARCH_WEIGHT_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_VISUAL"));
  watch(() => config.value.SEARCH_WEIGHT_PAGE_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_PAGE_VISUAL"));
  watch(() => config.value.SEARCH_WEIGHT_DESC, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_DESC"));
  watch(() => config.value.SEARCH_WEIGHT_TEXT, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_TEXT"));
  watch(() => config.value.SEARCH_WEIGHT_PLOT_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_PLOT_VISUAL", ["SEARCH_WEIGHT_PLOT_VISUAL", "SEARCH_WEIGHT_PLOT_PAGE_VISUAL", "SEARCH_WEIGHT_PLOT_DESC", "SEARCH_WEIGHT_PLOT_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_PLOT_PAGE_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_PLOT_PAGE_VISUAL", ["SEARCH_WEIGHT_PLOT_VISUAL", "SEARCH_WEIGHT_PLOT_PAGE_VISUAL", "SEARCH_WEIGHT_PLOT_DESC", "SEARCH_WEIGHT_PLOT_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_PLOT_DESC, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_PLOT_DESC", ["SEARCH_WEIGHT_PLOT_VISUAL", "SEARCH_WEIGHT_PLOT_PAGE_VISUAL", "SEARCH_WEIGHT_PLOT_DESC", "SEARCH_WEIGHT_PLOT_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_PLOT_TEXT, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_PLOT_TEXT", ["SEARCH_WEIGHT_PLOT_VISUAL", "SEARCH_WEIGHT_PLOT_PAGE_VISUAL", "SEARCH_WEIGHT_PLOT_DESC", "SEARCH_WEIGHT_PLOT_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_MIXED_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_MIXED_VISUAL", ["SEARCH_WEIGHT_MIXED_VISUAL", "SEARCH_WEIGHT_MIXED_PAGE_VISUAL", "SEARCH_WEIGHT_MIXED_DESC", "SEARCH_WEIGHT_MIXED_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_MIXED_PAGE_VISUAL, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_MIXED_PAGE_VISUAL", ["SEARCH_WEIGHT_MIXED_VISUAL", "SEARCH_WEIGHT_MIXED_PAGE_VISUAL", "SEARCH_WEIGHT_MIXED_DESC", "SEARCH_WEIGHT_MIXED_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_MIXED_DESC, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_MIXED_DESC", ["SEARCH_WEIGHT_MIXED_VISUAL", "SEARCH_WEIGHT_MIXED_PAGE_VISUAL", "SEARCH_WEIGHT_MIXED_DESC", "SEARCH_WEIGHT_MIXED_TEXT"]));
  watch(() => config.value.SEARCH_WEIGHT_MIXED_TEXT, () => normalizeSearchChannelWeights("SEARCH_WEIGHT_MIXED_TEXT", ["SEARCH_WEIGHT_MIXED_VISUAL", "SEARCH_WEIGHT_MIXED_PAGE_VISUAL", "SEARCH_WEIGHT_MIXED_DESC", "SEARCH_WEIGHT_MIXED_TEXT"]));
  watch(() => config.value.REC_TAG_WEIGHT, () => normalizeRecommendWeights("REC_TAG_WEIGHT"));
  watch(() => config.value.REC_VISUAL_WEIGHT, () => normalizeRecommendWeights("REC_VISUAL_WEIGHT"));
  watch(() => config.value.REC_FEEDBACK_WEIGHT, () => normalizeRecommendWeights("REC_FEEDBACK_WEIGHT"));
  watch(() => config.value.REC_TEMPERATURE, () => {
    const v = Number(config.value.REC_TEMPERATURE ?? 0.3);
    config.value.REC_TEMPERATURE = Number((Number.isFinite(v) ? Math.max(0.05, Math.min(2.0, v)) : 0.3).toFixed(2));
  });
  watch(() => config.value.REC_PROFILE_WEIGHT, () => {
    const v = Number(config.value.REC_PROFILE_WEIGHT ?? 0.18);
    config.value.REC_PROFILE_WEIGHT = Number((Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0.18).toFixed(4));
  });
  watch(() => config.value.REC_TOUCH_PENALTY_PCT, () => {
    const v = Number(config.value.REC_TOUCH_PENALTY_PCT ?? 35);
    config.value.REC_TOUCH_PENALTY_PCT = Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : 35;
  });
  watch(() => config.value.REC_IMPRESSION_PENALTY_PCT, () => {
    const v = Number(config.value.REC_IMPRESSION_PENALTY_PCT ?? 3);
    config.value.REC_IMPRESSION_PENALTY_PCT = Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : 3;
  });
  watch(() => config.value.READER_PRELOAD_COUNT, () => {
    const v = Number(config.value.READER_PRELOAD_COUNT ?? 10);
    config.value.READER_PRELOAD_COUNT = Number.isFinite(v) ? Math.max(10, Math.min(20, Math.round(v))) : 10;
  });
  watch(() => config.value.READER_IMAGE_QUALITY_MODE, () => {
    const mode = String(config.value.READER_IMAGE_QUALITY_MODE || "high").trim().toLowerCase();
    config.value.READER_IMAGE_QUALITY_MODE = ["low", "mid", "high", "original"].includes(mode) ? mode : "high";
  });
  watch(() => config.value.LOCAL_THUMB_PRESET, () => {
    const preset = String(config.value.LOCAL_THUMB_PRESET || "mid").trim().toLowerCase();
    config.value.LOCAL_THUMB_PRESET = ["low", "mid", "high", "ultra", "300", "600", "900", "1200"].includes(preset) ? preset : "mid";
  });
  watch(() => config.value.READER_WHEEL_CURVE, () => {
    const v = Number(config.value.READER_WHEEL_CURVE ?? 55);
    config.value.READER_WHEEL_CURVE = Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : 55;
  });
  watch(() => config.value.READER_WHEEL_RANGE, () => {
    const v = Number(config.value.READER_WHEEL_RANGE ?? 4);
    config.value.READER_WHEEL_RANGE = Number.isFinite(v) ? Math.max(2, Math.min(20, Math.round(v))) : 4;
  });
  watch(() => config.value.READER_WHEEL_EXTENT_PCT, () => {
    const v = Number(config.value.READER_WHEEL_EXTENT_PCT ?? 100);
    config.value.READER_WHEEL_EXTENT_PCT = Number.isFinite(v) ? Math.max(60, Math.min(220, Math.round(v))) : 100;
  });
  watch(() => config.value.READER_WHEEL_THUMB_SCALE_PCT, () => {
    const v = Number(config.value.READER_WHEEL_THUMB_SCALE_PCT ?? 100);
    config.value.READER_WHEEL_THUMB_SCALE_PCT = Number.isFinite(v) ? Math.max(60, Math.min(220, Math.round(v))) : 100;
  });
  watch(() => config.value.READER_WHEEL_THUMB_WIDTH, () => {
    const v = Number(config.value.READER_WHEEL_THUMB_WIDTH ?? 74);
    config.value.READER_WHEEL_THUMB_WIDTH = Number.isFinite(v) ? Math.max(44, Math.min(220, Math.round(v))) : 74;
  });
  watch(() => config.value.READER_WHEEL_THUMB_HEIGHT, () => {
    const v = Number(config.value.READER_WHEEL_THUMB_HEIGHT ?? 96);
    config.value.READER_WHEEL_THUMB_HEIGHT = Number.isFinite(v) ? Math.max(56, Math.min(280, Math.round(v))) : 96;
  });
  watch(() => config.value.DOWNLOAD_MAX_CONCURRENCY, () => {
    const v = Number(config.value.DOWNLOAD_MAX_CONCURRENCY ?? 1);
    config.value.DOWNLOAD_MAX_CONCURRENCY = Number.isFinite(v) ? Math.max(1, Math.min(6, Math.round(v))) : 1;
  });

  watch(() => newRecTag.value, () => {
    loadRecTagSuggestions().catch(() => null);
  });

  return {
    config,
    schema,
    configMeta,
    secretState,
    settingsTab,
    llmModelOptions,
    ingestModelOptions,
    appConfigRestoreRef,
    translationStatus,
    translationUploadRef,
    modelStatus,
    dbHealth,
    dbHealthLoading,
    siglipDownload,
    recTagZeroList,
    newRecTag,
    recTagSuggestions,
    builtinCategoryDefs,
    customCategoryDefs,
    pinnedCategoryKeys,
    localCategoryDefs,
    pinnedLocalCategoryDefs,
    builtinNamespaceDefs,
    customNamespaceDefs,
    themeOptions,
    themeModeOptions,
    timezoneOptions,
    llmReady,
    limitedModeMessages,
    health,
    accountForm,
    init,
    t,
    notify,
    labelFor,
    secretHint,
    getGalleryTitle,
    parseCsv,
    addRecTag,
    removeRecTag,
    loadRecTagSuggestions,
    normalizeSearchWeights,
    normalizeSearchChannelWeights,
    normalizeRecommendWeights,
    resetSearchWeightPresets,
    resetRecommendPreset,
    loadConfigData,
    saveConfig,
    flushConfig,
    configSaveState,
    configSaveError,
    downloadAppConfigBackupAction,
    onAppConfigRestoreChange,
    reloadIngestModels,
    reloadLlmModels,
    refreshDbHealth,
    loadTranslationStatus,
    onTranslationUploadChange,
    loadModelStatus,
    pollSiglipTask,
    downloadSiglipAction,
    clearRuntimeDepsAction,
    clearSiglipAction,
    clearWorksDuplicatesAction,
    clearReadEventsAction,
    toggleSiglipWorkerEnabled,
    openSetupWizardManual,
    updateAccountUsername,
    updateAccountPassword,
    deleteAccountNow,
  };
});
