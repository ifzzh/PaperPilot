# iPaper 路线图

当前正式版本为 [1.2.0](https://github.com/ifzzh/iPaper/releases/tag/v1.2.0)。

- 已完成统一文献库、Daily arXiv、连续 PDF 阅读、独立阅读位置和侧栏问答。
- 已完成 BabelDOC 版式 PDF 与 MinerU 解析后结构化翻译共存、块级重译、版本化结果、可信来源定位及问答引用。
- 后续在同一界面分阶段接入高级 Agent、笔记、跨论文检索、综述和图谱；这些功能尚未交付。

能力边界、实际验收和兼容组件见[发布记录](docs/releases/v1.2.0.md)与[双翻译说明](docs/development/dual-translation.md)。

## 上游早期路线图（历史记录）

以下保留原有 ResPhy 历史清单，其中 Supabase 登录等不代表 iPaper 当前功能或配置要求。

## ResPhy 个性化论文阅读工具 Roadmap 计划

- [x] 后端持久化统一为 SQLite DB
- [x] 支持 AI Chat 对话，提供对话式深度论文阅读
- [x] 支持按功能模块细粒度按需配置模型
- [x] 支持对接 Supabase 后端鉴权，实现用户注册登录
- [x] UI/UX 交互优化，侧边栏显示/隐藏悬浮按钮
- [x] 支持 AI Interpreter生成文章导出为Markdown和PDF格式

