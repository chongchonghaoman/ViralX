import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const publicDir = join(projectRoot, "public");
const publicStatic = join(publicDir, "static");
const publicFunctions = join(publicDir, "cloud-functions");
const assetVersion = "1.1.6";
const renderStaticUrls = (source) => source.replace(
  /\{\{\s*url_for\('static',\s*filename='([^']+)'(?:,\s*v='([^']+)')?\)\s*\}\}/g,
  (_match, filename, version) => `/static/${filename}${version ? `?v=${assetVersion}` : ""}`,
);
const publicApiBaseUrl = String(process.env.VIRALX_PUBLIC_API_BASE_URL || "").trim().replace(/\/+$/, "");
let publicApiOrigin = "";
if (publicApiBaseUrl) {
  const parsed = new URL(publicApiBaseUrl);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("VIRALX_PUBLIC_API_BASE_URL must be a credential-free HTTPS URL");
  }
  publicApiOrigin = parsed.origin;
}

await rm(publicDir, { recursive: true, force: true });
await mkdir(join(publicStatic, "assets"), { recursive: true });

let html = renderStaticUrls(await readFile(join(projectRoot, "templates", "index.html"), "utf8"));
html = html
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-deployment="edgeone">')
  .replaceAll('href="/settings"', 'href="/settings.html"')
  .replaceAll('href="/"', 'href="#main-content"')
  .replace("connect-src 'self'", `connect-src 'self'${publicApiOrigin ? ` ${publicApiOrigin}` : ""}`)
  .replace("本地设置", "网页设置")
  .replace("LOCAL-FIRST · 2026", "EDGE + LOCAL · 2026");

await writeFile(join(publicDir, "index.html"), html, "utf8");

let settingsHtml = renderStaticUrls(await readFile(join(projectRoot, "templates", "settings.html"), "utf8"));
settingsHtml = settingsHtml
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-deployment="edgeone">')
  .replace("connect-src 'self'", `connect-src 'self'${publicApiOrigin ? ` ${publicApiOrigin}` : ""}`)
  .replace("配置留在本地；证据留在你的工作区。", "网页负责展示与可选会话配置；完整证据链由 ViralX Worker 执行。")
  .replace("静态 EdgeOne 展示", "EdgeOne 网页 + 健康检查")
  .replace("LOCAL-FIRST · 2026", "SESSION-FIRST · EDGEONE · 2026");
await writeFile(join(publicDir, "settings.html"), settingsHtml, "utf8");

await cp(join(projectRoot, "static", "tokens.css"), join(publicStatic, "tokens.css"));
await cp(join(projectRoot, "static", "viralx.css"), join(publicStatic, "viralx.css"));
await cp(join(projectRoot, "static", "settings.css"), join(publicStatic, "settings.css"));
await writeFile(
  join(publicStatic, "runtime-config.js"),
  `window.ViralXRuntimeConfig=Object.freeze(${JSON.stringify({
    mode: publicApiBaseUrl ? "remote-worker" : "same-origin-worker",
    apiBaseUrl: publicApiBaseUrl,
    allowSessionOverrides: true,
  })});\n`,
  "utf8",
);
await cp(join(projectRoot, "static", "cloud-config.js"), join(publicStatic, "cloud-config.js"));
await cp(join(projectRoot, "static", "settings.js"), join(publicStatic, "settings.js"));
await cp(
  join(projectRoot, "static", "assets", "viralx-signal-orbit.png"),
  join(publicStatic, "assets", "viralx-signal-orbit.png"),
);
for (const width of [640, 1024]) {
  await cp(
    join(projectRoot, "static", "assets", `viralx-signal-orbit-${width}.webp`),
    join(publicStatic, "assets", `viralx-signal-orbit-${width}.webp`),
  );
}
await cp(
  join(projectRoot, "static", "assets", "viralx-title-shuei-wide.svg"),
  join(publicStatic, "assets", "viralx-title-shuei-wide.svg"),
);
await cp(
  join(projectRoot, "static", "assets", "viralx-title-shuei-stacked.svg"),
  join(publicStatic, "assets", "viralx-title-shuei-stacked.svg"),
);
await cp(
  join(projectRoot, "static", "assets", "viralx-title-shuei-stacked.webp"),
  join(publicStatic, "assets", "viralx-title-shuei-stacked.webp"),
);
await cp(join(projectRoot, "static", "viralx.js"), join(publicStatic, "viralx.js"));

await cp(join(projectRoot, "cloud-functions"), publicFunctions, { recursive: true });
for (const moduleName of [
  "ai_analyzer.py",
  "model_providers.py",
  "video_ingest.py",
  "libtv_analyzer.py",
  "shot_analyzers.py",
  "tiktok_viral_analyzer.py",
]) {
  await cp(join(projectRoot, moduleName), join(publicFunctions, moduleName));
}
await cp(
  join(projectRoot, ".agents", "skills", "tk-note", "scripts"),
  join(publicFunctions, "vendor", "tk_note"),
  { recursive: true },
);
console.log("EdgeOne web + Cloud Functions build ready:", publicDir);
