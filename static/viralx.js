(() => {
  "use strict";

  let currentModalTitle = "";
  let currentModalContent = "";
  let lastModalTrigger = null;
  let runtimeMode = "unknown";
  let runtimeReady = false;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gsapReady = () => !reduceMotion && typeof window.gsap !== "undefined";

  const byId = (id) => document.getElementById(id);
  const PIPELINE_STAGES = ["discovery", "collection", "shot-analysis", "evidence-merge", "final-analysis"];
  const STAGE_STATE_LABELS = {
    idle: "等待",
    running: "运行",
    complete: "完成",
    completed: "完成",
    skipped: "跳过",
    error: "失败",
  };
  const apiFetch = (url, options) => window.ViralXCloudConfig
    ? window.ViralXCloudConfig.apiFetch(url, options)
    : window.fetch(url, options);

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  const REPORT_ALLOWED_TAGS = new Set([
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
  ]);
  const REPORT_DROPPED_TAGS = new Set([
    "button", "embed", "form", "iframe", "input", "link", "math", "meta", "object", "script", "style", "svg", "template",
  ]);

  function safeReportHref(value) {
    const candidate = String(value || "").trim();
    if (!candidate) return "";
    if (candidate.startsWith("#")) return candidate;
    try {
      const url = new URL(candidate, window.location.href);
      return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function sanitizeReportHtml(html) {
    const source = document.createElement("template");
    const shell = document.createElement("div");
    source.innerHTML = String(html || "");

    const copyNode = (node, parent) => {
      if (node.nodeType === Node.TEXT_NODE) {
        parent.appendChild(document.createTextNode(node.textContent || ""));
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const tag = node.tagName.toLowerCase();
      if (REPORT_DROPPED_TAGS.has(tag)) return;
      if (!REPORT_ALLOWED_TAGS.has(tag)) {
        Array.from(node.childNodes).forEach((child) => copyNode(child, parent));
        return;
      }

      const clean = document.createElement(tag);
      if (tag === "a") {
        const href = safeReportHref(node.getAttribute("href"));
        if (href) clean.setAttribute("href", href);
        const title = String(node.getAttribute("title") || "").trim();
        if (title) clean.setAttribute("title", title.slice(0, 240));
        clean.setAttribute("rel", "noopener noreferrer");
      }
      if (tag === "td" || tag === "th") {
        ["colspan", "rowspan"].forEach((attribute) => {
          const value = node.getAttribute(attribute);
          if (/^\d{1,2}$/.test(value || "") && Number(value) >= 1 && Number(value) <= 12) {
            clean.setAttribute(attribute, value);
          }
        });
      }
      parent.appendChild(clean);
      Array.from(node.childNodes).forEach((child) => copyNode(child, clean));
    };

    Array.from(source.content.childNodes).forEach((node) => copyNode(node, shell));
    return shell.innerHTML;
  }

  function compactCount(value) {
    return new Intl.NumberFormat("zh-CN", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(Number(value) || 0);
  }

  function initMotion() {
    const motionItems = document.querySelectorAll("[data-motion], .story-section");
    if (!motionItems.length || !gsapReady()) {
      motionItems.forEach((item) => {
        item.style.opacity = "1";
        item.style.transform = "none";
      });
      return;
    }

    if (window.ScrollTrigger) window.gsap.registerPlugin(window.ScrollTrigger);

    const intro = window.gsap.timeline({ defaults: { ease: "power4.out" } });
    intro
      .from("[data-motion='nav']", { autoAlpha: 0, y: -16, duration: 0.6 })
      .from("[data-motion='hero-object']", { autoAlpha: 0, y: 24, scale: 0.975, duration: 0.8 }, "-=0.35")
      .from("[data-motion='hero-copy']", { autoAlpha: 0, y: 28, duration: 0.7 }, "-=0.45")
      .from("[data-motion='hero-form']", { autoAlpha: 0, y: 24, duration: 0.65 }, "-=0.4");

    if (!window.ScrollTrigger) return;

    window.gsap.utils.toArray(".story-section").forEach((section) => {
      window.gsap.from(section, {
        y: 40,
        duration: 0.75,
        ease: "power4.out",
        clearProps: "transform",
        scrollTrigger: {
          trigger: section,
          start: "top 82%",
          once: true,
        },
      });
    });

    window.gsap.from(".waveform i", {
      scaleY: 0.16,
      duration: 0.55,
      stagger: 0.025,
      ease: "power3.out",
      transformOrigin: "center",
      clearProps: "transform",
      scrollTrigger: {
        trigger: ".waveform",
        start: "top 82%",
        once: true,
      },
    });

    window.gsap.from(".frame", {
      y: 20,
      duration: 0.6,
      stagger: 0.08,
      ease: "power4.out",
      clearProps: "transform",
      scrollTrigger: {
        trigger: ".frame-row",
        start: "top 82%",
        once: true,
      },
    });
  }

  function animateCard(card) {
    if (!gsapReady()) return;
    window.gsap.fromTo(card, { autoAlpha: 0, y: 16 }, {
      autoAlpha: 1,
      y: 0,
      duration: 0.45,
      ease: "power4.out",
      clearProps: "visibility,opacity,transform",
    });
  }

  function resetPipelineStages() {
    document.querySelectorAll(".stage[data-stage]").forEach((stage) => {
      stage.dataset.state = "idle";
      const stateLabel = stage.querySelector(".stage__state");
      if (stateLabel) stateLabel.textContent = STAGE_STATE_LABELS.idle;
    });
  }

  function setPipelineStage(stageName, state) {
    if (!PIPELINE_STAGES.includes(stageName)) return;
    const stage = document.querySelector(`.stage[data-stage="${stageName}"]`);
    if (!stage) return;
    const normalized = state === "completed" ? "complete" : (state || "running");
    stage.dataset.state = normalized;
    const stateLabel = stage.querySelector(".stage__state");
    if (stateLabel) stateLabel.textContent = STAGE_STATE_LABELS[normalized] || normalized;
  }

  function failActiveStage() {
    const active = document.querySelector('.stage[data-state="running"]');
    if (active) setPipelineStage(active.dataset.stage, "error");
  }

  function updateProgress(label, percent) {
    const rawPercent = Math.max(0, Math.min(Number(percent) || 0, 100));
    const normalized = rawPercent / 100;
    const progressBar = byId("progress-bar");
    const progressLabel = byId("progress-label");
    const headerDesc = byId("header-desc");

    progressLabel.textContent = label;
    progressBar.parentElement.setAttribute("aria-valuenow", String(Math.round(normalized * 100)));

    if (gsapReady()) {
      window.gsap.to(progressBar, {
        scaleX: normalized,
        duration: 0.42,
        ease: "power3.inOut",
        overwrite: true,
      });
      window.gsap.fromTo(progressLabel, { autoAlpha: 0.45 }, {
        autoAlpha: 1,
        duration: 0.24,
        ease: "power4.out",
      });
    } else {
      progressBar.style.transform = `scaleX(${normalized})`;
    }

    if (headerDesc) headerDesc.textContent = label;
  }

  function updateResultCount(count, state = "") {
    const label = byId("result-count");
    if (!label) return;
    label.textContent = state || (count ? `${count} 条结果` : "等待输入");
  }

  function showInlineError(message) {
    const error = byId("error");
    error.textContent = message;
    error.hidden = false;
    error.focus({ preventScroll: true });
  }

  function clearInlineError() {
    const error = byId("error");
    error.textContent = "";
    error.hidden = true;
  }

  function settingsUrl() {
    const deployedToEdgeOne = document.documentElement.dataset.deployment === "edgeone";
    return runtimeMode === "edgeone" || deployedToEdgeOne ? "/settings.html" : "/settings";
  }

  function syncPrimaryActions() {
    const destination = runtimeReady ? "#analysis-studio" : settingsUrl();
    document.querySelectorAll("[data-runtime-action]").forEach((action) => {
      action.href = destination;
      action.textContent = runtimeReady
        ? (action.classList.contains("nav-cta") ? "开始拉片" : "开始分析")
        : "连接分析服务";
    });
    const analyzeButton = byId("analyze-btn");
    if (analyzeButton && !analyzeButton.disabled) {
      analyzeButton.textContent = runtimeReady ? "开始拉片" : "打开设置";
    }
  }

  async function checkRuntime() {
    const chip = byId("runtime-chip");
    const label = byId("runtime-label");
    if (!chip || !label) return;

    chip.dataset.state = "checking";
    label.textContent = "正在连接分析服务";
    try {
      const response = await apiFetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      runtimeMode = data.runtime || "local";
      if (runtimeMode === "edgeone") {
        const session = window.ViralXCloudConfig?.read() || {};
        const modelReady = Boolean(session.model_api_key && session.model_name && session.model_base_url);
        try {
          await window.ViralXConnector?.ready();
          const connector = await window.ViralXConnector?.probe();
          const paired = Boolean(connector?.paired);
          const libtv = connector?.libtv || {};
          const libtvReady = Boolean(libtv.connected || libtv.state === "connected");
          runtimeReady = paired && libtvReady && modelReady;
          chip.dataset.state = runtimeReady ? "ready" : "warning";
          label.textContent = runtimeReady
            ? "完整链路就绪 · TK Note → LibTV → 模型"
            : !paired
              ? "Connector 已启动 · 待安全配对"
              : !libtvReady
                ? "Connector 已配对 · 待登录 LibTV"
                : "LibTV 已连接 · 待配置模型 API";
        } catch (_) {
          runtimeReady = false;
          chip.dataset.state = "warning";
          const permission = await window.ViralXConnector?.permissionState();
          label.textContent = permission === "denied"
            ? "网页在线 · 本机网络权限已拒绝"
            : "网页在线 · 未检测到本机 Connector";
        }
        syncPrimaryActions();
        return;
      }
      runtimeReady = Boolean(data.analysis_ready);
      if (runtimeReady) {
        chip.dataset.state = "ready";
        label.textContent = "本地完整链路就绪 · TK Note → LibTV → 模型";
      } else {
        chip.dataset.state = "warning";
        label.textContent = "本地服务在线 · 待补齐 LibTV 与模型配置";
      }
      syncPrimaryActions();
    } catch (_) {
      runtimeMode = "offline";
      runtimeReady = false;
      chip.dataset.state = "offline";
      label.textContent = "分析服务暂不可用";
      syncPrimaryActions();
    }
  }

  function openExternal(url) {
    if (/^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener,noreferrer");
  }

  function openModal(title, content) {
    const modal = byId("modal");
    const reportShell = modal.querySelector(".report-shell");
    lastModalTrigger = document.activeElement;
    currentModalTitle = title;
    currentModalContent = content;
    byId("modal-title").textContent = title;
    const report = content || "暂无报告内容";
    const rendered = window.marked ? window.marked.parse(report) : escapeHtml(report);
    byId("modal-content").innerHTML = sanitizeReportHtml(rendered);

    if (!modal.open) modal.showModal();
    document.body.dataset.modalOpen = "true";

    if (gsapReady()) {
      window.gsap.fromTo(reportShell, { autoAlpha: 0, scale: 0.98 }, {
        autoAlpha: 1,
        scale: 1,
        duration: 0.3,
        ease: "power4.out",
        clearProps: "visibility,opacity,transform",
      });
    }

    modal.querySelector(".modal-close").focus();
  }

  function closeModal() {
    const modal = byId("modal");
    if (!modal.open) return;
    const reportShell = modal.querySelector(".report-shell");

    const finish = () => {
      modal.close();
      delete document.body.dataset.modalOpen;
      if (lastModalTrigger) lastModalTrigger.focus();
    };

    if (gsapReady()) {
      window.gsap.to(reportShell, {
        autoAlpha: 0,
        scale: 0.985,
        duration: 0.2,
        ease: "power3.inOut",
        onComplete: finish,
      });
    } else {
      finish();
    }
  }

  async function exportToObsidian() {
    const button = byId("export-btn");
    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = "正在导出";

    try {
      const response = await apiFetch("/api/export-obsidian", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: currentModalTitle, content: currentModalContent }),
      });
      const data = await response.json();
      if (data.status !== "success") throw new Error(data.message || "导出请求未完成");

      if (data.obsidian_uri) {
        window.location.assign(data.obsidian_uri);
        button.textContent = "已发送到 Obsidian";
      } else if (data.content != null && data.filename) {
        const blob = new Blob([data.content], { type: "text/markdown;charset=utf-8" });
        const href = URL.createObjectURL(blob);
        const download = document.createElement("a");
        download.href = href;
        download.download = data.filename;
        document.body.appendChild(download);
        download.click();
        download.remove();
        URL.revokeObjectURL(href);
        button.textContent = "Markdown 已下载";
      } else {
        button.textContent = "已导出";
      }
      button.title = data.file_path || data.message || "报告已导出";
      window.setTimeout(() => {
        button.textContent = previousLabel;
        button.disabled = false;
      }, 2500);
    } catch (error) {
      button.textContent = "导出失败";
      button.disabled = false;
      const hint = runtimeMode === "edgeone"
        ? "确认浏览器允许打开 Obsidian URI，或下载 Markdown 后导入"
        : "检查 Obsidian 输出目录";
      showInlineError(`报告没有导出：${error.message}。${hint}后重试。`);
    }
  }

  async function loadKeywords() {
    const list = byId("keywords-list");
    try {
      const response = await apiFetch("/api/keywords");
      const data = await response.json();
      list.replaceChildren();

      const sessionKeywords = window.ViralXCloudConfig
        ? (window.ViralXCloudConfig.read().search_keywords || []).map((keyword) => ({ keyword, cached: false }))
        : [];
      const keywords = [...sessionKeywords, ...(data.keywords || [])].filter(
        (item, index, all) => all.findIndex((candidate) => candidate.keyword === item.keyword) === index,
      );

      keywords.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "keyword-item";
        button.textContent = item.keyword;
        button.addEventListener("click", () => setKeyword(item.keyword));
        list.appendChild(button);
      });

      if (!list.children.length) {
        const empty = document.createElement("span");
        empty.className = "field-help";
        empty.textContent = "完成一次分析后，这里会保存常用主题。";
        list.appendChild(empty);
      }
    } catch (_) {
      list.textContent = "暂时无法读取缓存主题";
    }
  }

  function setKeyword(keyword) {
    byId("keyword").value = keyword;
    byId("keyword").focus();
  }

  function setBusy(isBusy) {
    const analyzeButton = byId("analyze-btn");
    const refreshButton = byId("refresh-btn");
    analyzeButton.disabled = isBusy;
    refreshButton.disabled = isBusy;
    analyzeButton.setAttribute("aria-busy", String(isBusy));
    analyzeButton.textContent = isBusy ? "正在拉片" : runtimeReady ? "开始拉片" : "打开设置";
  }

  function handleAnalyzeAction(refresh = false) {
    if (!runtimeReady) {
      window.location.assign(settingsUrl());
      return;
    }
    analyze(refresh);
  }

  function renderVideoCard(video, index) {
    const videoUrl = video.source_url || `https://www.tiktok.com/@${video.author}/video/${video.video_id}`;
    const analysisId = `analysis-${Date.now()}-${index}`;
    const remakeId = `remake-${Date.now()}-${index}`;
    const provider = String(video.analysis_provider || "model").toLowerCase();
    const status = video.libtv_status || "";
    const modelStatus = video.model_status || "";
    const acquisitionProvider = video.acquisition_provider || "";
    const acquisitionStatus = video.tk_note_status || video.video_ingest_status || "";
    const acquisitionLabel = acquisitionProvider === "tk-note"
      ? "TK Note · 已采集"
      : acquisitionProvider
        ? `${acquisitionProvider} · 已采集`
        : "";
    const providerName = {
      openai: "OpenAI",
      anthropic: "Claude",
      gemini: "Gemini",
      deepseek: "DeepSeek",
      openrouter: "OpenRouter",
      custom: "自定义模型",
    }[provider] || provider;
    const libtvLabel = status === "error"
      ? "LibTV · 拉片失败"
      : status === "timeout" || status === "pending"
        ? "LibTV · 处理中"
        : "LibTV · 拉片完成";
    const providerLabel = modelStatus === "error"
      ? `${providerName} · 分析失败`
      : `${providerName} · 最终分析`;
    const projectUrl = /^https?:\/\//i.test(video.libtv_project_url || "") ? video.libtv_project_url : "";

    const card = document.createElement("article");
    card.className = "video-card";
    card.innerHTML = `
      <button class="video-title" type="button">
        ${escapeHtml((video.title || "无标题视频").substring(0, 90))}
      </button>
      <div class="video-stats" aria-label="视频数据">
        <div class="stat"><div class="stat-label">作者</div><div class="stat-value">${escapeHtml(video.author || "未知")}</div></div>
        <div class="stat"><div class="stat-label">点赞</div><div class="stat-value">${compactCount(video.likes)}</div></div>
        <div class="stat"><div class="stat-label">评论</div><div class="stat-value">${compactCount(video.comments)}</div></div>
        <div class="stat"><div class="stat-label">分享</div><div class="stat-value">${compactCount(video.shares)}</div></div>
      </div>
      <div class="provider-row">
        ${acquisitionLabel ? `<span class="provider-badge ${escapeHtml(acquisitionStatus)}">${escapeHtml(acquisitionLabel)}</span>` : ""}
        <span class="provider-badge ${escapeHtml(status)}">${escapeHtml(libtvLabel)}</span>
        <span class="provider-badge ${escapeHtml(modelStatus)}">${escapeHtml(providerLabel)}</span>
      </div>
      <div class="card-actions">
        <button class="analysis-btn" type="button">打开最终分析</button>
        ${status === "error" ? runtimeMode === "edgeone" ? '<span class="project-link">云端配置未就绪</span>' : '<a class="project-link" href="/settings">检查 LibTV 设置</a>' : ""}
        ${projectUrl ? `<a class="project-link" href="${escapeHtml(projectUrl)}" target="_blank" rel="noopener noreferrer">打开项目画布</a>` : ""}
      </div>
      <div id="${analysisId}" hidden>${escapeHtml(video.ai_analysis || "")}</div>
    `;

    card.querySelector(".video-title").addEventListener("click", () => openExternal(videoUrl));
    card.querySelector(".analysis-btn").addEventListener("click", () => showAnalysis(analysisId, provider));

    if (video.remake_script) {
      const remake = document.createElement("div");
      remake.className = "remake-script";
      remake.innerHTML = `
        <h4>适配当前产品的复刻脚本</h4>
        <button class="analysis-btn" type="button">打开复刻脚本</button>
        <div id="${remakeId}" hidden>${escapeHtml(video.remake_script)}</div>
      `;
      remake.querySelector("button").addEventListener("click", () => showAnalysis(remakeId, "remake"));
      card.appendChild(remake);
    }

    animateCard(card);
    return card;
  }

  async function analyze(refresh = false) {
    const keyword = byId("keyword").value.trim();
    const productName = byId("product-name").value;
    const productInfo = byId("product-info").value;
    const loading = byId("loading");
    const results = byId("results");

    if (!keyword) {
      showInlineError("没有可分析的来源。粘贴抖音或 TikTok 链接，或输入一个搜索主题。 ");
      byId("keyword").focus();
      return;
    }

    clearInlineError();
    setBusy(true);
    loading.hidden = false;
    results.replaceChildren();
    resetPipelineStages();
    updateResultCount(0, "管线运行中");
    updateProgress("正在启动完整证据链", 2);

    const streamContainer = document.createElement("div");
    streamContainer.id = "stream-results";
    streamContainer.className = "results-list";
    results.appendChild(streamContainer);

    let received = 0;
    let done = false;

    const handlePayload = (data) => {
      if (data.status === "error") {
        showInlineError(data.message || "分析没有完成，请检查来源后重试。");
        failActiveStage();
        updateProgress("分析链已中断", data.stage_progress || 0);
        updateResultCount(received, "管线失败");
        return;
      }

      if (data.status === "progress" && !data.done) {
        if (data.stage) setPipelineStage(data.stage, data.stage_status || "running");
        updateProgress(data.stage_label || "证据链正在运行", data.stage_progress || 0);
        if (data.video) {
          received += 1;
          streamContainer.appendChild(renderVideoCard(data.video, received - 1));
          updateResultCount(received);
        }
        return;
      }

      if (data.done || data.status === "success") {
        done = true;
        const failed = data.failed_videos || 0;
        const pending = data.pending_videos || 0;
        const total = data.total_videos || received;
        const completed = Math.max(total - failed - pending, 0);
        const summary = failed || pending
          ? `处理结束：${completed} 条完成，${pending} 条处理中，${failed} 条失败`
          : `完整分析完成，共 ${total} 条视频`;
        updateProgress(summary, 100);
        updateResultCount(received, summary);
      }
    };

    const parseLine = (line) => {
      const cleanLine = line.replace(/\r/g, "").trim();
      if (!cleanLine) return;
      try {
        handlePayload(JSON.parse(cleanLine));
      } catch (error) {
        console.warn("NDJSON parse error:", error, cleanLine.substring(0, 120));
      }
    };

    try {
      const response = await apiFetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword, refresh, product_name: productName, product_info: productInfo }),
      });
      if (!response.ok) throw new Error(`服务返回 HTTP ${response.status}`);

      if (response.body && response.body.getReader) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { value, done: readerDone } = await reader.read();
          buffer += decoder.decode(value || new Uint8Array(), { stream: !readerDone });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          lines.forEach(parseLine);
          if (readerDone) break;
        }
        parseLine(buffer);
      } else {
        const text = await response.text();
        text.split("\n").forEach(parseLine);
      }
    } catch (error) {
      failActiveStage();
      const hint = runtimeMode === "edgeone"
        ? "确认本机 Connector 正在运行、LibTV 已登录且模型 API 已配置"
        : "确认本地服务仍在运行";
      showInlineError(`分析没有完成：${error.message}。${hint}后重试。`);
      updateResultCount(received, "连接中断");
    } finally {
      setBusy(false);
      if (done || !byId("error").hidden) loading.hidden = true;
    }
  }

  function displayResults(videos) {
    const results = byId("results");
    const list = document.createElement("div");
    list.className = "results-list";
    (videos || []).forEach((video, index) => list.appendChild(renderVideoCard(video, index)));
    results.replaceChildren(list);
    updateResultCount((videos || []).length);
  }

  function showAnalysis(id, provider = "ai") {
    const content = byId(id).textContent;
    const title = provider === "remake" ? "复刻脚本" : "ViralX 最终分析";
    openModal(title, content);
  }

  function bindEvents() {
    byId("analyze-btn").addEventListener("click", () => handleAnalyzeAction(false));
    byId("refresh-btn").addEventListener("click", () => handleAnalyzeAction(true));
    byId("focus-source").addEventListener("click", () => byId("keyword").focus());
    byId("export-btn").addEventListener("click", exportToObsidian);
    document.querySelector(".modal-close").addEventListener("click", closeModal);

    const modal = byId("modal");
    modal.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeModal();
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal();
    });

    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        byId("keyword").focus();
      }
    });
  }

  window.analyze = analyze;
  window.displayResults = displayResults;
  window.showAnalysis = showAnalysis;
  window.closeModal = closeModal;

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    initMotion();
    syncPrimaryActions();
    checkRuntime();
    loadKeywords();
    resetPipelineStages();
    updateProgress("等待视频来源", 0);
  });
})();
