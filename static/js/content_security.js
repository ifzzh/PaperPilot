(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    root.iPaperSecurity = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
    const SAFE_COLOR = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
    const MARKDOWN_FORBIDDEN_TAGS = [
        'style', 'script', 'iframe', 'object', 'embed', 'form', 'input',
        'select', 'option', 'textarea', 'button', 'svg', 'math', 'template'
    ];
    const MARKDOWN_FORBIDDEN_ATTRIBUTES = [
        'style', 'srcset', 'formaction', 'xlink:href', 'id', 'name'
    ];

    function asText(value) {
        return value === null || value === undefined ? '' : String(value);
    }

    function setText(element, value) {
        if (element) element.textContent = asText(value);
        return element;
    }

    function escapeHtml(value) {
        return asText(value).replace(/[&<>"']/g, function (character) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[character];
        });
    }

    function baseOrigin(baseUrl) {
        const fallback = 'http://ipaper.invalid';
        const candidate = baseUrl
            || (root.location && root.location.origin)
            || fallback;
        try {
            return new URL(candidate).origin;
        } catch (_) {
            return fallback;
        }
    }

    function safeHttpUrl(value, options) {
        const settings = options || {};
        const raw = asText(value).trim();
        if (!raw || CONTROL_CHARACTERS.test(raw) || raw.includes('\\')) return null;
        if (settings.allowFragment && /^#[A-Za-z0-9_.:-]+$/.test(raw)) return raw;

        const origin = baseOrigin(settings.baseUrl);
        const isRelative = raw.startsWith('/');
        if (isRelative && !settings.allowRelative) return null;

        let candidate = raw;
        if (!isRelative && !/^[A-Za-z][A-Za-z0-9+.-]*:/.test(candidate)) {
            candidate = `https://${candidate}`;
        }

        let parsed;
        try {
            parsed = new URL(candidate, origin);
        } catch (_) {
            return null;
        }
        if (!['http:', 'https:'].includes(parsed.protocol)) return null;
        if (parsed.username || parsed.password) return null;

        if (isRelative && parsed.origin === origin) {
            return `${parsed.pathname}${parsed.search}${parsed.hash}`;
        }
        return parsed.href;
    }

    function safeColor(value, fallback) {
        const normalizedFallback = SAFE_COLOR.test(asText(fallback)) ? asText(fallback) : '#7d4a9d';
        const candidate = asText(value).trim();
        return SAFE_COLOR.test(candidate) ? candidate : normalizedFallback;
    }

    function safeInternalImageUrl(value, options) {
        const settings = options || {};
        const origin = baseOrigin(settings.baseUrl);
        const normalized = safeHttpUrl(value, {
            allowRelative: true,
            baseUrl: origin
        });
        if (!normalized) return null;

        let parsed;
        try {
            parsed = new URL(normalized, origin);
        } catch (_) {
            return null;
        }
        if (parsed.origin !== origin) return null;
        if (parsed.pathname.startsWith('/static/images/')) {
            return `${parsed.pathname}${parsed.search}${parsed.hash}`;
        }

        const paperId = asText(settings.paperId).trim();
        if (!paperId) return null;
        const expected = `/api/paper/${encodeURIComponent(paperId)}/analysis/image`;
        if (parsed.pathname !== expected) return null;
        return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }

    function replaceWithText(node, value) {
        const documentRef = node && node.ownerDocument;
        if (!documentRef || !node.parentNode) return;
        node.parentNode.replaceChild(documentRef.createTextNode(asText(value)), node);
    }

    function sanitizeLinks(container, origin) {
        container.querySelectorAll('a').forEach(function (anchor) {
            const rawHref = anchor.getAttribute('href') || '';
            const href = safeHttpUrl(rawHref, {
                allowRelative: true,
                allowFragment: true,
                baseUrl: origin
            });
            if (!href) {
                replaceWithText(anchor, anchor.textContent);
                return;
            }
            anchor.setAttribute('href', href);
            let isExternal = false;
            try {
                isExternal = new URL(href, origin).origin !== origin;
            } catch (_) {
                isExternal = true;
            }
            if (/^https?:/i.test(href) && isExternal) {
                anchor.setAttribute('target', '_blank');
                anchor.setAttribute('rel', 'noopener noreferrer');
            } else {
                anchor.removeAttribute('target');
                anchor.removeAttribute('rel');
            }
        });
    }

    function sanitizeImages(container, options, origin, originalSources) {
        container.querySelectorAll('img').forEach(function (image) {
            const rawSource = (originalSources && originalSources.get(image)) || image.getAttribute('src') || '';
            const safeSource = safeInternalImageUrl(rawSource, {
                paperId: options.paperId,
                baseUrl: origin
            });
            if (safeSource) {
                image.setAttribute('src', safeSource);
                image.removeAttribute('srcset');
                image.setAttribute('loading', 'lazy');
                return;
            }

            const externalSource = safeHttpUrl(rawSource, { baseUrl: origin });
            const label = image.getAttribute('alt') || 'image';
            if (externalSource && /^https?:/i.test(externalSource)) {
                const link = image.ownerDocument.createElement('a');
                link.className = 'markdown-external-image';
                link.href = externalSource;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = `[External image: ${label}]`;
                image.parentNode.replaceChild(link, image);
                return;
            }
            replaceWithText(image, `[Blocked image: ${label}]`);
        });
    }

    function sanitizeMarkdownHtml(value, options) {
        const settings = options || {};
        const documentRef = root.document;
        const purifier = root.DOMPurify;
        if (!documentRef || !purifier || typeof purifier.sanitize !== 'function') {
            return escapeHtml(value);
        }

        const originalImageSources = new WeakMap();
        const stripImageSource = function (node, attribute) {
            if (node && node.nodeName === 'IMG' && attribute.attrName === 'src') {
                originalImageSources.set(node, attribute.attrValue);
                attribute.keepAttr = false;
            }
        };
        purifier.addHook('uponSanitizeAttribute', stripImageSource);
        let fragment;
        try {
            fragment = purifier.sanitize(asText(value), {
                USE_PROFILES: { html: true },
                RETURN_DOM_FRAGMENT: true,
                ALLOW_DATA_ATTR: false,
                ALLOW_ARIA_ATTR: true,
                FORBID_TAGS: MARKDOWN_FORBIDDEN_TAGS,
                FORBID_ATTR: MARKDOWN_FORBIDDEN_ATTRIBUTES
            });
        } finally {
            purifier.removeHook('uponSanitizeAttribute');
        }
        const container = documentRef.createElement('div');
        container.appendChild(fragment);
        const origin = baseOrigin(settings.baseUrl);
        sanitizeLinks(container, origin);
        sanitizeImages(container, settings, origin, originalImageSources);
        return container.innerHTML;
    }

    function setSanitizedMarkdown(element, html, options) {
        if (!element) return element;
        element.innerHTML = sanitizeMarkdownHtml(html, options);
        return element;
    }

    return Object.freeze({
        asText: asText,
        setText: setText,
        escapeHtml: escapeHtml,
        safeHttpUrl: safeHttpUrl,
        safeColor: safeColor,
        safeInternalImageUrl: safeInternalImageUrl,
        sanitizeMarkdownHtml: sanitizeMarkdownHtml,
        setSanitizedMarkdown: setSanitizedMarkdown
    });
});
