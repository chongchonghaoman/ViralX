(() => {
  "use strict";

  const STORAGE_KEY = "viralx.cloud.session.v1";
  const ALLOWED_FIELDS = [
    "analysis_mode",
    "min_likes",
    "rapidapi_key",
    "tk_note_asr_backend",
    "tk_note_language",
    "tk_note_proxy",
    "tk_note_timeout",
    "model_provider",
    "model_protocol",
    "model_api_key",
    "model_base_url",
    "model_name",
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
    tk_note_language: "X-ViralX-TK-Language",
    tk_note_timeout: "X-ViralX-TK-Timeout",
    model_provider: "X-ViralX-Model-Provider",
    model_protocol: "X-ViralX-Model-Protocol",
    model_api_key: "X-ViralX-Model-Key",
    model_base_url: "X-ViralX-Model-Base-URL",
    model_name: "X-ViralX-Model-Name",
    gemini_api_key: "X-ViralX-Gemini-Key",
    gemini_model: "X-ViralX-Gemini-Model",
    openrouter_api_key: "X-ViralX-OpenRouter-Key",
    openrouter_model: "X-ViralX-OpenRouter-Model",
    minimax_api_key: "X-ViralX-MiniMax-Key",
    minimax_model: "X-ViralX-MiniMax-Model",
  };

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

  function headers() {
    const result = {};
    const value = read();
    Object.entries(HEADER_MAP).forEach(([field, header]) => {
      if (value[field] !== undefined && value[field] !== "") {
        result[header] = String(value[field]);
      }
    });
    return result;
  }

  function apiFetch(url, options = {}) {
    const requestHeaders = new Headers(options.headers || {});
    Object.entries(headers()).forEach(([name, value]) => requestHeaders.set(name, value));
    const hosted = document.documentElement.dataset.deployment === "edgeone";
    const useConnector = hosted
      && (read().analysis_mode || "libtv") === "libtv"
      && new URL(url, window.location.origin).pathname === "/api/analyze"
      && window.ViralXConnector;
    if (useConnector) {
      return window.ViralXConnector.request("/connector/v1/analyze", {
        ...options,
        headers: requestHeaders,
      });
    }
    return window.fetch(url, { ...options, headers: requestHeaders });
  }

  window.ViralXCloudConfig = { read, write, clear, headers, apiFetch };
})();
