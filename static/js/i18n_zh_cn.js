(function () {
    'use strict';

    const messages = new Map(Object.entries({
        'PaperPilot - Agentic Paper Reading': 'PaperPilot - 智能论文阅读',
        'AI Interpretation - PaperPilot': 'AI 解读 - PaperPilot', 'PDF Viewer': 'PDF 阅读器',
        'Paper': '论文', 'My Library': '我的论文库', 'Paper Info': '论文信息',
        'Select a category to view PDFs': '选择分类以查看 PDF',
        'Select a category on the left to view PDF files': '请在左侧选择分类以查看 PDF 文件',
        'Select a paper to view details': '选择论文以查看详情',
        'Sort:': '排序：', 'Upload time ↓': '上传时间 ↓', 'Upload time ↑': '上传时间 ↑',
        'Published date ↓': '发表日期 ↓', 'Published date ↑': '发表日期 ↑',
        'Authors A-Z': '作者 A-Z', 'Authors Z-A': '作者 Z-A',
        'Reading list': 'Reading List', 'Selected 0 items': '已选择 0 项',
        'Cancel': '取消', 'Confirm': '确认', 'Title': '标题', 'Close': '关闭',
        'Sync': '同步', 'Fetching papers...': '正在获取论文…',
        'Fetching latest papers...': '正在获取最新论文…',
        'Please configure arXiv categories first': '请先配置 arXiv 分类',
        'Filters': '筛选', 'Clear filters': '清除筛选',
        'Affiliation filter': '机构筛选', 'Country filter': '国家/地区筛选',
        'Keyword filter': '关键词筛选', 'Overview': '概览',
        'Import': '导入', 'Export': '导出', 'Administration': '管理',
        'Reading Activity': '阅读活动', 'Total papers': '论文总数',
        'Total reading time': '总阅读时长', 'Papers read this week': '本周阅读论文',
        'Reading time this week': '本周阅读时长', 'Recent Reading': '最近阅读',
        'Less': '少', 'More': '多', 'Mon': '周一', 'Wed': '周三', 'Fri': '周五',
        'Agentic Settings': 'Agentic 设置',
        'AI feature configuration (translation, interpretation, daily arXiv, etc.)': '配置翻译、解读和 Daily arXiv 等 AI 功能',
        'LLM API Configuration': 'LLM API 配置', 'AI Translate': 'AI 翻译',
        'AI Interpret': 'AI 解读', 'Model Name': '模型名称',
        'LLM model name for paper translation': '用于论文翻译的 LLM 模型名称',
        'LLM model name for paper summary & chat': '用于论文总结与问答的 LLM 模型名称',
        'LLM model name for Daily arXiv abstract summary': '用于 Daily arXiv 摘要总结的 LLM 模型名称',
        'OpenAI-compatible API base URL': 'OpenAI 兼容 API 的 Base URL',
        'API access key': 'API 访问密钥', 'Not configured': '未配置',
        'Configured': '已配置', 'Clear': '清除', 'Test': '测试',
        'AI Output Language': 'AI 输出语言', 'Output Language': '输出语言',
        'Language for AI-generated content': 'AI 生成内容使用的语言',
        'Chinese': '中文', 'English': '英文', 'PDF Parsing Service': 'PDF 解析服务',
        'MinerU Mode': 'MinerU 模式', 'Choose between local deployment or cloud API': '选择本地部署或云 API',
        'Local Deployment': '本地部署', 'Cloud API': '云 API',
        'MinerU Server URL': 'MinerU 服务地址', 'Local PDF parsing service URL': '本地 PDF 解析服务地址',
        'Save Agentic settings': '保存 Agentic 设置', 'Save settings': '保存设置',
        'Changes are saved only when you click Save.': '点击“保存设置”后更改才会生效。',
        'Daily arXiv Settings': 'Daily arXiv 设置',
        'Configure daily arXiv paper fetching': '配置 Daily arXiv 论文收集',
        'Feature Switch': '功能开关', 'Enable Daily arXiv': '启用 Daily arXiv',
        'Turn on/off the automatic daily paper fetching': '开启或关闭每日自动收集论文',
        'arXiv Categories': 'arXiv 分类', 'Configured categories': '已配置分类',
        'Common categories:': '常用分类：', 'Fetch settings': '收集设置',
        'Retention days': '保留发布日数量', 'Check interval (minutes)': '检查间隔（分钟）',
        'Max papers per day': '每日最多论文数', 'Quality strategy': '质量策略',
        'Selection mode': '筛选模式', 'Strict': '严格', 'Balanced': '均衡',
        'Discovery': '探索', 'Institution tiers': '机构分层',
        'Keyword list': '关键词列表', 'Max keywords': '最多关键词数',
        'Institution aliases': '机构别名', 'Alias mappings': '别名映射',
        'Save Daily arXiv settings': '保存 Daily arXiv 设置',
        'Import Data': '导入数据', 'Export Data': '导出数据',
        'Upload RDF file': '上传 RDF 文件', 'Root (default)': '根目录（默认）',
        'Drag Zotero RDF file here': '将 Zotero RDF 文件拖到这里',
        'Parsing RDF file...': '正在解析 RDF 文件…', 'Imported': '已导入',
        'Failed': '失败', 'Skipped': '已跳过', 'Duplicates': '重复项',
        'How to import': '导入说明', 'Upload export file': '上传导出文件',
        'Importing...': '正在导入…', 'Success:': '成功：', 'Failed:': '失败：',
        'Skipped:': '跳过：', 'Duplicates:': '重复：', 'Usage': '使用说明',
        'Export notes': '导出说明', 'Browser limitations': '浏览器限制',
        'Full data migration': '完整数据迁移', 'Export includes:': '导出内容：',
        'Exporting...': '正在导出…', 'Start export': '开始导出',
        'Download export file': '下载导出文件', 'Chat with Paper': '与论文对话',
        'New Chat': '新建对话', 'History': '历史记录', 'Rename': '重命名',
        'Add subcategory': '添加子分类', 'Pin': '置顶', 'Delete': '删除',
        'Refresh metadata': '刷新元数据', 'AI iranslate': 'AI 翻译',
        'AI interpret': 'AI 解读', 'Delete paper': '删除论文',
        'Processing...': '处理中…', 'Add institution mapping': '添加机构映射',
        'Welcome to PaperPilot': '欢迎使用 PaperPilot',
        'Select AI Output Language': '选择 AI 输出语言', "Don't show again": '不再显示',
        'Log In': '登录', 'Log Out': '退出登录', 'Password': '密码',
        'Back to Home': '返回首页', 'Settings': '设置', 'Refresh': '刷新',
        'Upload files': '上传文件', 'Import from arXiv': '从 arXiv 导入',
        'Multi-select mode': '多选模式', 'View reading list': '查看 Reading List',
        'Toggle Library': '展开或收起论文库', 'Toggle Paper Info': '展开或收起论文信息',
        'Previous day': '上一个发布日', 'Next day': '下一个发布日',
        'Sync latest papers from arXiv': '同步 arXiv 最新论文',
        'Search Title / Authors / Abstract / Notes': '搜索标题、作者、摘要或笔记',
        'Search title / author / institution / abstract...': '搜索标题、作者、机构或摘要…',
        'Ask a question about the paper...': '输入关于这篇论文的问题…',
        'Enter category name, e.g., cs.CV': '输入分类，例如 cs.CV',
        'Enter keyword, press Enter to add': '输入关键词，按回车添加',
        'Enter your password': '输入密码', 'username': '用户名',
        'Loading PDF...': '正在加载 PDF…', 'Download PDF': '下载 PDF',
        'Open in new window': '在新窗口打开', 'Analysis report': '分析报告',
        'Copy': '复制', 'Copied': '已复制', 'Download': '下载',
        'Add arXiv categories that match your research interests.': '添加符合研究方向的 arXiv 分类。',
        'Papers older than the selected number of arXiv release days are removed from Daily arXiv.': 'Daily arXiv 仅保留所选数量的 arXiv 发布日。',
        'How often to check arXiv for updates.': '检查 arXiv 更新的频率。',
        'Maximum number of selected papers for each arXiv release day.': '每个 arXiv 发布日最多入选的论文数。',
        'Built-in institution groups': '内置机构分组',
        'Move institutions between tiers to adjust ranking preference.': '在不同层级间移动机构以调整排序偏好。',
        'Candidate papers are ranked by your topics and metadata before the LLM reranks them.': '候选论文先按主题和元数据计算相关性，再由 LLM 精排。',
        'Server-managed storage': '服务器托管存储',
    }));

    const excluded = '.paper-list, .daily-arxiv-grid, .chat-messages-container, .translation-raw-log, code, pre, script, style';

    function t(value) {
        if (typeof value !== 'string') return value;
        return messages.get(value.trim()) || value;
    }

    function translateStatic(root) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(node => {
            const parent = node.parentElement;
            if (!parent || parent.closest(excluded)) return;
            const raw = node.nodeValue;
            const trimmed = raw.trim();
            if (!trimmed || !messages.has(trimmed)) return;
            node.nodeValue = raw.replace(trimmed, messages.get(trimmed));
        });
        root.querySelectorAll('[title],[placeholder],[aria-label]').forEach(element => {
            if (element.closest(excluded)) return;
            for (const attribute of ['title', 'placeholder', 'aria-label']) {
                if (element.hasAttribute(attribute)) element.setAttribute(attribute, t(element.getAttribute(attribute)));
            }
        });
    }

    function formatDate(value) {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    function formatDateTime(value) {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return `${formatDate(date)} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    }

    function start() {
        translateStatic(document.body);
        const observer = new MutationObserver(records => {
            records.forEach(record => record.addedNodes.forEach(node => {
                if (node.nodeType === Node.ELEMENT_NODE) translateStatic(node);
                else if (node.nodeType === Node.TEXT_NODE && node.parentElement) translateStatic(node.parentElement);
            }));
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    window.PaperPilotI18n = { locale: 'zh-CN', t, translateStatic, formatDate, formatDateTime };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
})();
