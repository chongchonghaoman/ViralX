# 贡献指南

产品说明见 [README](../README.md)，运行与配置见 [使用指南](../docs/USAGE.md)。以下命令均从仓库根目录执行。

## 如何贡献

### 报告 Bug

- 在 GitHub Issues 中创建新 issue
- 清楚描述问题和复现步骤
- 提供环境信息（Python 版本、OS 等）

### 提交功能建议

- 在 GitHub Discussions 中讨论
- 或创建 issue 标记为 `enhancement`

### 提交代码

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 代码规范

- 使用 PEP 8 风格
- 添加必要的注释和文档
- 确保代码能正常运行

## 提交前检查

从仓库当前默认分支创建功能分支，提交前运行：

```bash
python -m unittest discover -s tests -v
npm run build:edgeone
git diff --check
```

保持网页、Worker、Agent Skill 和原片证据链的兼容性。业务代码放在 `viralx/`，内部使用包内导入；项目资源通过 `viralx.paths.PROJECT_ROOT` 定位，不依赖当前工作目录或模块所在目录。移动文件时同时验证兼容入口、Flask 资源路径及 EdgeOne 发布包，不能只改文件位置。

不要提交 `config.json`、API Key、Cookie、代理凭据、部署凭据、下载视频、分析缓存或个人文件路径。发布前检查暂存区，测试通过后再合并；CI 通过不代表第三方服务始终可用。

## 许可证

提交代码即表示你同意在 MIT 许可证下发布你的贡献。
