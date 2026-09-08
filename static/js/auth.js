let currentUser = null;
let appLoaded = false;
let appLoading = false;
let authMode = 'login';

function cookieValue(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    const part = document.cookie.split(';').map(value => value.trim())
        .find(value => value.startsWith(prefix));
    return part ? decodeURIComponent(part.slice(prefix.length)) : '';
}

function patchFetchWithAuth() {
    if (window.__paperpilotFetchAuthPatched) return;
    window.__paperpilotFetchAuthPatched = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
        try {
            const url = typeof input === 'string' ? input : input.url;
            const method = String(init.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
            const sameOriginApi = typeof url === 'string' && (
                url.startsWith('/api/') || url.startsWith(`${window.location.origin}/api/`)
            );
            if (sameOriginApi && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
                const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined));
                const csrf = cookieValue('paperpilot_csrf');
                if (csrf && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
                init = { ...init, headers };
            }
        } catch (_error) {
            // The original request still runs if an unusual Request object cannot be inspected.
        }
        return originalFetch(input, init);
    };
}

document.addEventListener('DOMContentLoaded', async () => {
    patchFetchWithAuth();
    bindAuthUIHandlers();
    try {
        const response = await fetch('/api/auth/session');
        const payload = await response.json();
        if (payload.auth_disabled) {
            hideLoginOverlay();
            document.getElementById('login-btn').style.display = 'none';
            document.getElementById('logout-btn').style.display = 'none';
            ensureAppLoaded();
            return;
        }
        if (payload.authenticated) applyAuthenticatedUser(payload.user);
        else showAuthMode('login');
    } catch (_error) {
        showAuthMode('login');
        setAuthError('无法连接认证服务，请稍后重试');
    }
});

function bindAuthUIHandlers() {
    document.getElementById('auth-form')?.addEventListener('submit', handleAuth);
    document.getElementById('logout-btn')?.addEventListener('click', handleLogout);
    document.getElementById('login-btn')?.addEventListener('click', () => showAuthMode('login'));
    document.getElementById('auth-show-login')?.addEventListener('click', () => showAuthMode('login'));
    document.getElementById('auth-show-register')?.addEventListener('click', () => showAuthMode('register'));
    document.getElementById('auth-show-reset')?.addEventListener('click', () => showAuthMode('reset'));
    document.getElementById('admin-create-invite')?.addEventListener('click', createInvite);
    document.getElementById('admin-add-provider')?.addEventListener('click', addProvider);
    document.querySelector('[data-setting="admin"]')?.addEventListener('click', loadAdminPanel);
    document.getElementById('account-password-form')?.addEventListener('submit', handleAccountPasswordChange);
}

function showLoginOverlay() {
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function hideLoginOverlay() {
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.style.display = 'none';
    document.body.style.overflow = '';
}

function showAuthMode(mode) {
    authMode = mode;
    showLoginOverlay();
    clearAuthError();
    const title = document.getElementById('auth-title');
    const username = document.getElementById('auth-username-group');
    const invite = document.getElementById('auth-invite-group');
    const current = document.getElementById('auth-current-password-group');
    const replacement = document.getElementById('auth-new-password-group');
    const submit = document.getElementById('auth-submit');
    if (title) title.textContent = mode === 'register' ? '邀请码注册' : mode === 'change' ? '首次登录请修改密码' : mode === 'reset' ? '使用重置码' : '登录';
    username.style.display = ['login', 'register'].includes(mode) ? 'block' : 'none';
    invite.style.display = mode === 'register' || mode === 'reset' ? 'block' : 'none';
    current.style.display = ['login', 'register', 'change'].includes(mode) ? 'block' : 'none';
    replacement.style.display = mode === 'change' || mode === 'reset' ? 'block' : 'none';
    document.getElementById('auth-invite-label').textContent = mode === 'reset' ? '一次性密码重置码' : '邀请码';
    submit.textContent = mode === 'register' ? '注册' : mode === 'change' ? '修改密码' : mode === 'reset' ? '重置密码' : '登录';
    document.getElementById('auth-mode-links').style.display = mode === 'change' ? 'none' : 'flex';
}

function applyAuthenticatedUser(user) {
    currentUser = user;
    window.__PAPERPILOT_USER = user;
    if (user.must_change_password) {
        showAuthMode('change');
        setAuthError('临时密码必须先修改，之后才能使用 PaperPilot', '#7d4a9d');
        return;
    }
    hideLoginOverlay();
    document.getElementById('login-btn').style.display = 'none';
    document.getElementById('logout-btn').style.display = 'inline-flex';
    const adminNav = document.querySelector('[data-setting="admin"]');
    if (adminNav) adminNav.style.display = user.role === 'admin' ? 'flex' : 'none';
    ensureAppLoaded();
}

function ensureAppLoaded() {
    if (appLoaded || appLoading) return;
    appLoading = true;
    const script = document.createElement('script');
    script.id = 'paperpilot-app-script';
    script.src = '/static/js/app.js?v=0.9.1';
    script.onload = () => { appLoaded = true; appLoading = false; };
    script.onerror = () => { appLoading = false; setAuthError('应用脚本加载失败'); };
    document.body.appendChild(script);
}

function setAuthError(message, color = '#ef5350') {
    const element = document.getElementById('auth-error');
    if (!element) return;
    element.style.color = color;
    element.textContent = message;
    element.style.display = 'block';
}

function clearAuthError() {
    const element = document.getElementById('auth-error');
    if (!element) return;
    element.textContent = '';
    element.style.display = 'none';
}

async function jsonRequest(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `request_failed_${response.status}`);
    return payload;
}

