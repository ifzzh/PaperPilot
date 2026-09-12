"""Persistent assets, no PaperStore seeding and no legacy homepage request."""
import pytest
import app as app_module
from ipaper.database import connection
from ipaper.database.dao.paper_dao import PaperDAO
from ipaper.core.base_paper import Paper
from ipaper.security.identity import Identity, run_as_identity
from tests.workbench_support import make_workbench_fixture
from tests.test_workbench import login


@pytest.mark.parametrize('first_request', ['/api/papers/all', '/api/paper/a-1', '/api/paper/a-1/file'])
def test_direct_cold_workbench_and_owner_isolation(tmp_path, monkeypatch, first_request):
    app, first, second = make_workbench_fixture(tmp_path, monkeypatch, cold=True)
    with app.app_context():
        _, invitation = app_module.AUTH_SERVICE.create_invite(first['id'])
        app_module.AUTH_SERVICE.register('empty_reader', 'workbench-test-pass', invitation)
    a, b, empty = [app.test_client() for _ in range(3)]
    login(a); login(b, 'reader_two'); login(empty, 'empty_reader')
    # A restart discards memory only; persistent metadata, files and sessions survive.
    for restart in range(2):
        app_module.paper_store.reset()
        assert a.get('/workbench?paper=a-1&view=reader').location == '/?paper=a-1&view=reader'
        assert a.get('/?paper=a-1&view=reader').status_code in (200, 503)
        assert a.get(first_request).status_code == 200
        assert [p['id'] for p in a.get('/api/papers/all').json] == ['a-2', 'a-1', 'a-0']
        assert [p['id'] for p in b.get('/api/papers/all').json] == ['b-0']
        assert empty.get('/api/papers/all').json == []
        for client, foreign in [(a, 'b-0'), (b, 'a-1'), (empty, 'a-1')]:
            for suffix in ('', '/file'):
                assert client.get('/api/paper/' + foreign + suffix).status_code == 404
        assert a.get('/api/paper/a-1/file').data.startswith(b'%PDF-')
    connection.close_db()


def test_partial_cache_does_not_mark_category_complete(tmp_path, monkeypatch):
    app, first, _ = make_workbench_fixture(tmp_path, monkeypatch, count=6, cold=True)
    def seed_one():
        paper = Paper.from_dict(PaperDAO.get_paper('a-1'))
        app_module.paper_store.upsert(paper, category_id='library', category_path=['Root', '文献分类'])
    with app.app_context():
        run_as_identity(Identity(first['id'], first['username'], first['role']), seed_one)
    c = app.test_client(); login(c)
    assert len(c.get('/api/papers/all').json) == 6
    connection.close_db()
