# PaperQuay 与 PaperPilot 统一界面的接入记录

参照固定为 [WangQrkkk/PaperQuay](https://github.com/WangQrkkk/PaperQuay/tree/1d65fdbfe0eb7ef33c57cf8b9d87b6afdb5f06bf)，版本 0.1.25，提交 `1d65fdbfe0eb7ef33c57cf8b9d87b6afdb5f06bf`。本地参照目录被 Git 忽略，不进入 Docker 上下文。

## 复用判断

已阅读上游 LICENSE、主题、文献库、标签、ReaderWorkspace、PdfViewer、AssistantSidebar 和 PDF 文件源适配；对照 `docs/assets/main.png`、`agent.png`。上游为 AGPL-3.0-only。PaperPilot 根 LICENSE 为 CC BY-NC 4.0，Python classifier 仍标为 MIT；classifier 不能替代授权文本。

直接搬入上游 React 组件会形成需要核查的组合代码。上游 AGPL 第 5、10、13 节涉及整体许可、不得增加限制和网络使用的源码提供；现有 [CC BY-NC 第 2 节](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en)则限制为非商业使用。未发现覆盖双方相关权利人的额外授权，不能通过分目录或只修改一个许可证声明就确认该组合可以发布。因此本次没有复制上游组件源码、CSS、图标或截图进发行包，也没有修改项目许可证。以下采用独立代码重现其布局、信息组织与操作流程；这是一项具体的复用决策，不是对现有项目所有许可问题的法律结论。将来直接代码复用仍须另行明确授权路径。

## 逐项映射

| 上游参照 | 本地实现与适配 | 后端与浏览器差异 |
|---|---|---|
| `src/app/index.css`、`literatureUi.tsx` | `frontend/src/style.css`、`ui.tsx`，独立 CSS token、细边框、中性浅深主题、青绿色强调、中文控件 | 系统字体与自托管 CSS；不引入上游 Electron 主题状态 |
| `LiteratureCategorySidebar.tsx` | `Library.tsx`，功能栏、分类、收藏、Reading List，初始分类栏 248px、可调整宽度 | `/api/categories` 及现有分类 CRUD；owner 虚拟根，资产 ID 不变 |
| `LiteraturePaperList.tsx` | 紧凑标题/作者/年份/状态、搜索排序、单击预览、双击/按钮阅读、批量操作 | 现有全量列表 API，客户端每页 50 条；不宣称服务端分页 |
| `LiteraturePaperDetails.tsx` | 420px 初始详情栏、摘要/状态/元数据、原文译文、任务动作 | 复用论文详情、编辑、收藏、Reading List、翻译、分析接口 |
| `components/tabs/TabBar.tsx` | `main.tsx`，论文标签、关闭与切换，服务端保存工作区偏好 | 不复用 Electron 工作区数据库；owner 设置保存，不新增表 |
| `ReaderWorkspace.tsx`、`PdfViewerToolbar.tsx` | `Reader.tsx`，填满剩余高度的阅读区、紧凑工具栏、折叠缩略图、可调整问答侧栏 | 同源授权 URL，原文/译文分别定位；无桌面自定义协议和磁盘路径 |
| `PdfViewer.tsx`、PDF document source | 独立 PDF.js 按可见范围渲染与生命周期；复用官方 PDF.js 包 | matching legacy display/worker 修复 Edge 139；资源自托管，保留严格脚本 CSP |
| `AssistantSidebar.tsx`、聊天呈现 | `Chat.tsx`，历史/多会话、流式回答、引用卡片、选择文字后确认发送 | 保留首行会话 JSON + 原始文本流；服务端模型配置；停止接收不等于服务端取消 |
| 桌面文件选择、IPC、设置 | `Transfers.tsx`、`Settings.tsx`，浏览器文件选择/拖放、现有 HTTP API | 不暴露主机路径、密钥、Electron IPC 或未实现工具入口 |
| 桌面无对应的多用户登录与 Daily | `Auth.tsx`、`Daily.tsx`、`DiscoverySettings.tsx`，沿用同一设计体系 | 保留现有 PaperPilot 身份、Daily、机构配置与用户资产 |

上表是源码接入记录。视觉、交互和正式部署是否通过，必须以本次验收记录为准，不能以组件名或截图数量代替。

## 发行依赖

实际依赖版本及来源见 `frontend/DEPENDENCIES.json`，完整性来自 npm lockfile。React、React DOM、Scheduler、Vite 使用 MIT；PDF.js 使用 Apache-2.0；Lucide React 使用 ISC；Marked 使用 MIT；DOMPurify 为 MPL-2.0 OR Apache-2.0（本次按 Apache-2.0 路径使用）。运行依赖原始许可证随 `THIRD_PARTY_NOTICES.txt` 自托管；字体/CMap 的上游声明随发行资源保留。没有将 PaperQuay 当作上述独立 npm 包的授权来源。