async function handleAuth(event) {
    event.preventDefault();
    clearAuthError();
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    const inviteCode = document.getElementById('auth-invite').value.trim();
    const newPassword = document.getElementById('auth-new-password').value;
    const submit = document.getElementById('auth-submit');
    submit.disabled = true;
    try {
        if (authMode === 'login') {
            const payload = await jsonRequest('/api/auth/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            applyAuthenticatedUser(payload.user);
        } else if (authMode === 'register') {
            await jsonRequest('/api/auth/register', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, invite_code: inviteCode }),
            });
            showAuthMode('login');
            setAuthError('注册成功，请登录', '#2e7d32');
        } else if (authMode === 'change') {
            const payload = await jsonRequest('/api/auth/change-password', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password: password, new_password: newPassword }),
            });
            applyAuthenticatedUser(payload.user);
        } else if (authMode === 'reset') {
            await jsonRequest('/api/auth/reset-password', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reset_code: inviteCode, new_password: newPassword }),
            });
            showAuthMode('login');
            setAuthError('密码已重置，请登录', '#2e7d32');
        }
    } catch (error) {
        const messages = {
            invalid_credentials: '用户名或密码错误',
            registration_failed: '注册失败，请检查用户名、密码和邀请码',
            invalid_password: '密码必须为 8–128 个字符',
            invalid_username: '用户名须为 3–32 位小写字母、数字、下划线或连字符',
            invalid_reset_code: '重置码无效、过期或已使用', csrf_failed: '安全令牌失效，请重新登录',
        };
        setAuthError(messages[error.message] || error.message || '操作失败');
    } finally {
        submit.disabled = false;
    }
}

async function handleAccountPasswordChange(event) {
    event.preventDefault();
    const current = document.getElementById('account-current-password');
    const replacement = document.getElementById('account-new-password');
    const confirmation = document.getElementById('account-confirm-password');
    const status = document.getElementById('account-password-status');
    const submit = document.getElementById('account-password-submit');
    status.style.display = 'block';
    status.style.color = '#ef5350';
    if (replacement.value.length < 8 || replacement.value.length > 128) {
        status.textContent = '新密码必须为 8–128 个字符';
        return;
    }
    if (replacement.value !== confirmation.value) {
        status.textContent = '两次输入的新密码不一致';
        return;
    }
    submit.disabled = true;
    try {
        const payload = await jsonRequest('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                current_password: current.value,
                new_password: replacement.value,
            }),
        });
        currentUser = payload.user;
        window.__PAPERPILOT_USER = payload.user;
        event.currentTarget.reset();
        status.style.color = '#2e7d32';
        status.textContent = '密码已修改，其他设备已退出登录';
    } catch (error) {
        status.textContent = error.message === 'invalid_credentials'
            ? '当前密码错误'
            : error.message === 'invalid_password'
                ? '新密码必须为 8–128 个字符'
                : (error.message || '密码修改失败');
    } finally {
        submit.disabled = false;
    }
}

async function handleLogout() {
    try { await jsonRequest('/api/auth/session', { method: 'DELETE' }); } catch (_error) {}
    window.location.reload();
}

