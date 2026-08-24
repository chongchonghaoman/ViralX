(() => {
  "use strict";

  const DEFAULTS = {
    rapidapi_key: "", analysis_mode: "libtv", libtv_access_key: "",
    libtv_im_base: "https://im.liblib.tv", libtv_poll_interval: 8,
    libtv_timeout: 100, libtv_concurrency: 1, tk_note_asr_backend: "auto",
    tk_note_language: "auto", tk_note_cookies_from_browser: "", tk_note_proxy: "",
    tk_note_timeout: 90, video_cache_dir: "./video_cache", gemini_api_key: "",
    gemini_model: "gemini-2.5-flash", openrouter_api_key: "",
    openrouter_model: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    minimax_api_key: "", minimax_base_url: "https://api.minimaxi.com/anthropic",
    minimax_model: "MiniMax-M2.7", min_likes: 5000, output_dir: "./data",
    search_keywords: [],
  };

  let settings = {};
  let runtimeMode = "local";
  const byId = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const apiFetch = (url, options) => window.ViralXCloudConfig
    ? window.ViralXCloudConfig.apiFetch(url, options)
    : window.fetch(url, options);

  function setValue(id, value) {
    const field = byId(id);
    if (field) field.value = value ?? "";
  }

  function applySettings() {
    Object.entries(DEFAULTS).forEach(([id, fallback]) => {
      if (id !== "search_keywords") setValue(id, settings[id] ?? fallback);
    });
    renderKeywords();
  }

  function collectSettings() {
    settings.rapidapi_key = byId("rapidapi_key").value.trim();
    settings.analysis_mode = byId("analysis_mode").value;
    settings.libtv_access_key = byId("libtv_access_key").value.trim();
    settings.libtv_im_base = byId("libtv_im_base").value.trim() || DEFAULTS.libtv_im_base;
    settings.libtv_poll_interval = Number.parseInt(byId("libtv_poll_interval").value, 10) || DEFAULTS.libtv_poll_interval;
    settings.libtv_timeout = Number.parseInt(byId("libtv_timeout").value, 10) || DEFAULTS.libtv_timeout;
    settings.libtv_concurrency = Number.parseInt(byId("libtv_concurrency").value, 10) || DEFAULTS.libtv_concurrency;
    settings.tk_note_asr_backend = byId("tk_note_asr_backend").value || DEFAULTS.tk_note_asr_backend;
    settings.tk_note_language = byId("tk_note_language").value.trim() || DEFAULTS.tk_note_language;
    settings.tk_note_cookies_from_browser = byId("tk_note_cookies_from_browser").value;
    settings.tk_note_proxy = byId("tk_note_proxy").value.trim();
    settings.tk_note_timeout = Number.parseInt(byId("tk_note_timeout").value, 10) || DEFAULTS.tk_note_timeout;
    settings.video_cache_dir = byId("video_cache_dir").value.trim() || DEFAULTS.video_cache_dir;
    settings.gemini_api_key = byId("gemini_api_key").value.trim();
    settings.gemini_model = byId("gemini_model").value.trim() || DEFAULTS.gemini_model;
    settings.openrouter_api_key = byId("openrouter_api_key").value.trim();
    settings.openrouter_model = byId("openrouter_model").value.trim() || DEFAULTS.openrouter_model;
    settings.minimax_api_key = byId("minimax_api_key").value.trim();
    settings.minimax_base_url = byId("minimax_base_url").value.trim() || DEFAULTS.minimax_base_url;
    settings.minimax_model = byId("minimax_model").value.trim() || DEFAULTS.minimax_model;
    settings.min_likes = Number.parseInt(byId("min_likes").value, 10) || DEFAULTS.min_likes;
    settings.output_dir = byId("output_dir").value.trim() || DEFAULTS.output_dir;
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

  function showStatus(message, type = "success") {
    const status = byId("status");
    status.textContent = message;
    status.className = `settings-status ${type}`;
    status.hidden = false;
    status.focus({ preventScroll: true });
    if (type === "success") window.setTimeout(() => { status.hidden = true; }, 4500);
  }

  function updateRuntimeNote(health = {}) {
    const note = byId("runtime-note");
    if (runtimeMode !== "edgeone") { note.hidden = true; return; }
    const configured = health.configured || {};
    const provider = String(health.analysis_provider || settings.analysis_mode || "libtv");
    note.replaceChildren();
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "当前标签页的安全配置";
    const description = document.createElement("p");
    description.textContent = "密钥只保存在浏览器 sessionStorage，并通过 HTTPS 发送给 ViralX 云函数；关闭标签页后自动清除。不要在共享设备上填写。";
    copy.append(title, description);
    const badges = document.createElement("div");
    badges.className = "runtime-badges";
    [["分析模式", provider], ["LibTV", configured.libtv ? "已配置" : "未配置"], ["关键词", configured.keyword_search ? "已配置" : "未配置"]]
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
    document.querySelector(".settings-hero > p:last-child").textContent = "网页端使用当前标签页的临时凭据调用 EdgeOne 云函数；本地目录、浏览器 Cookie 与持久缓存仍由本地 Flask 管理。";
    document.querySelector(".settings-actions > p").textContent = "保存到当前标签页；关闭后自动清除。";
    byId("save-btn").textContent = "保存到当前会话";
    byId("reset-btn").textContent = "恢复会话值";
    byId("clear-session-btn").hidden = false;
    byId("libtv_timeout").max = "100";
    byId("tk_note_timeout").min = "30";
    byId("tk_note_timeout").max = "90";
  }

  async function loadLocalSettings() {
    const response = await window.fetch("/api/settings");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    settings = { ...DEFAULTS, ...(await response.json()) };
    applySettings();
  }

  async function loadCloudSettings(health) {
    configureCloudPage();
    settings = { ...DEFAULTS, ...(window.ViralXCloudConfig?.read() || {}) };
    applySettings();
    updateRuntimeNote(health);
  }

  async function loadSettings() {
    try {
      const healthResponse = await apiFetch("/api/health", { cache: "no-store" });
      if (!healthResponse.ok) throw new Error(`HTTP ${healthResponse.status}`);
      const health = await healthResponse.json();
      runtimeMode = health.runtime || "local";
      if (runtimeMode === "edgeone") await loadCloudSettings(health);
      else await loadLocalSettings();
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
    collectSettings();
    try {
      if (runtimeMode === "edgeone") {
        settings.libtv_timeout = Math.min(Math.max(settings.libtv_timeout, 30), 100);
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
      showStatus(`设置没有保存：${error.message}。检查字段后重试。`, "error");
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
    byId("new-keyword").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); addKeyword(event.currentTarget.value); }
    });
    initMotion();
    bindCategoryNav();
    loadSettings();
  });
})();
