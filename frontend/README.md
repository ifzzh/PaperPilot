# PaperPilot 实验工作台

这是 1.0.0 的前期工作台入口；包版本 `1.0.0-alpha.1` 不是正式发布号。Web/Worker 的现有版本保持不变。

## 构建与开发

需要 Node 22（本次固定镜像 22.23.2）和 npm。仓库根执行：

```bash
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
```

`static/workbench/` 包含 manifest、哈希命名的 JS/CSS 和 THIRD_PARTY_NOTICES.txt，不提交构建产物。`npm --prefix frontend run watch` 持续生成相同形式的资源，浏览器手动刷新；不使用 HMR 或另一个浏览器开发端口。

在已有**隔离开发配置**启动前设置 `PAPERPILOT_WORKBENCH_ENABLED=true`（也接受 1；false/0 关闭；未设置默认关闭，其他值启动失败）。正常启动 Flask 后，登录旧页面，点击“新版工作台（实验）”；直接入口为 `/workbench`，选择状态使用 `?paper=<id>`。首次改密仍由旧页面处理。本步未提供 development/disabled 的无账号工作台模式。

开关关闭后入口 404，旧站链接隐藏；重启应用使配置生效。缺少或无效构建产物时仅新入口返回中文 503，旧站可继续使用。生产部署配置不由本步骤改写。

页面使用同源 Cookie/CSRF，复用会话、列表/详情、原文/译文文件及聊天接口。用户内容只存内存；退出、过期或身份重验时取消读取，跨工作台标签通过 BroadcastChannel 清理。旧页面不会发送该通知；返回工作台焦点或 BFCache 恢复时重新验证。没有 BroadcastChannel 的浏览器仍在焦点恢复时重验，不承诺后台实时同步。

客户端每页 50 条，API 仍一次返回全库；这不是服务端分页。页面不启动后台模型任务或计时器。原文和译文按钮保留旧阅读器；“工作台阅读”进入自托管 PDF.js 单页阅读，译文存在性最终由文件端点判断。

## 验证

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/test_workbench.py -q
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run test:e2e
docker build --target test --tag paperpilot:workbench-test .
docker build --target runtime --tag paperpilot:workbench-web .
```

浏览器测试依赖现有 Python 测试环境 `.venv`，使用 `tests/workbench_server.py` 创建临时 SQLite 与合成用户（API 测试两位；浏览器增加独立阅读测试账号，避免触发旧列表用例的登录限流），通过真实认证/DAO/路由提供数据，关闭后清理。仅监听 **127.0.0.2:7191**，避开正式 127.0.0.1:7191；禁用 dotenv 加载，不启动 Worker 或调度器，聊天仅调用测试进程启动的回环假 OpenAI 服务，不调用外部模型。端口已被其他测试占用时测试失败，不复用未知服务。测试密码仅用于临时合成账号，不用于真实服务。

截图位于 `frontend/test-results/`。可设置 `PLAYWRIGHT_BROWSERS_PATH` 与 `npm_config_cache` 到可写缓存目录。性能输出为单次本机样本，记录浏览器、响应大小、可用的 JS heap 估计和翻页时间，不作为 SLA。

Docker frontend-build 执行 npm ci、类型检查、Vitest、生产构建和 npm audit（high 门槛），test 阶段运行完整非集成 Python 测试，Web/test 复制同一前端产物。现有 CI 的 Docker test gate 因此覆盖前端；另有独立 npm audit 步骤每次检查最新公告，避免镜像构建缓存跳过审计。浏览器验收单独执行。Node 与前端开发依赖不会复制到运行镜像。不要将未发布验证镜像推送为现有版本或 latest。

## 依赖与许可证

`package-lock.json` 固定直接与传递依赖的版本、npm 来源及 integrity；[`DEPENDENCIES.json`](DEPENDENCIES.json) 记录相同依赖集合的许可证与来源。升级时一起更新、重新审计和验证。打包的运行代码许可证随 `THIRD_PARTY_NOTICES.txt` 自托管，包含 React、React DOM、Scheduler 以及 Vite polyfill 的声明。

前端自主实现，未复制 PaperQuay 代码或品牌。项目既有许可证标记冲突按 P0 记录单独处理。使用 PDF.js 6.3.289（Apache-2.0），没有引入编辑器、新聊天协议或数据库迁移。

## 第三步：实验阅读与问答

`/workbench?paper=<id>&view=reader&document=original|translated` 恢复论文和版本；页码、缩放、旋转、聊天草稿仅在内存，刷新后重置。阅读组件按需加载，单页渲染，关闭后释放页面及 worker；可随时返回详情或旧阅读器。尚未接入阅读计时、批注、多论文标签或阅读位置保存。

PDF.js worker、CMap、标准字体及 WASM 发行资源随构建复制，自托管字体许可证随目录保留。6.3.289 的 display/worker 中没有旧动态求值字体编译器，未加载脚本 sandbox；显式 `useWasm: false` 保持现有严格脚本 CSP，不添加 wasm-unsafe-eval。当前中文、旋转和标准文本样例可读，特殊图像编码不是本次覆盖范围。DOM 尺寸使用 CSSOM 更新、文本层使用库自己的定位样式；这不等同于全站内联样式整改完成。

聊天使用首行会话 JSON 加后续原始文本，纯文本显示，不渲染 HTML/Markdown。发送后核对服务端历史；关闭、切换、停止接收只取消客户端连接，服务端是否完成以历史为准。无完成事件、取消确认或幂等协议，不自动重发。

文件路由成功/拒绝/Range/错误均使用 `Cache-Control: private, no-store` 与 `Vary: Cookie`。文件路径先完成隔离校验，再将合法路径的缺失情况归为 404；非法路径仍为 409。客户端分页仍不减少全量列表响应。

新增验证：`pytest tests/test_workbench_reader.py`、`frontend/src/chat-stream.test.ts` 和 `frontend/tests/reader.spec.ts`。样例与来源见 `tests/fixtures/workbench/README.md`，不运行 ReportLab 于 Web。假模型只在测试专用策略下访问本进程分配的精确回环地址，清除测试子进程代理变量，不改变生产出站策略。完整第三步证据记录于被忽略的 `.devnotes/paperquay-step3-reader.md`。
