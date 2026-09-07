const SUPABASE_URL = window.__SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY || '';

const supabaseClient = (window.supabase?.createClient && SUPABASE_URL && SUPABASE_ANON_KEY)
    ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
    : null;

let currentSession = null;
let appLoaded = false;
let appLoading = false;

document.addEventListener('DOMContentLoaded', async () => {
    bindAuthUIHandlers();

    if (!supabaseClient) {
        hideLoginOverlay();
        const loginBtn = document.getElementById('login-btn');
        const logoutBtn = document.getElementById('logout-btn');
        if (loginBtn) loginBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'none';
        loadAppWithoutAuth();
        return;
    }

    const { data: { session } } = await supabaseClient.auth.getSession();
    await applyAuthSession(session);

    supabaseClient.auth.onAuthStateChange((_event, session) => {
        applyAuthSession(session);
    });
});

function bindAuthUIHandlers() {
    const loginForm = document.getElementById('auth-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleAuth);
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }

    const loginBtn = document.getElementById('login-btn');
    if (loginBtn) {
        loginBtn.addEventListener('click', () => {
            showLoginOverlay();
            clearAuthError();
        });
    }

}

function getAccessToken() {
    return currentSession?.access_token || null;
}

async function syncServerSession(session) {
    if (!session?.access_token) {
        await fetch('/api/auth/session', { method: 'DELETE' });
        return;
    }

    const response = await fetch('/api/auth/session', {
        method: 'POST',
        headers: { Authorization: `Bearer ${session.access_token}` },
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || 'Unable to establish a secure session');
    }
}

async function applyAuthSession(session) {
    currentSession = session;
    try {
        await syncServerSession(session);
        updateAuthUI(session);
    } catch (error) {
        currentSession = null;
        showLoginOverlay();
        setAuthError(error.message || 'Unable to establish a secure session');
    }
}

function showLoginOverlay() {
    const loginOverlay = document.getElementById('login-overlay');
    if (loginOverlay) {
        loginOverlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
}

function hideLoginOverlay() {
    const loginOverlay = document.getElementById('login-overlay');
    if (loginOverlay) {
        loginOverlay.style.display = 'none';
        document.body.style.overflow = '';
    }
}

function updateAuthUI(session) {
    const loginBtn = document.getElementById('login-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const userNameDisplay = document.getElementById('setting-user-name');

    if (session) {
        hideLoginOverlay();
        if (loginBtn) loginBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'inline-flex';

        if (userNameDisplay && userNameDisplay.textContent === 'Paper Reader') {
            userNameDisplay.textContent = session.user.email.split('@')[0];
        }

        ensureAppLoaded();
        return;
    }

    showLoginOverlay();
    if (loginBtn) loginBtn.style.display = 'inline-flex';
    if (logoutBtn) logoutBtn.style.display = 'none';
}

function ensureAppLoaded() {
    if (appLoaded || appLoading) return;
    if (!getAccessToken()) return;

    const existing = document.getElementById('paperpilot-app-script');
    if (existing) {
        appLoading = true;
        return;
    }

    patchFetchWithAuth();

    appLoading = true;
    const script = document.createElement('script');
    script.id = 'paperpilot-app-script';
    script.src = '/static/js/app.js?v=1.2';
    script.onload = () => {
        appLoaded = true;
        appLoading = false;
    };
    script.onerror = () => {
        appLoading = false;
    };
    document.body.appendChild(script);
}

function loadAppWithoutAuth() {
    if (appLoaded || appLoading) return;

    const existing = document.getElementById('paperpilot-app-script');
    if (existing) {
        appLoading = true;
        return;
    }

    appLoading = true;
    const script = document.createElement('script');
    script.id = 'paperpilot-app-script';
    script.src = '/static/js/app.js?v=1.2';
    script.onload = () => {
        appLoaded = true;
        appLoading = false;
    };
    script.onerror = () => {
        appLoading = false;
    };
    document.body.appendChild(script);
}

function patchFetchWithAuth() {
    if (window.__fetchPatchedForAuth) return;
    window.__fetchPatchedForAuth = true;

    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
        try {
            const url = typeof input === 'string' ? input : input.url;
            const isApiCall = typeof url === 'string' && url.startsWith('/api/');
            const token = getAccessToken();
            if (isApiCall && token) {
                const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined));
                if (!headers.has('Authorization')) {
                    headers.set('Authorization', `Bearer ${token}`);
                }
                init = { ...init, headers };
            }
        } catch {
        }
        return originalFetch(input, init);
    };
}

function setAuthError(message, color = '#ef5350') {
    const errorMsg = document.getElementById('auth-error');
    if (!errorMsg) return;
    errorMsg.style.color = color;
    errorMsg.textContent = message;
    errorMsg.style.display = 'block';
}

function clearAuthError() {
    const errorMsg = document.getElementById('auth-error');
    if (!errorMsg) return;
    errorMsg.style.display = 'none';
    errorMsg.textContent = '';
}

async function handleAuth(e) {
    e.preventDefault();
    if (!supabaseClient) return;

    const email = (document.getElementById('auth-email')?.value || '').trim();
    const password = (document.getElementById('auth-password')?.value || '').trim();
    const submitBtn = document.getElementById('auth-submit');

    clearAuthError();
    if (!email || !password) {
        setAuthError('请输入邮箱和密码');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Logging in...';

    try {
        const { error } = await supabaseClient.auth.signInWithPassword({ email, password });
        if (error) throw error;
    } catch (error) {
        setAuthError(error.message || '操作失败');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Log In';
    }
}

async function handleLogout() {
    if (!supabaseClient) return;
    await fetch('/api/auth/session', { method: 'DELETE' });
    await supabaseClient.auth.signOut();
}
