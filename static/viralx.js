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

  function setPipelineState(percent) {
    const stages = Array.from(document.querySelectorAll(".stage"));
    const thresholds = [8, 45, 82];

    stages.forEach((stage, index) => {
      const stateLabel = stage.querySelector(".stage__state");
      let state = "idle";
      let text = "等待";

      if (percent >= 100 || percent >= (thresholds[index + 1] ?? 100)) {
        state = "complete";
        text = "完成";
      } else if (percent >= thresholds[index]) {
        state = "active";
        text = "运行";
      }

      stage.dataset.state = state;
      if (stateLabel) stateLabel.textContent = text;
    });
  }

  function updateProgress(label, percent) {
    const rawPercent = Math.max(0, Math.min(Number(percent) || 0, 100));
    const normalized = rawPercent / 100;
    const progressBar = byId("progress-bar");
    const progressLabel = byId("progress-label");
    const headerDesc = byId("header-desc");

    progressLabel.textContent = label;
    progressBar.parentElement.setAttribute("aria-valuenow", String(Math.round(normalized * 100)));
    setPipelineState(rawPercent);

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
      runtimeReady = Boolean(data.analysis_ready);
      const providerKey = String(data.analysis_provider || "libtv").toLowerCase();
      const provider = {
        libtv: "LibTV",
        gemini: "Gemini",
        openrouter: "OpenRouter",
        minimax: "MiniMax",
      }[providerKey] || providerKey;

      if (runtimeReady) {
        chip.dataset.state = "ready";
        label.textContent = runtimeMode === "edgeone"
          ? `EdgeOne 云端分析 · ${provider} 就绪`
          : `本地分析服务 · ${provider} 就绪`;
      } else {
        chip.dataset.state = "warning";
        label.textContent = runtimeMode === "edgeone"
          ? `云端接口在线 · 待配置 ${provider}`
          : `本地服务在线 · 待配置 ${provider}`;
      }
    } catch (_) {
      runtimeMode = "offline";
      runtimeReady = false;
      chip.dataset.state = "offline";
      label.textContent = "分析服务暂不可用";
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
    byId("modal-content").innerHTML = window.marked ? window.marked.parse(content || "暂无报告内容") : escapeHtml(content || "暂无报告内容");

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
    analyzeButton.textContent = isBusy ? "正在拉片" : "开始拉片";
  }

  function renderVideoCard(video, index) {
    const videoUrl = video.source_url || `https://www.tiktok.com/@${video.author}/video/${video.video_id}`;
    const analysisId = `analysis-${Date.now()}-${index}`;
    const remakeId = `remake-${Date.now()}-${index}`;
    const provider = video.analysis_provider || "ai";
    const status = video.libtv_status || "";
    const acquisitionProvider = video.acquisition_provider || "";
    const acquisitionStatus = video.tk_note_status || video.video_ingest_status || "";
    const acquisitionLabel = acquisitionProvider === "tk-note"
      ? "TK Note · 已采集"
      : acquisitionProvider
        ? `${acquisitionProvider} · 已采集`
        : "";
    const providerLabel = provider === "libtv"
      ? status === "pending" || status === "timeout"
        ? "LibTV · 处理中"
        : status === "error"
          ? "LibTV · 失败"
          : "LibTV · 已完成"
      : provider;
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
        <span class="provider-badge ${escapeHtml(status)}">${escapeHtml(providerLabel)}</span>
      </div>
      <div class="card-actions">
        <button class="analysis-btn" type="button">打开拉片报告</button>
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
    updateResultCount(0, "管线运行中");
    updateProgress("正在准备视频证据，随后提交 LibTV", 8);

    const streamContainer = document.createElement("div");
    streamContainer.id = "stream-results";
    streamContainer.className = "results-list";
    results.appendChild(streamContainer);

    let received = 0;
    let done = false;

    const handlePayload = (data) => {
      if (data.status === "error") {
        showInlineError(data.message || "分析没有完成，请检查来源后重试。");
        updateProgress("分析未开始", 0);
        updateResultCount(received, "管线失败");
        return;
      }

      if (data.status === "progress" && !data.done) {
        received += 1;
        const total = Math.max(data.total || 1, 1);
        const percent = 18 + (data.current / total) * 72;
        updateProgress(`正在拆解 ${data.current}/${total} 条视频`, percent);
        streamContainer.appendChild(renderVideoCard(data.video, received - 1));
        updateResultCount(received);
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
          : `拉片完成，共 ${total} 条视频`;
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
      const hint = runtimeMode === "edgeone"
        ? "确认云端运行状态与服务配置"
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
    const title = provider === "libtv" ? "LibTV 一键拉片报告" : provider === "remake" ? "复刻脚本" : "AI 深度拆解";
    openModal(title, content);
  }

  function bindEvents() {
    byId("analyze-btn").addEventListener("click", () => analyze(false));
    byId("refresh-btn").addEventListener("click", () => analyze(true));
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
    checkRuntime();
    loadKeywords();
    updateProgress("等待视频来源", 0);
  });
})();
