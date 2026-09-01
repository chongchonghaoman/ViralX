(() => {
  "use strict";

  let currentModalTitle = "";
  let currentModalContent = "";
  let lastModalTrigger = null;
  let runtimeMode = "unknown";
  let runtimeAnalysisReady = false;
  let runtimeSearchReady = false;
  let runtimeBlocker = "checking";
  let resultRevealHandled = false;

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
    const actionable = renderSubscriptionRecovery(error, message, payload);
    error.hidden = false;
    error.focus({ preventScroll: !actionable });
    if (actionable) {
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      error.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    }
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
      action.textContent = primaryActionLabel(action.classList.contains("nav-cta"));
    });
    const analyzeButton = byId("analyze-btn");
    if (analyzeButton && !analyzeButton.disabled) {
      analyzeButton.textContent = primaryActionLabel(false);
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
      runtimeAnalysisReady = Boolean(data.analysis_ready);
      runtimeSearchReady = Boolean(data.configured?.keyword_search);
      if (runtimeMode === "worker") {
        runtimeBlocker = runtimeAnalysisReady
          ? (runtimeSearchReady ? "ready" : "search_config_missing")
          : "server_config_missing";
        chip.dataset.state = runtimeAnalysisReady && runtimeSearchReady ? "ready" : "warning";
        label.textContent = runtimeAnalysisReady && runtimeSearchReady
          ? "完整分析在线 · 关键词搜索 → TK Note → ShotLoom + 视觉模型"
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
          : `本地完整链路就绪 · TK Note → ${shot.engine === "libtv" ? "LibTV" : "ShotLoom + 视觉模型"} → 证据终审`;
        label.textContent = runtimeSearchReady ? pipelineLabel : `${pipelineLabel} · 关键词搜索 Key 待配置`;
      } else {
        chip.dataset.state = "warning";
        label.textContent = "本地服务在线 · 待补齐 ShotLoom 与视觉模型配置";
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

  function renderVideoCard(video, index) {
    const videoUrl = video.source_url || `https://www.tiktok.com/@${video.author}/video/${video.video_id}`;
    const analysisId = `analysis-${Date.now()}-${index}`;
    const remakeId = `remake-${Date.now()}-${index}`;
    const provider = String(video.analysis_provider || "model").toLowerCase();
    const status = video.shot_status || video.libtv_status || "";
    const modelStatus = video.model_status || "";
    const acquisitionProvider = video.acquisition_provider || "";
    const acquisitionStatus = video.tk_note_status || video.video_ingest_status || "";
    const acquisitionFailed = ["error", "blocked"].includes(acquisitionStatus);
    const acquisitionLabel = acquisitionProvider === "tk-note"
      ? acquisitionFailed ? "TK Note · 采集失败" : "TK Note · 已采集"
      : acquisitionProvider
        ? `${acquisitionProvider} · ${acquisitionFailed ? "采集失败" : "已采集"}`
        : "";
    const providerName = {
      openai: "OpenAI",
      anthropic: "Claude",
      gemini: "Gemini",
      deepseek: "DeepSeek",
      openrouter: "OpenRouter",
      custom: "自定义模型",
    }[provider] || provider;
    const shotProvider = video.shot_provider === "libtv" ? "LibTV" : video.shot_provider === "shotloom" ? "ShotLoom" : "镜头证据";
    const shotLabel = ["error", "blocked"].includes(status)
      ? `${shotProvider} · 已阻断`
      : status === "timeout" || status === "pending"
        ? `${shotProvider} · 处理中`
        : `${shotProvider} · 已完成`;
    const providerLabel = ["error", "blocked"].includes(modelStatus)
      ? `${providerName} · 分析失败`
      : `${providerName} · 最终分析`;
    const projectUrl = /^https?:\/\//i.test(video.libtv_project_url || "") ? video.libtv_project_url : "";
    const pipelineFailed = video.pipeline_status && video.pipeline_status !== "completed";
    const failureMessage = pipelineFailed ? String(video.ai_analysis || "分析链没有完成") : "";

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
        <span class="provider-badge ${escapeHtml(status)}">${escapeHtml(shotLabel)}</span>
        <span class="provider-badge ${escapeHtml(modelStatus)}">${escapeHtml(providerLabel)}</span>
      </div>
      ${failureMessage ? `<p class="video-card__error" role="alert">${escapeHtml(failureMessage.substring(0, 600))}</p>` : ""}
      <div class="card-actions">
        <button class="analysis-btn" type="button">打开最终分析</button>
        ${["error", "blocked"].includes(status) ? runtimeMode === "edgeone" ? '<span class="project-link">镜头证据未就绪</span>' : '<a class="project-link" href="/settings">检查镜头取证设置</a>' : ""}
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
    resultRevealHandled = false;
    resetPipelineStages();
    updateResultCount(0, "管线运行中");
    updateProgress("正在启动完整证据链", 2);

    const streamContainer = document.createElement("div");
    streamContainer.id = "stream-results";
    streamContainer.className = "results-list";
    results.appendChild(streamContainer);
    window.requestAnimationFrame(() => revealSection("pipeline-title", "center"));

    let received = 0;
    let done = false;

    const handlePayload = (data) => {
      if (data.status === "error") {
        showInlineError(data.message || "分析没有完成，请检查来源后重试。", data);
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
          revealFirstResult();
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
      const hint = runtimeMode === "worker"
        ? "实时分析服务可能刚刚离线，请稍后重试"
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
    loadKeywords();
    resetPipelineStages();
    updateProgress("等待视频来源", 0);
  });
})();