function appendCell(row, value) {
    const cell = document.createElement('td');
    cell.textContent = String(value ?? '');
    row.appendChild(cell);
    return cell;
}

function actionButton(label, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary';
    button.textContent = label;
    button.addEventListener('click', async () => {
        try { await handler(); } catch (error) {
            document.getElementById('admin-status').textContent = error.message;
        }
    });
    return button;
}

async function loadAdminPanel() {
    if (currentUser?.role !== 'admin') return;
    try {
        const [users, invites, providers] = await Promise.all([
            jsonRequest('/api/admin/users'), jsonRequest('/api/admin/invites'),
            jsonRequest('/api/admin/ai-providers'),
        ]);
        renderUsers(users.users || []);
        renderInvites(invites.invites || []);
        renderProviders(providers.providers || []);
    } catch (error) {
        document.getElementById('admin-status').textContent = error.message;
    }
}

function renderUsers(users) {
    const body = document.getElementById('admin-users-body');
    body.replaceChildren();
    users.forEach(user => {
        const row = document.createElement('tr');
        appendCell(row, user.username); appendCell(row, user.role); appendCell(row, user.status);
        const actions = document.createElement('td');
        actions.append(
            actionButton(user.status === 'active' ? '禁用' : '启用', async () => {
                await jsonRequest(`/api/admin/users/${encodeURIComponent(user.id)}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: user.status === 'active' ? 'disabled' : 'active' }),
                }); await loadAdminPanel();
            }),
            actionButton(user.role === 'admin' ? '取消管理员' : '设为管理员', async () => {
                await jsonRequest(`/api/admin/users/${encodeURIComponent(user.id)}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ role: user.role === 'admin' ? 'user' : 'admin' }),
                }); await loadAdminPanel();
            }),
            actionButton('生成重置码', async () => {
                const result = await jsonRequest(`/api/admin/users/${encodeURIComponent(user.id)}/password-reset`, { method: 'POST' });
                showOneTimeCode('一次性密码重置码', result.reset_code);
            }),
        );
        row.appendChild(actions); body.appendChild(row);
    });
}

function renderInvites(invites) {
    const body = document.getElementById('admin-invites-body');
    body.replaceChildren();
    invites.forEach(invite => {
        const row = document.createElement('tr');
        appendCell(row, window.PaperPilotI18n?.formatDateTime(invite.expires_at * 1000) || ''); appendCell(row, invite.status);
        const actions = document.createElement('td');
        if (invite.status === 'active') actions.appendChild(actionButton('撤销', async () => {
            await jsonRequest(`/api/admin/invites/${encodeURIComponent(invite.id)}`, { method: 'DELETE' });
            await loadAdminPanel();
        }));
        row.appendChild(actions); body.appendChild(row);
    });
}

function renderProviders(providers) {
    const body = document.getElementById('admin-providers-body');
    body.replaceChildren();
    providers.forEach(provider => {
        const row = document.createElement('tr');
        appendCell(row, provider.name); appendCell(row, provider.origin); appendCell(row, provider.enabled ? '启用' : '停用');
        const actions = document.createElement('td');
        actions.append(actionButton(provider.enabled ? '停用' : '启用', async () => {
            await jsonRequest(`/api/admin/ai-providers/${encodeURIComponent(provider.id)}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !provider.enabled }),
            }); await loadAdminPanel();
        }));
        row.appendChild(actions); body.appendChild(row);
    });
}

async function createInvite() {
    try {
        const result = await jsonRequest('/api/admin/invites', { method: 'POST' });
        showOneTimeCode('一次性邀请码（24 小时有效）', result.invite_code);
        await loadAdminPanel();
    } catch (error) { document.getElementById('admin-status').textContent = error.message; }
}

async function addProvider() {
    const name = document.getElementById('admin-provider-name').value.trim();
    const url = document.getElementById('admin-provider-url').value.trim();
    try {
        await jsonRequest('/api/admin/ai-providers', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url }),
        });
        document.getElementById('admin-provider-url').value = '';
        await loadAdminPanel();
    } catch (error) { document.getElementById('admin-status').textContent = error.message; }
}

function showOneTimeCode(label, code) {
    const output = document.getElementById('admin-one-time-code');
    output.replaceChildren();
    const title = document.createElement('strong'); title.textContent = `${label}：`;
    const value = document.createElement('code'); value.textContent = code;
    output.append(title, value);
    output.style.display = 'block';
}
