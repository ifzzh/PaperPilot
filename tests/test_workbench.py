import json
from pathlib import Path

import pytest

from paperpilot.database import connection
from paperpilot.workbench import build_assets, parse_workbench_flag
from tests.workbench_support import make_workbench_fixture


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    app, first, second = make_workbench_fixture(tmp_path, monkeypatch)
    # Unit tests work before npm build, using a local manifest fixture.
    static = tmp_path / 'static'
    (static / 'workbench/.vite').mkdir(parents=True)
    (static / 'workbench/main.js').write_text('// bundled')
    (static / 'workbench/main.css').write_text('body{}')
    (static / 'workbench/.vite/manifest.json').write_text(json.dumps({
        'src/main.tsx': {'file': 'main.js', 'css': ['main.css']}
    }))
    app.static_folder = str(static)
    yield app, first, second
    connection.close_db()


def login(client, name='reader_one'):
    result = client.post('/api/auth/login', json={'username': name, 'password': 'workbench-test-pass'})
    assert result.status_code == 200
    return result.json['csrf_token']


def test_flag_and_closed_entry(fixture):
    app, _, _ = fixture
    assert parse_workbench_flag() is False
    assert parse_workbench_flag('1') is True
    with pytest.raises(ValueError):
        parse_workbench_flag('yes-please')
    app.config['PAPERPILOT_WORKBENCH_ENABLED'] = False
    c = app.test_client()
    assert c.get('/workbench').status_code == 404
    assert c.get('/workbench/').status_code == 404
    assert '新版工作台' not in c.get('/').text


def test_auth_entry_manifest_and_logout(fixture):
    app, _, _ = fixture
    c = app.test_client()
    assert c.get('/workbench').location == '/'
    csrf = login(c)
    page = c.get('/workbench')
    assert page.status_code == 200
    assert 'type="module"' in page.text
    assert '/static/workbench/main.js' in page.text
    assert '/static/workbench/main.css' in page.text
    assert 'app.js' not in page.text
    assert page.headers['Cache-Control'] == 'no-store'
    assert "script-src 'self'" in page.headers['Content-Security-Policy']
    assert c.get('/workbench/?paper=a-0').location == '/workbench?paper=a-0'
    assert '新版工作台' in c.get('/').text
    assert c.delete('/api/auth/session').status_code == 403
    assert c.delete('/api/auth/session', headers={'X-CSRF-Token': csrf}).status_code == 200
    assert c.get('/workbench').location == '/'
    assert c.get('/api/papers/all').status_code == 401


def test_first_password_change_redirects(fixture):
    app, first, _ = fixture
    with app.app_context():
        connection.get_db().execute('UPDATE users SET must_change_password=1 WHERE id=?', (first['id'],))
        connection.get_db().commit()
    c = app.test_client(); login(c)
    assert c.get('/workbench').location == '/'
    assert c.get('/api/papers/all').status_code == 403


def test_real_list_detail_and_owner_isolation(fixture):
    app, _, _ = fixture
    a, b = app.test_client(), app.test_client()
    login(a); login(b, 'reader_two')
    assert {p['id'] for p in a.get('/api/papers/all').json} == {'a-0', 'a-1', 'a-2'}
    assert {p['id'] for p in b.get('/api/papers/all').json} == {'b-0'}
    assert a.get('/api/paper/a-0').json['has_chinese_version'] is True
    assert a.get('/api/paper/b-0').status_code == 404
    assert b.get('/api/paper/a-0').status_code == 404
    assert a.get('/viewer/a-0').status_code == 200


def test_missing_or_escaping_assets_do_not_break_old_site(fixture):
    app, _, _ = fixture
    c = app.test_client(); login(c)
    manifest = Path(app.static_folder) / 'workbench/.vite/manifest.json'
    manifest.write_text(json.dumps({'src/main.tsx': {'file': '../../outside.js'}}))
    assert c.get('/workbench').status_code == 503
    assert '返回旧版' in c.get('/workbench').text
    manifest.unlink()
    assert c.get('/workbench').status_code == 503
    assert c.get('/').status_code == 200


def test_manifest_includes_imported_css(tmp_path):
    root = tmp_path / 'workbench'; (root / '.vite').mkdir(parents=True)
    for file in ['a.js', 'b.js', 'b.css']:
        (root / file).write_text('/* fixture */')
    (root / '.vite/manifest.json').write_text(json.dumps({
        'src/main.tsx': {'file': 'a.js', 'imports': ['b']},
        'b': {'file': 'b.js', 'css': ['b.css']},
    }))
    assert build_assets(str(tmp_path))['styles'] == ['workbench/b.css']
