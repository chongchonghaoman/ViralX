(() => {
  "use strict";

  const PROVIDERS = {
    openai: { name: "OpenAI", protocol: "openai", baseUrl: "https://api.openai.com/v1", model: "gpt-4.1-mini", keyPlaceholder: "OpenAI API Key" },
    anthropic: { name: "Anthropic Claude", protocol: "anthropic", baseUrl: "https://api.anthropic.com", model: "claude-sonnet-5", keyPlaceholder: "Anthropic API Key" },
    gemini: { name: "Google Gemini", protocol: "gemini", baseUrl: "https://generativelanguage.googleapis.com", model: "gemini-3.7-flash", keyPlaceholder: "Google AI Studio API Key" },
    deepseek: { name: "DeepSeek", protocol: "openai", baseUrl: "https://api.deepseek.com", model: "deepseek-v4-flash", keyPlaceholder: "DeepSeek API Key" },
    openrouter: { name: "OpenRouter", protocol: "openai", baseUrl: "https://openrouter.ai/api/v1", model: "openrouter/auto", keyPlaceholder: "OpenRouter API Key" },
    custom: { name: "自定义 API", protocol: "openai", baseUrl: "", model: "", keyPlaceholder: "自定义服务的 API Key" },
  };

  const DEFAULTS = {
    rapidapi_key: "", analysis_mode: "libtv", libtv_concurrency: 1, tk_note_asr_backend: "auto",
    tk_note_language: "auto", tk_note_cookies_from_browser: "", tk_note_proxy: "",
    tk_note_timeout: 90, video_cache_dir: "./video_cache", model_provider: "openai",
    model_protocol: "openai", model_api_key: "", model_base_url: "https://api.openai.com/v1",
    model_name: "gpt-4.1-mini", gemini_api_key: "", gemini_model: "gemini-3.7-flash", openrouter_api_key: "",
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
    if (!["gemini", "openrouter", "minimax"].includes(legacyMode)) return migrated;
    const legacy = {
      gemini: { provider: "gemini", protocol: "gemini", key: migrated.gemini_api_key, baseUrl: PROVIDERS.gemini.baseUrl, model: migrated.gemini_model },
      openrouter: { provider: "openrouter", protocol: "openai", key: migrated.openrouter_api_key, baseUrl: PROVIDERS.openrouter.baseUrl, model: migrated.openrouter_model },
      minimax: { provider: "custom", protocol: "anthropic", key: migrated.minimax_api_key, baseUrl: migrated.minimax_base_url, model: migrated.minimax_model },
    }[legacyMode];
    migrated.analysis_mode = "model";
    migrated.model_provider = legacy.provider;
    migrated.model_protocol = legacy.protocol;
    migrated.model_api_key ||= legacy.key || "";
    migrated.model_base_url ||= legacy.baseUrl || "";
    migrated.model_name ||= legacy.model || "";
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
    const mode = byId("analysis_mode")?.value || "libtv";
    document.querySelectorAll("[data-mode-details]").forEach((details) => {
      const active = details.dataset.modeDetails === mode;
      details.open = active;
      details.closest(".settings-section")?.classList.toggle("is-active", active);
    });
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
    if (userInitiated) {
      byId("analysis_mode").value = "model";
      syncAnalysisMode();
    }
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
    renderKeywords();
    clearFieldErrors();
    syncAnalysisMode();
  }

  function collectSettings() {
    settings.rapidapi_key = byId("rapidapi_key").value.trim();
    settings.analysis_mode = byId("analysis_mode").value;
    settings.tk_note_asr_backend = byId("tk_note_asr_backend").value || DEFAULTS.tk_note_asr_backend;
    settings.tk_note_language = byId("tk_note_language").value.trim() || DEFAULTS.tk_note_language;
    settings.tk_note_cookies_from_browser = byId("tk_note_cookies_from_browser").value;
    settings.tk_note_proxy = byId("tk_note_proxy").value.trim();
    settings.tk_note_timeout = Number.parseInt(byId("tk_note_timeout").value, 10) || DEFAULTS.tk_note_timeout;
    settings.video_cache_dir = byId("video_cache_dir").value.trim() || DEFAULTS.video_cache_dir;
    const selectedProvider = document.querySelector('input[name="model_provider"]:checked')?.value || "openai";
    const preset = PROVIDERS[selectedProvider];
    settings.model_provider = selectedProvider;
    settings.model_protocol = selectedProvider === "custom" ? byId("model_protocol").value : preset.protocol;
    settings.model_api_key = byId("model_api_key").value.trim();
    settings.model_base_url = selectedProvider === "custom" ? byId("model_base_url").value.trim() : preset.baseUrl;
    settings.model_name = byId("model_name").value.trim();
    settings.min_likes = Number.parseInt(byId("min_likes").value, 10) || DEFAULTS.min_likes;
    settings.output_dir = byId("output_dir").value.trim() || DEFAULTS.output_dir;
    if (settings.analysis_mode === "model") {
      if (!settings.model_api_key) throw new SettingsValidationError("model_api_key", "模型 API 模式需要填写 API Key");
      if (!settings.model_name) throw new SettingsValidationError("model_name", "模型 API 模式需要填写模型名称");
      if (selectedProvider === "custom") {
        let endpoint;
        try { endpoint = new URL(settings.model_base_url); }
        catch (_) { throw new SettingsValidationError("model_base_url", "自定义 Base URL 不是有效的完整地址"); }
        if (!(["http:", "https:"].includes(endpoint.protocol)) || endpoint.search || endpoint.hash) {
          throw new SettingsValidationError("model_base_url", "自定义 Base URL 需使用 HTTP(S)，且不能包含查询参数或锚点");
        }
        if (runtimeMode === "edgeone" && endpoint.protocol !== "https:") {
          throw new SettingsValidationError("model_base_url", "网页端的自定义 Base URL 必须使用 HTTPS");
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
    const provider = String(health.analysis_provider || settings.model_provider || "openai");
    const providerLabel = PROVIDERS[provider]?.name || (provider === "libtv" ? "LibTV" : provider);
    const searchProvider = String(health.keyword_search_provider || "api23").toUpperCase();
    note.replaceChildren();
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "当前标签页的安全配置";
    const description = document.createElement("p");
    description.textContent = "模型与 API23 密钥只保存在浏览器 sessionStorage，并通过 HTTPS 发送给 ViralX 云函数；LibTV 网页授权只在本机版可用。";
    copy.append(title, description);
    const badges = document.createElement("div");
    badges.className = "runtime-badges";
    [["分析模式", providerLabel], ["模型 API", configured.model ? "已配置" : "未配置"], [`${searchProvider} 搜索`, configured.keyword_search ? "已配置" : "未配置"]]
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
    const libtvOption = byId("analysis_mode").querySelector('option[value="libtv"]');
    libtvOption.disabled = true;
    libtvOption.textContent = "LibTV 画布拉片 · 需本地运行";
    document.querySelector(".settings-hero > p:last-child").textContent = "EdgeOne 网页端使用当前标签页的模型 API 与 API23 临时凭据；LibTV 网页授权、本地目录和 Obsidian 文件写入由本地 Flask 管理。";
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
    const connect = byId("libtv-connect-btn");
    connect.hidden = connected || unavailable;
    connect.disabled = busy || localOnly;
    connect.toggleAttribute("aria-busy", busy);
    connect.textContent = busy ? "等待授权" : (connectionState === "error" ? "重新连接" : "连接 LibTV");
    byId("libtv-refresh-btn").hidden = localOnly;
    byId("libtv-disconnect-btn").hidden = !connected;
    byId("libtv-install-link").hidden = !unavailable && !localOnly;
  }

  function stopLibTVPolling() {
    if (libtvPollTimer) window.clearTimeout(libtvPollTimer);
    libtvPollTimer = 0;
  }

  async function refreshLibTVState({ force = false, poll = false } = {}) {
    if (runtimeMode === "edgeone") {
      renderLibTVState({
        state: "local_only",
        message: "EdgeOne 无法访问你电脑上的 LibTV CLI 登录态；线上分析请选择模型 API。",
      });
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
    if (runtimeMode === "edgeone") return;
    const popup = window.open("about:blank", "ViralXLibTVLogin");
    renderLibTVState({ state: "starting", message: "正在向本机 LibTV CLI 请求官方授权地址…" });
    try {
      const response = await window.fetch("/api/libtv/auth/start", { method: "POST" });
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
      const response = await window.fetch("/api/libtv/auth/logout", { method: "POST" });
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
    if (settings.analysis_mode === "libtv") settings.analysis_mode = "model";
    applySettings();
    updateRuntimeNote(health);
    renderLibTVState({ state: "local_only", message: "EdgeOne 无法访问你电脑上的 LibTV CLI 登录态；线上分析请选择模型 API。" });
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
    byId("model_base_url").addEventListener("input", () => renderProvider("custom"));
    byId("analysis_mode").addEventListener("change", syncAnalysisMode);
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
