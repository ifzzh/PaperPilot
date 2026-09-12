(() => {
  if (window.__ipaperFetchAuthPatched) return;
  window.__ipaperFetchAuthPatched = true;
  const originalFetch = window.fetch.bind(window);
  const csrf = () => {
    const entry = document.cookie.split(';').map(value => value.trim())
      .find(value => value.startsWith('paperpilot_csrf='));
    return entry ? decodeURIComponent(entry.slice('paperpilot_csrf='.length)) : '';
  };
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url;
    const method = String(init.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
    if (typeof url === 'string' && url.includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined));
      if (csrf() && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf());
      init = { ...init, headers };
    }
    return originalFetch(input, init).then(response => {
      if (response.status === 401) window.location.href = '/';
      return response;
    });
  };
})();
