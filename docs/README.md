# 文档索引

| 文档 | 用途 |
| --- | --- |
| [产品 README](../README.md) | 产品能力、最新工作逻辑与使用入口 |
| [使用指南](USAGE.md) | 本地运行、Worker、配置与故障排查 |
| [设计合同](DESIGN.md) | 视觉、交互与状态约束 |
| [贡献指南](../.github/CONTRIBUTING.md) | 提交规范、测试与凭据保护 |
| [第三方许可](THIRD_PARTY_NOTICES.md) | 第三方适配与资产许可说明 |
| [工作流程图](assets/viralx-workflow.svg) | 当前五阶段流程与失败恢复 |
| [流程图 Mermaid 源码](assets/viralx-workflow.mmd) | 可编辑的流程定义 |

文档中的代码路径和命令工作目录默认指仓库根目录。网页截图与流程图统一保存在 `docs/assets/`，网站实际使用的资源保存在 `static/assets/`。

Python 实现统一位于 `viralx/`。根目录只保留兼容启动入口；`web_app`、`worker_server` 的旧导入仍指向同一实现模块。内部模块请使用 `viralx.*` 导入。

配置示例位于 `config/`，可选依赖位于 `requirements/`。用户的 `config.json`、下载文件、缓存、模板与静态资源仍按原项目根目录定位，由 `viralx/paths.py` 统一维护。
