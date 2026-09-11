# PaperPilot 统一前端

1.1.3 开发线将文献库、阅读、问答、Daily、任务、设置和登录放入同一个应用。正式入口为 `/`；`/workbench` 和历史 `/viewer` 地址只作兼容跳转。`PAPERPILOT_WORKBENCH_ENABLED` 已退役，不能用于产品版本切换。运维回退使用兼容组件镜像和配置。

## 开发

Node 22；仓库根运行：

```bash
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
```

Flask 按 `static/workbench/.vite/manifest.json` 加载外部 module script 和 CSS。构建产物与 node_modules 不提交。`npm --prefix frontend run watch` 监听生成同样产物，不注入 HMR。缺失构建返回中文 503；业务 API 的可用性不依赖前端 manifest。

## 状态与资源

业务接口复用既有路由。新增的工作区偏好和原文/译文位置通过 owner 隔离的设置存储保存，不新增表或移动论文资产。文件指纹变化会重置不适用的位置。密码只供本次 PDF 解锁，不保存。退出或身份失效清空内存内容、取消请求和销毁 PDF，并通知其他标签；恢复焦点重新校验身份。

PDF.js 6.3.289 使用匹配的 legacy display/worker，以覆盖本机 Edge 139 的标准内建函数差异。详见 [故障报告](../docs/development/pdf-browser-compatibility.md)。worker、字体、CMap 和发行 WASM 资源全部自托管；`useWasm: false`，不放宽脚本 CSP。该版本已移除旧字体动态求值实现，不再提供旧 `isEvalSupported` 参数。PDF 文本定位、canvas 尺寸和拖动宽度使用 CSSOM，在严格 style-src 下通过实际浏览器核查。

长文档只渲染可见区域附近的正文和缩略图，切换文献销毁非活动文档。列表每页挂载 50 条，但 API 仍返回全量元数据。阅读时长仅在可见且获得焦点的阅读区累计。

聊天保留首行会话 JSON 加后续原始文本协议。显示经过 DOMPurify 清洗的 Markdown，移除远程图片与危险内容。选区作为现有消息正文的一部分，由用户确认发送；浏览器不接收服务端密钥。流结束核对持久历史，不自动重发；客户端停止接收不确认服务端取消。

## 隔离验收

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m pytest -m 'not integration' -q
cd frontend
npx playwright test --config playwright.unified.config.ts
```

`tests/unified_server.py` 注册完整 Flask 路由图，使用临时 SQLite、合成账号/文件和仅本进程可达的假 OpenAI 服务。监听 127.0.0.2:7191，避开正式端口；禁用 dotenv，不复制生产数据库或密钥，不调用真实模型。测试不应复用未知端口服务。合成样例与许可在 `tests/fixtures/workbench/README.md`。

本机 Edge 回归单独配置在 `playwright.edge.config.ts`。生产论文与正式验收截图仅放被忽略的受限证据目录。Docker test 和 runtime 必须使用同一前端构建产物，运行层不包含 Node/npm/node_modules。

## 来源

详见 [PaperQuay 组件接入与许可记录](../docs/development/paperquay-adaptation.md)。`DEPENDENCIES.json` 记录 npm lockfile 的版本、来源、完整性和许可证，构建同时输出许可证声明。本说明描述实现契约，发布状态与实际通过项以对应发布验收记录为准。

导入进度使用既有 SSE 接口，和聊天原始文本流分别适配；导入任务由 owner 校验并由有界执行器继承身份。
