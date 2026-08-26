(() => {
  "use strict";

  const PROVIDERS = {
    openai: { name: "OpenAI", protocol: "openai", baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini", vision: true, keyPlaceholder: "OpenAI API Key" },
    anthropic: { name: "Anthropic Claude", protocol: "anthropic", baseUrl: "https://api.anthropic.com", model: "claude-sonnet-5", vision: true, keyPlaceholder: "Anthropic API Key" },
    gemini: { name: "Google Gemini", protocol: "gemini", baseUrl: "https://generativelanguage.googleapis.com", model: "gemini-3.7-flash", vision: true, keyPlaceholder: "Google AI Studio API Key" },
    deepseek: { name: "DeepSeek", protocol: "openai", baseUrl: "https://api.deepseek.com", model: "deepseek-v4-flash", vision: false, keyPlaceholder: "DeepSeek API Key" },
    openrouter: { name: "OpenRouter", protocol: "openai", baseUrl: "https://openrouter.ai/api/v1", model: "openrouter/auto", vision: true, keyPlaceholder: "OpenRouter API Key" },
    custom: { name: "自定义 API", protocol: "openai", baseUrl: "", model: "", vision: true, keyPlaceholder: "自定义服务的 API Key" },
  };

  const DEFAULTS = {
    rapidapi_key: "", analysis_mode: "pipeline", libtv_concurrency: 1, tk_note_asr_backend: "auto",
    tk_note_language: "auto", tk_note_cookies_from_browser: "", tk_note_proxy: "",
    tk_note_timeout: 90, video_cache_dir: "./video_cache", model_provider: "openai",
    model_protocol: "openai", model_api_key: "", model_base_url: "https://api.openai.com/v1",
    model_name: "gpt-4.1-mini", gemini_api_key: "", gemini_model: "gemini-3.7-flash", openrouter_api_key: "",
    shot_engine: "auto", shot_model_source: "inherit", shot_model_api_key: "",
    shot_model_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    shot_model_name: "qwen-vl-max", shot_scene_threshold: 27,
    openrouter_model: "openrouter/auto",
    minimax_api_key: "", minimax_base_url: "https://api.minimaxi.com/anthropic",
    minimax_model: "MiniMax-M2.7", min_likes: 5000, output_dir: "./data",
    search_keywords: [],
  };

  let settings = {};
  let runtimeMode = "local";
  let activeProvider = "openai";
  let providerDrafts = {};
  let libtvPollTimer = 0;
  let connectorState = { available: false, paired: false, libtv: null, shotloomCore: null };
  const byId = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const apiFetch = (url, options) => window.ViralXCloudConfig
    ? window.ViralXCloudConfig.apiFetch(url, options)
    : window.fetch(url, options);

  class SettingsValidationError extends Error {
    constructor(fieldId, message) {
      super(message);
      this.name = "SettingsValidationError";
      this.fieldId = fieldId;
    }
  }

  function setValue(id, value) {
    const field = byId(id);
    if (field) field.value = value ?? "";
  }

  function migrateLegacySettings(input) {
    const migrated = { ...(input || {}) };
    const legacyMode = String(migrated.analysis_mode || "").toLowerCase();
    if (["gemini", "openrouter", "minimax"].includes(legacyMode)) {
      const legacy = {
        gemini: { provider: "gemini", protocol: "gemini", key: migrated.gemini_api_key, baseUrl: PROVIDERS.gemini.baseUrl, model: migrated.gemini_model },
        openrouter: { provider: "openrouter", protocol: "openai", key: migrated.openrouter_api_key, baseUrl: PROVIDERS.openrouter.baseUrl, model: migrated.openrouter_model },
        minimax: { provider: "custom", protocol: "anthropic", key: migrated.minimax_api_key, baseUrl: migrated.minimax_base_url, model: migrated.minimax_model },
      }[legacyMode];
      migrated.model_provider = legacy.provider;
      migrated.model_protocol = legacy.protocol;
      migrated.model_api_key ||= legacy.key || "";
      migrated.model_base_url ||= legacy.baseUrl || "";
      migrated.model_name ||= legacy.model || "";
    }
    migrated.analysis_mode = "pipeline";
    return migrated;
  }

  function providerDraft() {
    return {
      apiKey: byId("model_api_key")?.value.trim() || "",
      model: byId("model_name")?.value.trim() || "",
      baseUrl: byId("model_base_url")?.value.trim() || "",
      protocol: byId("model_protocol")?.value || "openai",
    };
  }

  function renderProvider(provider) {
    const preset = PROVIDERS[provider] || PROVIDERS.openai;
    const custom = provider === "custom";
    byId("provider-name").textContent = preset.name;
    byId("provider-endpoint").textContent = custom
      ? (byId("model_base_url").value.trim() || "等待填写 Base URL")
      : preset.baseUrl;
    byId("model_api_key").placeholder = preset.keyPlaceholder;
    document.querySelectorAll("[data-custom-model]").forEach((field) => {
      field.hidden = !custom;
      field.querySelectorAll("input, select").forEach((control) => { control.disabled = !custom; });
    });
  }

  function syncAnalysisMode() {
    setValue("analysis_mode", "pipeline");
    document.querySelectorAll("[data-mode-details]").forEach((details) => {
      details.open = true;
      details.closest(".settings-section")?.classList.add("is-active");
    });
  }

  function renderShotEngine() {
    const engine = document.querySelector('input[name="shot_engine"]:checked')?.value || "auto";
    const source = byId("shot_model_source")?.value || "inherit";
    const shotloomRelevant = ["auto", "shotloom"].includes(engine);
    const libtvRelevant = ["auto", "libtv"].includes(engine);
    const shotModelDisclosure = byId("shot-model-disclosure");
    const libtvDisclosure = byId("libtv-fallback-disclosure");
    if (shotModelDisclosure) shotModelDisclosure.hidden = !shotloomRelevant;
    if (libtvDisclosure) {
      libtvDisclosure.hidden = !libtvRelevant;
      if (engine === "libtv") libtvDisclosure.open = true;
    }
    document.querySelectorAll("[data-shot-model-field]").forEach((field) => {
      const credentialNeeded = source !== "inherit";
      field.hidden = !credentialNeeded;
      field.querySelectorAll("input, select").forEach((control) => { control.disabled = !credentialNeeded; });
    });
    if (source === "qwen") {
      if (!byId("shot_model_base_url").value.trim()) setValue("shot_model_base_url", DEFAULTS.shot_model_base_url);
      if (!byId("shot_model_name").value.trim()) setValue("shot_model_name", DEFAULTS.shot_model_name);
    }
    const dependency = connectorState.shotloomCore;
    const summary = byId("shotloom-summary-state");
    if (summary) {
      summary.textContent = dependency?.installed === false
        ? "依赖未安装"
        : source === "inherit" ? "复用最终视觉模型" : "独立视觉模型";
    }
  }

  function selectProvider(provider, { restore = true, userInitiated = false } = {}) {
    const next = PROVIDERS[provider] ? provider : "openai";
    if (restore && activeProvider) providerDrafts[activeProvider] = providerDraft();
    activeProvider = next;
    document.querySelectorAll('input[name="model_provider"]').forEach((radio) => {
      radio.checked = radio.value === next;
    });
    const preset = PROVIDERS[next];
    const draft = providerDrafts[next] || {
      apiKey: "",
      model: preset.model,
      baseUrl: preset.baseUrl,
      protocol: preset.protocol,
    };
    setValue("model_api_key", draft.apiKey);
    setValue("model_name", draft.model || preset.model);
    setValue("model_base_url", draft.baseUrl || preset.baseUrl);
    setValue("model_protocol", draft.protocol || preset.protocol);
    renderProvider(next);
    renderShotEngine();
    if (userInitiated) syncAnalysisMode();
  }

  function applySettings() {
    settings = migrateLegacySettings(settings);
    Object.entries(DEFAULTS).forEach(([id, fallback]) => {
      if (id !== "search_keywords") setValue(id, settings[id] ?? fallback);
    });
    activeProvider = PROVIDERS[settings.model_provider] ? settings.model_provider : "openai";
    providerDrafts = {
      [activeProvider]: {
        apiKey: settings.model_api_key || "",
        model: settings.model_name || PROVIDERS[activeProvider].model,
        baseUrl: settings.model_base_url || PROVIDERS[activeProvider].baseUrl,
        protocol: settings.model_protocol || PROVIDERS[activeProvider].protocol,
      },
    };
    selectProvider(activeProvider, { restore: false });
    document.querySelectorAll('input[name="shot_engine"]').forEach((radio) => {
      radio.checked = radio.value === (settings.shot_engine || "auto");
    });
    renderShotEngine();
    renderKeywords();
    clearFieldErrors();
    syncAnalysisMode();
  }

  function collectSettings() {
    settings.rapidapi_key = byId("rapidapi_key").value.trim();
    settings.analysis_mode = "pipeline";
    settings.tk_note_asr_backend = byId("tk_note_asr_backend").value || DEFAULTS.tk_note_asr_backend;
    settings.tk_note_language = byId("tk_note_language").value.trim() || DEFAULTS.tk_note_language;
    settings.tk_note_cookies_from_browser = byId("tk_note_cookies_from_browser").value;
    settings.tk_note_proxy = byId("tk_note_proxy").value.trim();
    settings.tk_note_timeout = Number.parseInt(byId("tk_note_timeout").value, 10) || DEFAULTS.tk_note_timeout;
    settings.video_cache_dir = byId("video_cache_dir").value.trim() || DEFAULTS.video_cache_dir;
    settings.shot_engine = document.querySelector('input[name="shot_engine"]:checked')?.value || "auto";
    settings.shot_model_source = byId("shot_model_source").value || "inherit";
    settings.shot_model_api_key = byId("shot_model_api_key").value.trim();
    settings.shot_model_base_url = byId("shot_model_base_url").value.trim();
    settings.shot_model_name = byId("shot_model_name").value.trim();
    settings.shot_scene_threshold = Math.min(Math.max(Number(byId("shot_scene_threshold").value) || 27, 5), 80);
    const selectedProvider = document.querySelector('input[name="model_provider"]:checked')?.value || "openai";
    const preset = PROVIDERS[selectedProvider];
    settings.model_provider = selectedProvider;
    settings.model_protocol = selectedProvider === "custom" ? byId("model_protocol").value : preset.protocol;
    settings.model_api_key = byId("model_api_key").value.trim();
    settings.model_base_url = selectedProvider === "custom" ? byId("model_base_url").value.trim() : preset.baseUrl;
    settings.model_name = byId("model_name").value.trim();
    const parsedMinLikes = Number.parseInt(byId("min_likes").value, 10);
    settings.min_likes = Number.isFinite(parsedMinLikes) ? Math.max(0, parsedMinLikes) : DEFAULTS.min_likes;
    settings.output_dir = byId("output_dir").value.trim() || DEFAULTS.output_dir;
    if (settings.shot_engine !== "skip" && !settings.model_api_key) throw new SettingsValidationError("model_api_key", "完整分析链需要填写最终模型 API Key");
    if (settings.shot_engine !== "skip" && !settings.model_name) throw new SettingsValidationError("model_name", "完整分析链需要填写最终模型名称");
    if (settings.shot_engine !== "skip" && selectedProvider === "custom") {
      let endpoint;
      try { endpoint = new URL(settings.model_base_url); }
      catch (_) { throw new SettingsValidationError("model_base_url", "自定义 Base URL 不是有效的完整地址"); }
      if (!(["http:", "https:"].includes(endpoint.protocol)) || endpoint.search || endpoint.hash) {
        throw new SettingsValidationError("model_base_url", "自定义 Base URL 需使用 HTTP(S)，且不能包含查询参数或锚点");
      }
    }
    if (["auto", "shotloom"].includes(settings.shot_engine)) {
      if (settings.shot_model_source === "inherit") {
        const inheritsVision = preset.vision && settings.model_protocol === "openai";
        if (!inheritsVision) {
          throw new SettingsValidationError("shot_model_source", "当前最终模型不能作为 ShotLoom 视觉模型；请选择 Qwen VL 或自定义 OpenAI-compatible 视觉模型");
        }
      } else {
        if (!settings.shot_model_api_key) throw new SettingsValidationError("shot_model_api_key", "ShotLoom Core 需要镜头视觉模型 API Key");
        if (!settings.shot_model_base_url) throw new SettingsValidationError("shot_model_base_url", "镜头视觉模型需要 Base URL");
        if (!settings.shot_model_name) throw new SettingsValidationError("shot_model_name", "镜头视觉模型需要模型名称");
        let shotEndpoint;
        try { shotEndpoint = new URL(settings.shot_model_base_url); }
        catch (_) { throw new SettingsValidationError("shot_model_base_url", "镜头模型 Base URL 不是有效的完整地址"); }
        if (!(["http:", "https:"].includes(shotEndpoint.protocol)) || shotEndpoint.search || shotEndpoint.hash) {
          throw new SettingsValidationError("shot_model_base_url", "镜头模型 Base URL 需使用 HTTP(S)，且不能包含查询参数或锚点");
        }
      }
    }
    return settings;
  }

  function initMotion() {
    const items = document.querySelectorAll("[data-motion]");
    if (!items.length) return;
    if (reduceMotion || typeof window.gsap === "undefined") {
      items.forEach((item) => { item.style.opacity = "1"; item.style.transform = "none"; });
      return;
    }
    window.gsap.from(items, {
      autoAlpha: 0, y: 20, duration: 0.6, stagger: 0.055,
      ease: "power4.out", clearProps: "visibility,opacity,transform",
    });
  }

  function clearFieldError(id) {
    const control = byId(id);
    if (!control) return;
    const errorId = `${id}-error`;
    byId(errorId)?.remove();
    control.removeAttribute("aria-invalid");
    control.removeAttribute("aria-errormessage");
    const describedBy = (control.getAttribute("aria-describedby") || "")
      .split(/\s+/)
      .filter((token) => token && token !== errorId);
    if (describedBy.length) control.setAttribute("aria-describedby", describedBy.join(" "));
    else control.removeAttribute("aria-describedby");
    control.closest(".settings-field")?.querySelectorAll(".field-note").forEach((note) => { note.hidden = false; });
  }

  function clearFieldErrors() {
    document.querySelectorAll("[aria-invalid='true']").forEach((control) => clearFieldError(control.id));
  }

  function showFieldError(id, message) {
    const control = byId(id);
    if (!control) return;
    clearFieldError(id);
    const details = control.closest("details");
    if (details) details.open = true;
    const field = control.closest(".settings-field");
    field?.querySelectorAll(".field-note").forEach((note) => { note.hidden = true; });
    const error = document.createElement("small");
    error.className = "field-error";
    error.id = `${id}-error`;
    error.textContent = message;
    field?.appendChild(error);
    control.setAttribute("aria-invalid", "true");
    control.setAttribute("aria-errormessage", error.id);
    const describedBy = new Set((control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
    describedBy.add(error.id);
    control.setAttribute("aria-describedby", Array.from(describedBy).join(" "));
    control.scrollIntoView({ block: "center", behavior: reduceMotion ? "auto" : "smooth" });
    control.focus({ preventScroll: true });
  }

  function showStatus(message, type = "success", { focus = true } = {}) {
    const status = byId("status");
    status.textContent = message;
    status.className = `settings-status ${type}`;
    status.setAttribute("role", type === "error" ? "alert" : "status");
    status.hidden = false;
    if (focus) status.focus({ preventScroll: true });
    if (type === "success") window.setTimeout(() => { status.hidden = true; }, 4500);
  }

  function updateRuntimeNote(health = {}) {
    const note = byId("runtime-note");
    if (runtimeMode !== "edgeone") { note.hidden = true; return; }
    const configured = health.configured || {};
    const provider = String(settings.model_provider || health.analysis_provider || "openai");
    const providerLabel = PROVIDERS[provider]?.name || provider;
    const searchProvider = String(health.keyword_search_provider || "scraper7").toLowerCase() === "scraper7"
      ? "TikTok Scraper7"
      : String(health.keyword_search_provider || "scraper7");
    note.replaceChildren();
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "当前标签页的安全配置";
    const description = document.createElement("p");
    description.textContent = "TikTok Scraper7 与模型密钥只保存在当前标签页。完整任务发送给仅监听 127.0.0.1 的 Connector，由它串联 TK Note、镜头证据与最终模型；EdgeOne 不代理分析内容。";
    copy.append(title, description);
    const badges = document.createElement("div");
    badges.className = "runtime-badges";
    const connectorLabel = !connectorState.available
      ? "未启动"
      : connectorState.paired
        ? "已安全配对"
        : "等待配对";
    const modelConfigured = Boolean(settings.model_api_key && settings.model_name) || configured.model;
    const libtvConnected = connectorState.libtv?.state === "connected";
    const shotloomInstalled = Boolean(connectorState.shotloomCore?.installed);
    [["证据链", "串联"], ["本机 Connector", connectorLabel], ["ShotLoom Core", shotloomInstalled ? "已安装" : "待安装"], ["LibTV 备用", libtvConnected ? "已连接" : "未连接"], [`${providerLabel} 最终模型`, modelConfigured ? "已配置" : "未配置"], [`${searchProvider} 搜索`, settings.rapidapi_key || configured.keyword_search ? "已配置" : "未配置"]]
      .forEach(([label, value]) => {
        const badge = document.createElement("span");
        badge.textContent = `${label} · ${value}`;
        badges.appendChild(badge);
      });
    note.append(copy, badges);
    note.hidden = false;
  }

  function configureCloudPage() {
    document.documentElement.dataset.runtime = "edgeone";
    document.querySelectorAll("[data-local-only]").forEach((field) => {
      field.hidden = true;
      field.querySelectorAll("input, select, textarea").forEach((control) => { control.disabled = true; });
    });
    document.querySelector(".settings-hero > p:last-child").textContent = "EdgeOne 只提供网页界面；本机 Connector 串联 TK Note、ShotLoom Core、可选 LibTV 与最终模型。密钥只留在当前标签页。";
    document.querySelector(".settings-actions > p").textContent = "保存到当前标签页；关闭后自动清除。";
    byId("save-btn").textContent = "保存到当前会话";
    byId("reset-btn").textContent = "恢复会话值";
    byId("clear-session-btn").hidden = false;
    byId("tk_note_timeout").min = "30";
    byId("tk_note_timeout").max = "90";
  }

  function renderLibTVState(state = {}) {
    const panel = byId("libtv-connection");
    const connectionState = String(state.state || "disconnected");
    const labels = {
      connected: "已连接",
      awaiting_browser: "等待网页授权",
      starting: "正在启动",
      unavailable: "需要安装 CLI",
      error: "连接失败",
      local_only: "仅本地可用",
      connector_missing: "未检测到 Connector",
      pairing_required: "等待安全配对",
      disconnected: "尚未连接",
    };
    panel.dataset.connectionState = connectionState;
    byId("libtv-auth-label").textContent = labels[connectionState] || "尚未连接";
    byId("libtv-auth-message").textContent = state.message || "点击连接后，将打开 LibTV 官方授权页。";
    byId("libtv-summary-state").textContent = labels[connectionState] || "尚未连接";

    const busy = ["starting", "awaiting_browser"].includes(connectionState);
    const connected = connectionState === "connected";
    const unavailable = connectionState === "unavailable";
    const localOnly = connectionState === "local_only";
    const connectorBlocked = ["connector_missing", "pairing_required"].includes(connectionState);
    const connect = byId("libtv-connect-btn");
    connect.hidden = connected || unavailable || connectorBlocked;
    connect.disabled = busy || localOnly || connectorBlocked;
    connect.toggleAttribute("aria-busy", busy);
    connect.textContent = busy ? "等待授权" : (connectionState === "error" ? "重新连接" : "连接 LibTV");
    byId("libtv-refresh-btn").hidden = localOnly;
    byId("libtv-disconnect-btn").hidden = !connected;
    byId("connector-guide-link").hidden = !connectorBlocked;
    byId("libtv-install-link").hidden = !unavailable;
  }

  function stopLibTVPolling() {
    if (libtvPollTimer) window.clearTimeout(libtvPollTimer);
    libtvPollTimer = 0;
  }

  async function refreshLibTVState({ force = false, poll = false } = {}) {
    if (runtimeMode === "edgeone") {
      try {
        const pairing = await window.ViralXConnector?.ready();
        const status = await window.ViralXConnector?.probe({ force });
        connectorState = {
          available: true,
          paired: Boolean(status?.paired),
          libtv: status?.libtv || null,
          shotloomCore: status?.shotloom_core || null,
        };
        if (!connectorState.paired) {
          renderLibTVState({
            state: "pairing_required",
            message: pairing?.error
              ? `安全配对没有完成：${pairing.error}。请重启 Connector。`
              : "Connector 已启动，但当前标签页没有会话。重启 Connector 后会自动打开配对页。",
          });
          updateRuntimeNote();
          return;
        }
        const state = connectorState.libtv || {};
        renderLibTVState(state);
        renderShotEngine();
        updateRuntimeNote();
        if (poll && ["starting", "awaiting_browser"].includes(state.state)) {
          stopLibTVPolling();
          libtvPollTimer = window.setTimeout(() => refreshLibTVState({ force: true, poll: true }), 1500);
        } else {
          stopLibTVPolling();
        }
      } catch (_) {
        connectorState = { available: false, paired: false, libtv: null, shotloomCore: null };
        stopLibTVPolling();
        const permission = await window.ViralXConnector?.permissionState();
        renderLibTVState({
          state: "connector_missing",
          message: permission === "denied"
            ? "浏览器已拒绝本机网络访问。请在本站点权限中允许本地网络，然后刷新状态。"
            : "这台电脑尚未运行 ViralX Connector，或浏览器尚未允许本机网络。启动后它会打开本页并自动完成一次性配对。",
        });
        renderShotEngine();
        updateRuntimeNote();
      }
      return;
    }
    try {
      const response = await window.fetch(`/api/libtv/auth/status${force ? "?refresh=1" : ""}`, { cache: "no-store" });
      const state = await response.json();
      if (!response.ok) throw new Error(state.message || `HTTP ${response.status}`);
      renderLibTVState(state);
      if (poll && ["starting", "awaiting_browser"].includes(state.state)) {
        stopLibTVPolling();
        libtvPollTimer = window.setTimeout(() => refreshLibTVState({ force: true, poll: true }), 1500);
      } else {
        stopLibTVPolling();
      }
    } catch (error) {
      stopLibTVPolling();
      renderLibTVState({ state: "error", message: `无法读取 LibTV 连接状态：${error.message}` });
    }
  }

  async function startLibTVLogin() {
    if (runtimeMode === "edgeone" && !connectorState.paired) {
      await refreshLibTVState({ force: true });
      return;
    }
    const popup = window.open("about:blank", "ViralXLibTVLogin");
    renderLibTVState({ state: "starting", message: "正在向本机 LibTV CLI 请求官方授权地址…" });
    try {
      const response = runtimeMode === "edgeone"
        ? await window.ViralXConnector.request("/connector/v1/libtv/login/start", { method: "POST" })
        : await window.fetch("/api/libtv/auth/start", { method: "POST" });
      const state = await response.json();
      if (!response.ok) throw new Error(state.message || `HTTP ${response.status}`);
      renderLibTVState(state);
      if (state.login_url) {
        if (popup) popup.location.replace(state.login_url);
        else window.open(state.login_url, "_blank", "noopener,noreferrer");
      } else if (popup) {
        popup.close();
      }
      if (["starting", "awaiting_browser"].includes(state.state)) {
        stopLibTVPolling();
        libtvPollTimer = window.setTimeout(() => refreshLibTVState({ force: true, poll: true }), 1500);
      }
    } catch (error) {
      if (popup) popup.close();
      renderLibTVState({ state: "error", message: `LibTV 没有连接：${error.message}` });
    }
  }

  async function disconnectLibTV() {
    stopLibTVPolling();
    try {
      const response = runtimeMode === "edgeone"
        ? await window.ViralXConnector.request("/connector/v1/libtv/logout", { method: "POST" })
        : await window.fetch("/api/libtv/auth/logout", { method: "POST" });
      const state = await response.json();
      if (!response.ok) throw new Error(state.message || `HTTP ${response.status}`);
      renderLibTVState(state);
      showStatus("已断开本机 LibTV CLI 登录。", "success");
    } catch (error) {
      renderLibTVState({ state: "error", message: `无法断开 LibTV：${error.message}` });
    }
  }

  async function loadLocalSettings() {
    const response = await window.fetch("/api/settings");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    settings = { ...DEFAULTS, ...migrateLegacySettings(await response.json()) };
    applySettings();
  }

  async function loadCloudSettings(health) {
    configureCloudPage();
    settings = { ...DEFAULTS, ...migrateLegacySettings(window.ViralXCloudConfig?.read() || {}) };
    applySettings();
    const pairing = await window.ViralXConnector?.ready();
    if (pairing?.attempted && pairing.paired) {
      showStatus("已与本机 ViralX Connector 安全配对。现在可以运行 ShotLoom Core；LibTV 仅作备用。", "success", { focus: false });
    } else if (pairing?.attempted && pairing.error) {
      showStatus(`Connector 配对失败：${pairing.error}`, "error", { focus: false });
    }
    await refreshLibTVState();
    updateRuntimeNote(health);
  }

  async function loadSettings() {
    try {
      const healthResponse = await apiFetch("/api/health", { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(`HTTP ${healthResponse.status}`);
      const health = await healthResponse.json();
      runtimeMode = health.runtime || "local";
      if (runtimeMode === "edgeone") await loadCloudSettings(health);
      else {
        await loadLocalSettings();
        await refreshLibTVState();
      }
    } catch (error) {
      showStatus(`配置没有载入：${error.message}。确认分析服务可访问后重试。`, "error");
    }
  }

  function renderKeywords() {
    const container = byId("keywords-list");
    container.replaceChildren();
    (settings.search_keywords || []).forEach((keyword) => {
      const tag = document.createElement("span");
      tag.className = "keyword-tag";
      const label = document.createElement("span");
      label.textContent = keyword;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除关键词 ${keyword}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => removeKeyword(keyword));
      tag.append(label, remove);
      container.appendChild(tag);
    });
    if (!container.children.length) {
      const empty = document.createElement("span");
      empty.className = "field-note";
      empty.textContent = "暂时没有保存的搜索关键词。";
      container.appendChild(empty);
    }
  }

  function addKeyword(keyword) {
    const clean = keyword.trim();
    if (!clean) return;
    if (!settings.search_keywords) settings.search_keywords = [];
    if (!settings.search_keywords.includes(clean)) settings.search_keywords.push(clean);
    byId("new-keyword").value = "";
    renderKeywords();
  }

  function removeKeyword(keyword) {
    settings.search_keywords = (settings.search_keywords || []).filter((item) => item !== keyword);
    renderKeywords();
  }

  async function saveSettings() {
    const button = byId("save-btn");
    const previousLabel = button.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "正在保存";
    try {
      clearFieldErrors();
      collectSettings();
      if (runtimeMode === "edgeone") {
        settings.tk_note_timeout = Math.min(Math.max(settings.tk_note_timeout, 30), 90);
        window.ViralXCloudConfig.write(settings);
        const healthResponse = await apiFetch("/api/health", { cache: "no-store" });
        updateRuntimeNote(healthResponse.ok ? await healthResponse.json() : {});
        await refreshLibTVState();
        showStatus("已保存到当前浏览器会话。返回分析页后立即生效，关闭标签页会自动清除。", "success");
      } else {
        const response = await window.fetch("/api/settings", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
        });
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.message || `HTTP ${response.status}`);
        showStatus("设置已保存，新的分析任务会立即使用这组配置。", "success");
      }
    } catch (error) {
      if (error instanceof SettingsValidationError) {
        showStatus(`设置没有保存：${error.message}。`, "error", { focus: false });
        showFieldError(error.fieldId, error.message);
      } else {
        showStatus(`设置没有保存：${error.message}。检查字段后重试。`, "error");
      }
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = previousLabel;
    }
  }

  async function clearCloudSession() {
    window.ViralXCloudConfig?.clear();
    settings = { ...DEFAULTS };
    applySettings();
    const response = await apiFetch("/api/health", { cache: "no-store" });
    updateRuntimeNote(response.ok ? await response.json() : {});
    showStatus("当前标签页中的临时密钥已清除。", "success");
  }

  function bindCategoryNav() {
    const links = Array.from(document.querySelectorAll(".category-nav a"));
    const sections = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      links.forEach((link) => {
        if (link.getAttribute("href") === `#${visible.target.id}`) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    }, { rootMargin: "-20% 0px -65%", threshold: [0.05, 0.25] });
    sections.forEach((section) => observer.observe(section));
  }

  document.addEventListener("DOMContentLoaded", () => {
    byId("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
    byId("reset-btn").addEventListener("click", loadSettings);
    byId("clear-session-btn").addEventListener("click", clearCloudSession);
    byId("libtv-connect-btn").addEventListener("click", startLibTVLogin);
    byId("libtv-refresh-btn").addEventListener("click", () => refreshLibTVState({ force: true }));
    byId("libtv-disconnect-btn").addEventListener("click", disconnectLibTV);
    byId("new-keyword").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); addKeyword(event.currentTarget.value); }
    });
    document.querySelectorAll('input[name="model_provider"]').forEach((radio) => {
      radio.addEventListener("change", (event) => {
        if (event.currentTarget.checked) selectProvider(event.currentTarget.value, { userInitiated: true });
      });
    });
    document.querySelectorAll('input[name="shot_engine"]').forEach((radio) => {
      radio.addEventListener("change", () => renderShotEngine());
    });
    byId("shot_model_source").addEventListener("change", (event) => {
      if (event.currentTarget.value === "qwen") {
        setValue("shot_model_base_url", DEFAULTS.shot_model_base_url);
        setValue("shot_model_name", DEFAULTS.shot_model_name);
      }
      renderShotEngine();
    });
    byId("model_base_url").addEventListener("input", () => renderProvider("custom"));
    document.querySelectorAll(".settings-field input, .settings-field select, .settings-field textarea").forEach((control) => {
      const clear = () => {
        if (control.getAttribute("aria-invalid") === "true") clearFieldError(control.id);
      };
      control.addEventListener("input", clear);
      control.addEventListener("change", clear);
    });
    settings = { ...DEFAULTS };
    applySettings();
    initMotion();
    bindCategoryNav();
    loadSettings();
  });
})();
