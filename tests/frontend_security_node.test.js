'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const security = require('../static/js/content_security.js');

test('escapes plain text without dropping visible content', () => {
    assert.equal(
        security.escapeHtml('<img onerror="x">\'&'),
        '&lt;img onerror=&quot;x&quot;&gt;&#39;&amp;'
    );
});

test('normalizes user-facing http URLs and rejects active schemes', () => {
    assert.equal(
        security.safeHttpUrl('github.com/ifzzh/iPaper', { baseUrl: 'http://ipaper.test' }),
        'https://github.com/ifzzh/iPaper'
    );
    assert.equal(
        security.safeHttpUrl('/viewer/paper', { allowRelative: true, baseUrl: 'http://ipaper.test' }),
        '/viewer/paper'
    );
    assert.equal(security.safeHttpUrl('javascript:alert(1)'), null);
    assert.equal(security.safeHttpUrl('data:text/html,boom'), null);
    assert.equal(security.safeHttpUrl('https://user:secret@example.com'), null);
    assert.equal(security.safeHttpUrl('https://example.com/\nattack'), null);
    assert.equal(security.safeHttpUrl('https:\\example.com'), null);
    assert.equal(
        security.safeHttpUrl('https://ipaper.test.evil/path', { baseUrl: 'https://ipaper.test' }),
        'https://ipaper.test.evil/path'
    );
});

test('allows only fixed CSS color syntax', () => {
    assert.equal(security.safeColor('#7d4a9d', '#000000'), '#7d4a9d');
    assert.equal(security.safeColor('#fff', '#000000'), '#fff');
    assert.equal(security.safeColor('red; background:url(x)', '#8b949e'), '#8b949e');
});

test('allows only controlled same-origin markdown image routes', () => {
    const options = { paperId: 'paper-1', baseUrl: 'http://ipaper.test' };
    assert.equal(
        security.safeInternalImageUrl('/api/paper/paper-1/analysis/image?path=figure.png', options),
        '/api/paper/paper-1/analysis/image?path=figure.png'
    );
    assert.equal(
        security.safeInternalImageUrl('/static/images/website_logo.svg', options),
        '/static/images/website_logo.svg'
    );
    assert.equal(
        security.safeInternalImageUrl('/api/paper/other/analysis/image?path=figure.png', options),
        null
    );
    assert.equal(security.safeInternalImageUrl('https://tracker.example/pixel', options), null);
    assert.equal(security.safeInternalImageUrl('data:image/svg+xml,x', options), null);
});
