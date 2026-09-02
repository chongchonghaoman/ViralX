(() => {
  "use strict";

  let currentModalMarkdown = "";
  let lastModalTrigger = null;
  let runtimeMode = "unknown";
  let runtimeAnalysisReady = false;
  let runtimeSearchReady = false;
  let runtimeBlocker = "checking";
  let resultRevealHandled = false;
  let runtimeCheckPromise = null;

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gsapReady = () => !reduceMotion && typeof window.gsap !== "undefined";
  const RUNTIME_RECHECK_MS = 30000;

  const byId = (id) => document.getElementById(id);
  const PIPELINE_STAGES = ["discovery", "collection", "shot-analysis", "evidence-merge", "final-analysis"];
  const STAGE_STATE_LABELS = {
    idle: "等待",
    running: "运行",
    complete: "完成",
    completed: "完成",
    skipped: "跳过",
    blocked: "已阻断",
    degraded: "已降级",
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
    const motionItems = document.querySelectorAll("[data-motion]");
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

  function checkpointExpiryLabel(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return "任务保留期结束";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
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

  function rapidApiUrl(value) {
    try {
      const url = new URL(String(value || ""));
      const safePort = !url.port || url.port === "443";
      return url.protocol === "https:"
        && url.hostname === "rapidapi.com"
        && !url.username
        && !url.password
        && safePort
        ? url.href
        : "";
    } catch (_error) {
      return "";
    }
  }

  function renderSubscriptionRecovery(error, message, payload) {
    const links = Array.isArray(payload?.subscription_links)
      ? payload.subscription_links.filter((item) => rapidApiUrl(item?.url))
      : [];
    if (!links.length) {
      error.textContent = message;
      return false;
    }

    error.classList.add("error--actionable");
    const title = document.createElement("strong");
    title.className = "error__title";
    title.textContent = "先订阅一个搜索源";
    const copy = document.createElement("p");
    copy.className = "error__message";
    copy.textContent = message;
    const list = document.createElement("ul");
    list.className = "subscription-link-list";

    links.forEach((item) => {
      const row = document.createElement("li");
      row.className = "subscription-link-item";
      const text = document.createElement("div");
      text.className = "subscription-link__copy";
      const label = document.createElement("strong");
      label.textContent = `${item.label || item.provider || "TikTok 搜索源"}${item.recommended ? " · 推荐" : ""}`;
      const note = document.createElement("small");
      note.textContent = item.note || "查看 RapidAPI 订阅方案";
      const link = document.createElement("a");
      link.className = "subscription-link";
      link.href = rapidApiUrl(item.url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.direct === false ? "查找替代页 ↗" : "查看订阅方案 ↗";
      link.setAttribute("aria-label", `${link.textContent.replace(" ↗", "")}：${label.textContent}（新标签页）`);
      text.append(label, note);
      row.append(text, link);
      list.append(row);
    });

    error.append(title, copy, list);
    const providerErrors = Array.isArray(payload?.provider_errors) ? payload.provider_errors : [];
    if (providerErrors.length) {
      const details = document.createElement("details");
      details.className = "error__details";
      const summary = document.createElement("summary");
      summary.textContent = `查看 ${providerErrors.length} 个来源的响应`;
      const detailList = document.createElement("ul");
      providerErrors.forEach((item) => {
        const detail = document.createElement("li");
        detail.textContent = `${item.label || item.provider || "搜索源"}：${item.message || "未完成"}`;
        detailList.append(detail);
      });
      details.append(summary, detailList);
      error.append(details);
    }
    return true;
  }

  function showInlineError(message, payload = {}) {
    const error = byId("error");
    error.replaceChildren();
    error.classList.remove("error--actionable");
    renderSubscriptionRecovery(error, message, payload);
    error.hidden = false;
    error.focus({ preventScroll: true });
    window.requestAnimationFrame(() => {
      error.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    });
  }

  function clearInlineError() {
    const error = byId("error");
    error.replaceChildren();
    error.classList.remove("error--actionable");
    error.hidden = true;
  }

  function revealSection(id, block = "start") {
    const section = byId(id);
    if (!section) return;
    section.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block });
  }

  function revealFirstResult() {
    if (resultRevealHandled) return;
    resultRevealHandled = true;
    window.requestAnimationFrame(() => revealSection("results-zone"));
  }

  function isDirectVideoSource(value) {
    try {
      const source = new URL(String(value || "").trim());
      return ["http:", "https:"].includes(source.protocol) && Boolean(source.hostname);
    } catch (_) {
      return false;
    }
  }

  function sourceReady() {
    if (!runtimeAnalysisReady) return false;
    const value = byId("keyword")?.value || "";
    return isDirectVideoSource(value) || runtimeSearchReady;
  }

  function primaryActionLabel(navigation = false) {
    if (runtimeAnalysisReady && navigation) return "开始分析";
    if (sourceReady()) return "开始拉片";
    if (runtimeAnalysisReady && !runtimeSearchReady) return "需要搜索 Key";
    return {
      checking: "正在连接服务",
      server_config_missing: "分析服务配置中",
      local_config_missing: "完成本机配置",
      offline: "实时分析暂离线",
    }[runtimeBlocker] || "查看实时状态";
  }

  function syncPrimaryActions() {
    document.querySelectorAll("[data-runtime-action]").forEach((action) => {
      action.href = "#analysis-studio";
      const marketingCta = action.classList.contains("nav-cta") || action.classList.contains("hero-cta");
      action.textContent = marketingCta ? "开始分析" : primaryActionLabel(false);
    });
    const analyzeButton = byId("analyze-btn");
    if (analyzeButton && !analyzeButton.disabled) {
      analyzeButton.textContent = primaryActionLabel(false);
    }
  }

  async function checkRuntime({ silent = false } = {}) {
    if (runtimeCheckPromise) return runtimeCheckPromise;
    const chip = byId("runtime-chip");
    const label = byId("runtime-label");
    if (!chip || !label) return;

    runtimeCheckPromise = (async () => {
      if (!silent) {
        chip.dataset.state = "checking";
        label.textContent = "正在连接分析服务";
      }
      try {
        const response = await apiFetch("/api/health", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        runtimeMode = data.runtime || "local";
        runtimeAnalysisReady = Boolean(data.analysis_ready);
        runtimeSearchReady = Boolean(data.configured?.keyword_search);
        if (runtimeMode === "worker") {
          runtimeBlocker = runtimeAnalysisReady
            ? (runtimeSearchReady ? "ready" : "search_config_missing")
            : "server_config_missing";
          chip.dataset.state = runtimeAnalysisReady && runtimeSearchReady ? "ready" : "warning";
          label.textContent = runtimeAnalysisReady && runtimeSearchReady
            ? "完整分析在线 · 关键词搜索 → TK Note → 原片视觉终审"
            : runtimeAnalysisReady
              ? "直链分析在线 · 关键词搜索 Key 待配置"
              : runtimeSearchReady
                ? "关键词搜索在线 · 视觉分析链待配置"
                : "分析服务在线 · 搜索与视觉模型配置待补齐";
          syncPrimaryActions();
          return;
        }
        if (runtimeMode === "edgeone") {
          runtimeAnalysisReady = false;
          runtimeSearchReady = false;
          runtimeBlocker = "offline";
          chip.dataset.state = "offline";
          label.textContent = "展示站在线 · 实时分析服务暂未接入";
          syncPrimaryActions();
          return;
        }
        runtimeBlocker = runtimeAnalysisReady ? "ready" : "local_config_missing";
        if (runtimeAnalysisReady) {
          chip.dataset.state = runtimeSearchReady ? "ready" : "warning";
          const shot = data.shot || {};
          const pipelineLabel = shot.collection_only
            ? "本地采集链就绪 · 不生成最终报告"
            : shot.engine === "direct"
              ? "本地完整链路就绪 · TK Note → 原片视觉 → 证据终审"
              : `本地专业链路就绪 · TK Note → ${shot.engine === "libtv" ? "LibTV" : "ShotLoom"} → 原片终审`;
          label.textContent = runtimeSearchReady ? pipelineLabel : `${pipelineLabel} · 关键词搜索 Key 待配置`;
        } else {
          chip.dataset.state = "warning";
          label.textContent = "本地服务在线 · 待补齐支持视频输入的视觉模型配置";
        }
        syncPrimaryActions();
      } catch (_) {
        runtimeMode = "offline";
        runtimeAnalysisReady = false;
        runtimeSearchReady = false;
        runtimeBlocker = "offline";
        chip.dataset.state = "offline";
        label.textContent = "实时分析暂离线 · 网站内容仍可浏览";
        syncPrimaryActions();
      }
    })();

    try {
      return await runtimeCheckPromise;
    } finally {
      runtimeCheckPromise = null;
    }
  }

  function openExternal(url) {
    if (/^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener,noreferrer");
  }

  function completeMarkdownDocument(title, content) {
    const report = String(content || "暂无报告内容").trim();
    return /^#\s+\S/.test(report) ? report : `# ${title}\n\n${report}`;
  }

  function buildReportOutline(modalContent) {
    const outline = byId("report-outline");
    outline.replaceChildren();
    const label = document.createElement("span");
    label.className = "report-outline__label";
    label.textContent = "报告目录";
    outline.appendChild(label);

    modalContent.querySelectorAll("h2").forEach((heading, index) => {
      const sectionNumber = String(index + 1).padStart(2, "0");
      heading.dataset.section = sectionNumber;
      heading.id = `report-section-${index + 1}`;
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<span>${sectionNumber}</span>${escapeHtml(heading.textContent || `第 ${index + 1} 节`)}`;
      button.addEventListener("click", () => {
        heading.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      });
      outline.appendChild(button);
    });
  }

  function setReportView(view) {
    const sourceMode = view === "source";
    const toggle = byId("source-toggle-btn");
    const copyButton = byId("copy-source-btn");
    byId("report-reading").hidden = sourceMode;
    byId("markdown-source").hidden = !sourceMode;
    toggle.setAttribute("aria-pressed", String(sourceMode));
    toggle.textContent = sourceMode ? "返回阅读视图" : "查看 MD 源码";
    copyButton.hidden = !sourceMode;
    if (sourceMode) byId("modal-source").parentElement.focus();
  }

  function toggleMarkdownSource() {
    setReportView(!byId("markdown-source").hidden ? "reading" : "source");
  }

  function openModal(title, content) {
    const modal = byId("modal");
    const reportShell = modal.querySelector(".report-shell");
    lastModalTrigger = document.activeElement;
    currentModalMarkdown = completeMarkdownDocument(title, content);
    byId("modal-title").textContent = title;
    const report = content || "暂无报告内容";
    const rendered = window.marked ? window.marked.parse(report) : escapeHtml(report);
    const modalContent = byId("modal-content");
    modalContent.innerHTML = sanitizeReportHtml(rendered);
    modalContent.querySelectorAll("table").forEach((table, index) => {
      const scroller = document.createElement("div");
      scroller.className = "report-table-scroll";
      scroller.tabIndex = 0;
      scroller.setAttribute("role", "region");
      scroller.setAttribute("aria-label", `报告表格 ${index + 1}`);
      table.before(scroller);
      scroller.appendChild(table);
    });
    buildReportOutline(modalContent);
    byId("modal-source").textContent = currentModalMarkdown;
    const lineCount = currentModalMarkdown.split(/\r?\n/).length;
    byId("source-stats").textContent = `${lineCount} 行 · ${currentModalMarkdown.length.toLocaleString("zh-CN")} 字符`;
    byId("copy-status").textContent = "源码与当前阅读视图完全一致。";
    byId("copy-status").dataset.state = "idle";
    setReportView("reading");

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

  async function copyMarkdownSource() {
    const button = byId("copy-source-btn");
    const status = byId("copy-status");
    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = "正在复制";

    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(currentModalMarkdown);
      } else {
        const fallback = document.createElement("textarea");
        fallback.value = currentModalMarkdown;
        fallback.setAttribute("readonly", "");
        fallback.style.position = "fixed";
        fallback.style.opacity = "0";
        document.body.appendChild(fallback);
        fallback.select();
        const copied = document.execCommand("copy");
        fallback.remove();
        if (!copied) throw new Error("浏览器拒绝访问剪贴板");
      }
      button.textContent = "已复制";
      status.textContent = "完整 Markdown 已复制，可直接粘贴到飞书文档或 Obsidian。";
      status.dataset.state = "success";
      window.setTimeout(() => {
        button.textContent = previousLabel;
        button.disabled = false;
      }, 2200);
    } catch (error) {
      button.textContent = "复制失败";
      button.disabled = false;
      status.textContent = `没有复制：${error.message}。你仍可在上方手动全选源码。`;
      status.dataset.state = "error";
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
    analyzeButton.textContent = isBusy ? "正在拉片" : primaryActionLabel(false);
    byId("results")?.setAttribute("aria-busy", String(isBusy));
  }

  function handleAnalyzeAction(refresh = false) {
    const source = byId("keyword")?.value.trim() || "";
    if (!runtimeAnalysisReady) {
      const configurationMissing = ["server_config_missing", "local_config_missing"].includes(runtimeBlocker);
      showInlineError(configurationMissing
        ? "分析服务已经在线，但当前标签页没有可用的视觉模型配置。请在本标签页打开设置，填写后点击“保存并返回分析页”；新标签页不会共享 Key。"
        : "实时分析服务当前离线。网站内容与方法仍可浏览，服务恢复后可直接在这里开始分析。");
      byId("analysis-studio")?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
      return;
    }
    if (!isDirectVideoSource(source) && !runtimeSearchReady) {
      showInlineError("直链分析已经就绪；关键词发现还缺少 RapidAPI Key。同一把 Key 用于已订阅的多源搜索链，你也可以先粘贴视频直链。");
      byId("keyword")?.focus();
      return;
    }
    analyze(refresh);
  }

  function videoSourceUrl(video) {
    const source = String(video?.source_url || "").trim();
    if (source) return source;
    const author = String(video?.author || "").trim();
    const videoId = String(video?.video_id || "").trim();
    return author && videoId ? `https://www.tiktok.com/@${author}/video/${videoId}` : "";
  }

  function stableVideoKey(video) {
    const videoId = String(video?.video_id || "").trim();
    if (videoId) return `video:${videoId}`;
    const source = videoSourceUrl(video);
    const pathVideoId = source.match(/\/video\/([^/?#]+)/i)?.[1];
    if (pathVideoId) return `video:${pathVideoId}`;
    if (source) return `source:${source.toLowerCase()}`;
    return `fallback:${String(video?.author || "").trim().toLowerCase()}|${String(video?.title || "").trim().toLowerCase()}`;
  }

  async function consumeAnalysisStream(requestBody, onPayload, endpoint = "/api/analyze") {
    const response = await apiFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    if (!response.ok) {
      const rawError = await response.text();
      let message = `服务返回 HTTP ${response.status}`;
      try {
        const payload = JSON.parse(rawError);
        if (payload?.message) message = payload.message;
      } catch (_) {
        if (rawError.trim()) message = `${message}：${rawError.trim().substring(0, 240)}`;
      }
      const responseError = new Error(message);
      responseError.status = response.status;
      throw responseError;
    }

    let terminal = false;
    let malformedLine = false;
    const parseLine = (line) => {
      const cleanLine = line.replace(/\r/g, "").trim();
      if (!cleanLine) return;
      let payload;
      try {
        payload = JSON.parse(cleanLine);
      } catch (error) {
        malformedLine = true;
        console.warn("NDJSON parse error:", error, cleanLine.substring(0, 120));
        return;
      }
      if (terminal) return;
      const isTerminal = Boolean(payload.done) || ["success", "error"].includes(payload.status);
      if (isTerminal) terminal = true;
      onPayload(payload);
    };

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

    if (malformedLine) {
      throw new Error("分析流包含无法解析的数据，结果可能不完整");
    }
    if (!terminal) {
      throw new Error("分析流提前结束，未收到完成信号");
    }
  }

  function looksLikeGroundedReport(value) {
    const report = String(value || "").trim();
    const professional = report.includes("## 证据覆盖") && /\[SHOT:S\d{3}\]/.test(report);
    const direct = report.includes("## 目标产品核验")
      && /\[TARGET:(?:visible|not_visible|uncertain)\]/.test(report)
      && /\[VIDEO:\d{1,2}:\d{2}(?:\.\d+)?-\d{1,2}:\d{2}(?:\.\d+)?\]/.test(report);
    return (professional || direct)
      && /\[META:[^\]]+\]/.test(report)
      ;
  }

  function conciseFailureMessage(video) {
    const groundingIssue = String(video.model_grounding_error || "").trim();
    if (groundingIssue) return `最终报告未通过证据校验：${groundingIssue}。`;

    const report = String(video.ai_analysis || "").trim();
    if (looksLikeGroundedReport(report)) {
      return "模型报告已经返回，但旧状态被误标为失败；报告本身仍可打开核对。";
    }

    const firstLine = report
      .split(/\r?\n/)
      .map((line) => line.replace(/^#{1,6}\s*/, "").replace(/[|*_`]/g, "").trim())
      .find(Boolean);
    return (firstLine || "分析链没有完成").substring(0, 220);
  }

  function renderVideoCard(video, index) {
    const videoUrl = videoSourceUrl(video);
    const analysisId = `analysis-${Date.now()}-${index}`;
    const remakeId = `remake-${Date.now()}-${index}`;
    const provider = String(video.analysis_provider || "model").toLowerCase();
    const status = video.shot_status || video.libtv_status || "";
    const modelStatus = video.model_status || "";
    const acquisitionProvider = video.acquisition_provider || "";
    const acquisitionStatus = video.tk_note_status || video.video_ingest_status || "";
    const lifecycleLabel = (value, labels) => {
      const normalized = String(value || "").toLowerCase();
      if (["completed", "complete", "success", "reused"].includes(normalized)) return labels.completed;
      if (normalized === "partial") return labels.partial || labels.completed;
      if (["running", "pending", "timeout"].includes(normalized)) return labels.running;
      if (["error", "blocked", "failed"].includes(normalized)) return labels.failed;
      if (["not_run", "not_used", "skipped", ""].includes(normalized)) return labels.notRun;
      return labels.unknown;
    };
    const acquisitionName = acquisitionProvider === "tk-note" ? "TK Note" : acquisitionProvider || "视频采集";
    const acquisitionLabel = `${acquisitionName} · ${lifecycleLabel(acquisitionStatus, {
      completed: "已采集", partial: "部分采集", running: "采集中", failed: "采集失败", notRun: "未运行", unknown: "状态未知",
    })}`;
    const providerName = {
      openai: "OpenAI",
      anthropic: "Claude",
      gemini: "Gemini",
      deepseek: "DeepSeek",
      openrouter: "OpenRouter",
      custom: "自定义模型",
    }[provider] || provider;
    const shotProvider = video.shot_provider === "direct-video" ? "原片视觉"
      : video.shot_provider === "libtv" ? "LibTV"
        : video.shot_provider === "shotloom" ? "ShotLoom" : "镜头证据";
    const shotLabel = `${shotProvider} · ${lifecycleLabel(status, {
      completed: "已完成", running: "处理中", failed: "已阻断", notRun: "未运行", unknown: "状态未知",
    })}`;
    const legacyReportRecovered = video.pipeline_status !== "completed"
      && modelStatus === "error"
      && Object.prototype.hasOwnProperty.call(video, "model_grounding_error")
      && !video.model_grounding_error
      && looksLikeGroundedReport(video.ai_analysis);
    const effectiveModelStatus = legacyReportRecovered ? "completed" : modelStatus;
    const providerLabel = `${providerName} · ${lifecycleLabel(effectiveModelStatus, {
      completed: "最终分析", running: "分析中", failed: "分析失败", notRun: "未运行", unknown: "状态未知",
    })}`;
    const projectUrl = /^https?:\/\//i.test(video.libtv_project_url || "") ? video.libtv_project_url : "";
    const pipelineFailed = Boolean(video.pipeline_status && video.pipeline_status !== "completed" && !legacyReportRecovered);
    const canResumeFinal = pipelineFailed
      && video.resumable_stage === "final-analysis"
      && video.retry_scope === "model-only"
      && Boolean(video.task_id);
    const failureMessage = pipelineFailed ? conciseFailureMessage(video) : "";
    const failureTitle = video.pipeline_stage === "collection"
      ? "原片采集没有完成"
      : video.pipeline_stage === "shot-analysis"
        ? (video.shot_provider === "direct-video" ? "原片视觉准备没有完成" : "专业镜头索引没有完成")
        : video.pipeline_stage === "final-analysis"
          ? "证据终审没有完成"
          : "分析没有完成";
    const recoveryLabel = video.pipeline_stage === "collection"
      ? "检查采集设置"
      : video.pipeline_stage === "final-analysis"
        ? "检查模型设置"
        : "检查视觉模型";

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
        <span class="provider-badge ${escapeHtml(acquisitionStatus || "not_run")}">${escapeHtml(acquisitionLabel)}</span>
        <span class="provider-badge ${escapeHtml(status || "not_run")}">${escapeHtml(shotLabel)}</span>
        <span class="provider-badge ${escapeHtml(effectiveModelStatus || "not_run")}">${escapeHtml(providerLabel)}</span>
      </div>
      ${failureMessage ? `<div class="video-card__error" role="alert"><strong>${escapeHtml(failureTitle)}</strong><span>${escapeHtml(failureMessage)}</span></div>` : ""}
      ${canResumeFinal ? `<p class="video-card__checkpoint">原片与证据检查点保留至 ${escapeHtml(checkpointExpiryLabel(video.checkpoint_expires_at))}。仅再次调用模型，不会重新下载原片或重复专业镜头取证。</p>` : ""}
      <div class="card-actions">
        ${pipelineFailed ? `<button class="retry-video-btn" type="button">${canResumeFinal ? "仅重试终审" : "重试这条视频"}</button>` : ""}
        <button class="analysis-btn" type="button">${pipelineFailed ? "查看失败详情" : "打开最终分析"}</button>
        ${pipelineFailed && !video.model_grounding_error ? `<a class="project-link" href="/settings">${recoveryLabel}</a>` : ""}
        ${projectUrl ? `<a class="project-link" href="${escapeHtml(projectUrl)}" target="_blank" rel="noopener noreferrer">打开项目画布</a>` : ""}
      </div>
      <p class="video-card__retry-status" role="status" aria-live="polite" hidden></p>
      <div id="${analysisId}" hidden>${escapeHtml(video.ai_analysis || "")}</div>
    `;

    card.querySelector(".video-title").addEventListener("click", () => openExternal(videoUrl));
    card.querySelector(".analysis-btn").addEventListener("click", () => showAnalysis(analysisId, provider));
    const retryButton = card.querySelector(".retry-video-btn");
    if (retryButton) retryButton.addEventListener("click", () => retryVideo(video, card, retryButton));

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

  async function retryVideo(video, card, button) {
    const source = videoSourceUrl(video);
    const retryStatus = card.querySelector(".video-card__retry-status");
    const finalOnly = video.resumable_stage === "final-analysis"
      && video.retry_scope === "model-only"
      && Boolean(video.task_id);
    if (!finalOnly && !isDirectVideoSource(source)) {
      showInlineError("这条结果没有可重试的真实视频直链。请重新运行关键词搜索获取有效来源。");
      return;
    }

    const refresh = !finalOnly && video.pipeline_stage === "collection";
    const searchQuery = String(video.search_query || "").trim();
    const retryThroughSearch = refresh && searchQuery && Boolean(video.video_id);
    let retriedVideo = null;
    let terminalError = "";
    clearInlineError();
    button.disabled = true;
    button.textContent = "正在重试";
    card.dataset.retrying = "true";
    retryStatus.hidden = false;
    retryStatus.textContent = finalOnly
      ? "正在复用服务端证据检查点，仅重试模型终审…"
      : retryThroughSearch
        ? "正在重新搜索同一条视频并补全可下载媒体地址…"
        : refresh ? "正在重新采集原片与字幕证据…" : "正在复用已采集证据并重跑视觉终审…";
    updateProgress(retryStatus.textContent.replace("…", ""), finalOnly ? 86 : refresh ? 24 : 48);

    try {
      const requestBody = finalOnly ? {} : {
        keyword: retryThroughSearch ? searchQuery : source,
        refresh,
        target_video_id: retryThroughSearch ? String(video.video_id) : "",
        product_name: byId("product-name")?.value || "",
        product_info: byId("product-info")?.value || "",
      };
      const endpoint = finalOnly ? `/api/tasks/${encodeURIComponent(video.task_id)}/resume` : "/api/analyze";
      await consumeAnalysisStream(requestBody, (data) => {
        if (data.stage) setPipelineStage(data.stage, data.stage_status || "running");
        if (data.stage_label) updateProgress(data.stage_label, data.stage_progress || 0);
        if (data.video) retriedVideo = data.video;
        if (data.status === "error") terminalError = data.message || "单条重试没有完成";
      }, endpoint);
      if (terminalError) throw new Error(terminalError);
      if (!retriedVideo) throw new Error("重试完成但没有返回视频结果");

      const replacement = renderVideoCard(retriedVideo, Date.now());
      card.replaceWith(replacement);
      updateProgress("这条视频已完成重试", 100);
      replacement.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    } catch (error) {
      failActiveStage();
      retryStatus.textContent = `重试失败：${error.message}`;
      showInlineError(`这条视频没有完成重试：${error.message}。已保留原失败记录，可检查对应设置后再次重试。`);
      button.disabled = false;
      button.textContent = "再次重试";
      delete card.dataset.retrying;
      checkRuntime({ silent: true });
    }
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
    resultRevealHandled = false;
    resetPipelineStages();
    updateResultCount(0, "管线运行中");
    updateProgress("正在启动完整证据链", 2);

    const streamContainer = document.createElement("div");
    streamContainer.id = "stream-results";
    streamContainer.className = "results-list";
    results.appendChild(streamContainer);
    window.requestAnimationFrame(() => revealSection("pipeline-title", "center"));

    const resultCards = new Map();
    let streamFailed = false;

    const handlePayload = (data) => {
      if (data.status === "error") {
        streamFailed = true;
        showInlineError(data.message || "分析没有完成，请检查来源后重试。", data);
        failActiveStage();
        updateProgress("分析链已中断", data.stage_progress || 0);
        updateResultCount(resultCards.size, "管线失败");
        return;
      }

      if (data.status === "progress" && !data.done) {
        if (data.stage) setPipelineStage(data.stage, data.stage_status || "running");
        updateProgress(data.stage_label || "证据链正在运行", data.stage_progress || 0);
        if (data.video) {
          const key = stableVideoKey(data.video);
          const previous = resultCards.get(key);
          const card = renderVideoCard(data.video, resultCards.size);
          if (previous?.isConnected) previous.replaceWith(card);
          else streamContainer.appendChild(card);
          resultCards.set(key, card);
          updateResultCount(resultCards.size);
          revealFirstResult();
        }
        return;
      }

      if (data.done || data.status === "success") {
        const failed = data.failed_videos || 0;
        const pending = data.pending_videos || 0;
        const total = data.total_videos || resultCards.size;
        const completed = Math.max(total - failed - pending, 0);
        const summary = failed || pending
          ? `处理结束：${completed} 条完成，${pending} 条处理中，${failed} 条失败`
          : `完整分析完成，共 ${total} 条视频`;
        updateProgress(summary, 100);
        updateResultCount(resultCards.size, summary);
      }
    };

    try {
      await consumeAnalysisStream({ keyword, refresh, product_name: productName, product_info: productInfo }, handlePayload);
    } catch (error) {
      failActiveStage();
      let hint;
      if (error.status === 504) {
        hint = "长任务被中转网关提前截断。请刷新页面切换到直连分析服务后重新开始；Worker 本身可能仍在继续运行。";
      } else if (runtimeMode === "worker") {
        hint = "实时分析服务可能刚刚离线，请稍后重试。";
      } else {
        hint = "请确认本地服务仍在运行后重试。";
      }
      showInlineError(`分析没有完成：${error.message}。${hint}`);
      updateResultCount(resultCards.size, "连接中断");
      checkRuntime({ silent: true });
    } finally {
      setBusy(false);
      loading.hidden = true;
      if (streamFailed) checkRuntime({ silent: true });
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
    byId("source-toggle-btn").addEventListener("click", toggleMarkdownSource);
    byId("copy-source-btn").addEventListener("click", copyMarkdownSource);
    byId("keyword").addEventListener("input", syncPrimaryActions);
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
    window.setInterval(() => checkRuntime({ silent: true }), RUNTIME_RECHECK_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") checkRuntime({ silent: true });
    });
    loadKeywords();
    resetPipelineStages();
    updateProgress("等待视频来源", 0);
  });
})();
