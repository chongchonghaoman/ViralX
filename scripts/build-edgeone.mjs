import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const publicDir = join(projectRoot, "public");
const publicStatic = join(publicDir, "static");
const publicFunctions = join(publicDir, "cloud-functions");

await rm(publicDir, { recursive: true, force: true });
await mkdir(join(publicStatic, "assets"), { recursive: true });

let html = await readFile(join(projectRoot, "templates", "index.html"), "utf8");
html = html
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-deployment="edgeone">')
  .replaceAll("{{ url_for('static', filename='tokens.css') }}", "/static/tokens.css")
  .replaceAll("{{ url_for('static', filename='viralx.css') }}", "/static/viralx.css")
  .replaceAll("{{ url_for('static', filename='assets/viralx-signal-orbit-640.webp') }}", "/static/assets/viralx-signal-orbit-640.webp")
  .replaceAll("{{ url_for('static', filename='assets/viralx-signal-orbit-1024.webp') }}", "/static/assets/viralx-signal-orbit-1024.webp")
  .replaceAll("{{ url_for('static', filename='assets/viralx-signal-orbit.png') }}", "/static/assets/viralx-signal-orbit.png")
  .replaceAll("{{ url_for('static', filename='assets/viralx-title-shuei-wide.svg') }}", "/static/assets/viralx-title-shuei-wide.svg")
  .replaceAll("{{ url_for('static', filename='assets/viralx-title-shuei-stacked.svg') }}", "/static/assets/viralx-title-shuei-stacked.svg")
  .replaceAll("{{ url_for('static', filename='cloud-config.js') }}", "/static/cloud-config.js")
  .replaceAll("{{ url_for('static', filename='viralx.js') }}", "/static/viralx.js")
  .replaceAll('href="/settings"', 'href="/settings.html"')
  .replaceAll('href="/"', 'href="#main-content"')
  .replace("本地分析服务", "EdgeOne 云端分析")
  .replace("本地设置", "网页设置")
  .replace("LOCAL-FIRST · 2026", "EDGE + LOCAL · 2026");

await writeFile(join(publicDir, "index.html"), html, "utf8");

let settingsHtml = await readFile(join(projectRoot, "templates", "settings.html"), "utf8");
settingsHtml = settingsHtml
  .replace('<html lang="zh-CN">', '<html lang="zh-CN" data-deployment="edgeone">')
  .replaceAll("{{ url_for('static', filename='tokens.css') }}", "/static/tokens.css")
  .replaceAll("{{ url_for('static', filename='viralx.css') }}", "/static/viralx.css")
  .replaceAll("{{ url_for('static', filename='settings.css') }}", "/static/settings.css")
  .replaceAll("{{ url_for('static', filename='cloud-config.js') }}", "/static/cloud-config.js")
  .replaceAll("{{ url_for('static', filename='settings.js') }}", "/static/settings.js")
  .replace("配置留在本地；证据留在你的工作区。", "密钥留在当前标签页；请求只发往 ViralX 云函数。")
  .replace("静态 EdgeOne 展示", "EdgeOne 云函数")
  .replace("LOCAL-FIRST · 2026", "SESSION-FIRST · EDGEONE · 2026");
await writeFile(join(publicDir, "settings.html"), settingsHtml, "utf8");

await cp(join(projectRoot, "static", "tokens.css"), join(publicStatic, "tokens.css"));
await cp(join(projectRoot, "static", "viralx.css"), join(publicStatic, "viralx.css"));
await cp(join(projectRoot, "static", "settings.css"), join(publicStatic, "settings.css"));
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
await cp(join(projectRoot, "static", "viralx.js"), join(publicStatic, "viralx.js"));

await cp(join(projectRoot, "cloud-functions"), publicFunctions, { recursive: true });
for (const moduleName of [
  "ai_analyzer.py",
  "model_providers.py",
  "video_ingest.py",
  "libtv_analyzer.py",
  "tiktok_viral_analyzer.py",
]) {
  await cp(join(projectRoot, moduleName), join(publicFunctions, moduleName));
}
await cp(
  join(projectRoot, ".agents", "skills", "tk-note", "scripts"),
  join(publicFunctions, "vendor", "tk_note"),
  { recursive: true },
);
await cp(
  join(projectRoot, ".agents", "skills", "libtv-skill", "scripts"),
  join(publicFunctions, "vendor", "libtv"),
  { recursive: true },
);

console.log("EdgeOne web + Cloud Functions build ready:", publicDir);
