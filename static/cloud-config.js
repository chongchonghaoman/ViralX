(() => {
  "use strict";

  const STORAGE_KEY = "viralx.cloud.session.v1";
  // EdgeOne Functions may cold-start before relaying to the home Worker.
  // Keep the UI in its explicit connecting state long enough for that first hop.
  const HEALTH_TIMEOUT_MS = 15000;
  const ALLOWED_FIELDS = [
    "analysis_mode",
    "min_likes",
    "rapidapi_key",
    "tk_note_asr_backend",
    "tk_note_cookies_from_browser",
    "tk_note_language",
    "tk_note_proxy",
    "tk_note_timeout",
    "model_provider",
    "model_protocol",
    "model_api_key",
    "model_base_url",
    "model_name",
    "shot_engine",
    "shot_model_source",
    "shot_model_api_key",
    "shot_model_base_url",
    "shot_model_name",
    "shot_scene_threshold",
    "gemini_api_key",
    "gemini_model",
    "openrouter_api_key",
    "openrouter_model",
    "minimax_api_key",
    "minimax_base_url",
    "minimax_model",
    "search_keywords",
  ];

  const HEADER_MAP = {
    analysis_mode: "X-ViralX-Analysis-Mode",
    min_likes: "X-ViralX-Min-Likes",
    rapidapi_key: "X-ViralX-RapidAPI-Key",
    tk_note_asr_backend: "X-ViralX-TK-ASR",
    tk_note_cookies_from_browser: "X-ViralX-TK-Cookies-Browser",
    tk_note_language: "X-ViralX-TK-Language",
    tk_note_proxy: "X-ViralX-TK-Proxy",
    tk_note_timeout: "X-ViralX-TK-Timeout",
    model_provider: "X-ViralX-Model-Provider",
    model_protocol: "X-ViralX-Model-Protocol",
    model_api_key: "X-ViralX-Model-Key",
    model_base_url: "X-ViralX-Model-Base-URL",
    model_name: "X-ViralX-Model-Name",
    shot_engine: "X-ViralX-Shot-Engine",
    shot_model_source: "X-ViralX-Shot-Model-Source",
    shot_model_api_key: "X-ViralX-Shot-Model-Key",
    shot_model_base_url: "X-ViralX-Shot-Model-Base-URL",
    shot_model_name: "X-ViralX-Shot-Model-Name",
    shot_scene_threshold: "X-ViralX-Shot-Threshold",
    gemini_api_key: "X-ViralX-Gemini-Key",
    gemini_model: "X-ViralX-Gemini-Model",
    openrouter_api_key: "X-ViralX-OpenRouter-Key",
    openrouter_model: "X-ViralX-OpenRouter-Model",
    minimax_api_key: "X-ViralX-MiniMax-Key",
    minimax_model: "X-ViralX-MiniMax-Model",
  };

  const REMOTE_WORKER_HEADER_FIELDS = new Set([
    "min_likes",
    "rapidapi_key",
    "model_provider",
    "model_protocol",
    "model_api_key",
    "model_base_url",
    "model_name",
    "shot_scene_threshold",
  ]);

  const REMOTE_WORKER_PATHS = new Set([
    "/api/health",
    "/api/analyze",
    "/api/keywords",
    "/api/generate_variants",
  ]);

  function clean(input) {
    const result = {};
    ALLOWED_FIELDS.forEach((field) => {
      if (!(field in (input || {}))) return;
      if (field === "search_keywords") {
        result[field] = Array.isArray(input[field])
          ? input[field].map((value) => String(value).trim()).filter(Boolean).slice(0, 20)
          : [];
        return;
      }
      result[field] = typeof input[field] === "number"
        ? input[field]
        : String(input[field] ?? "").trim();
    });
    return result;
  }

  function read() {
    try {
      return clean(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "{}"));
    } catch (_) {
      return {};
    }
  }

  function write(value) {
    const safeValue = clean(value);
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(safeValue));
    return safeValue;
  }

  function clear() {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }

  function headers({ remoteWorker = false } = {}) {
    const result = {};
    const value = read();
    Object.entries(HEADER_MAP).forEach(([field, header]) => {
      if (remoteWorker && !REMOTE_WORKER_HEADER_FIELDS.has(field)) return;
      if (value[field] !== undefined && value[field] !== "") {
        result[header] = String(value[field]);
      }
    });
    return result;
  }

  function runtime() {
    const source = window.ViralXRuntimeConfig || {};
    return {
      mode: String(source.mode || "same-origin"),
      apiBaseUrl: String(source.apiBaseUrl || "").trim().replace(/\/+$/, ""),
      allowSessionOverrides: source.allowSessionOverrides !== false,
    };
  }

  function workerUrl(url) {
    const target = new URL(url, window.location.origin);
    const config = runtime();
    const hosted = document.documentElement.dataset.deployment === "edgeone";
    const workerRoute = hosted
      && ["remote-worker", "same-origin-worker"].includes(config.mode)
      && REMOTE_WORKER_PATHS.has(target.pathname);
    if (!workerRoute || config.mode === "same-origin-worker") {
      return target.origin === window.location.origin ? `${target.pathname}${target.search}` : target.href;
    }
    if (!config.apiBaseUrl) throw new Error("实时分析服务尚未配置公网地址");
    return `${config.apiBaseUrl}${target.pathname}${target.search}`;
  }

  function apiFetch(url, options = {}) {
    const route = new URL(url, window.location.origin).pathname;
    const config = runtime();
    const remoteWorker = document.documentElement.dataset.deployment === "edgeone"
      && ["remote-worker", "same-origin-worker"].includes(config.mode)
      && REMOTE_WORKER_PATHS.has(route);
    const requestHeaders = new Headers(options.headers || {});
    if (runtime().allowSessionOverrides) {
      Object.entries(headers({ remoteWorker })).forEach(([name, value]) => requestHeaders.set(name, value));
    }
    let target;
    try {
      target = workerUrl(url);
    } catch (error) {
      return Promise.reject(error);
    }
    const timeoutMs = route === "/api/health" ? HEALTH_TIMEOUT_MS : 0;
    if (!timeoutMs || options.signal) {
      return window.fetch(target, { ...options, headers: requestHeaders });
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    return window.fetch(target, { ...options, headers: requestHeaders, signal: controller.signal })
      .finally(() => window.clearTimeout(timeout));
  }

  window.ViralXCloudConfig = { read, write, clear, headers, runtime, workerUrl, apiFetch };
})();
