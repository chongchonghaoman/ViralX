# ViralX repository instructions

- ViralX is a web application. Do not restore an Electron or desktop-client wrapper unless the user explicitly requests a new desktop product.
- When the user asks to run or invoke ViralX, read `.agents/skills/viralx/SKILL.md` and use its bundled client.
- Preserve the API23 boundary: keyword discovery uses API23; direct video URLs skip API23 and continue through TK Note / yt-dlp.
- Keep credentials out of source files, prompts, logs, screenshots, and committed configuration. Use environment variables or the website's session-only BYOK settings.
- Preserve TK Note, LibTV, Obsidian, EdgeOne, and local Flask behavior unless the requested change explicitly targets one of those paths.
