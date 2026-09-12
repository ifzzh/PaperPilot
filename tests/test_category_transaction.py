import pytest
from tests.workbench_support import make_workbench_fixture
from tests.test_workbench import login
from ipaper.database.connection import get_db
from ipaper.security.identity import Identity, set_background_identity, reset_background_identity
from contextlib import contextmanager
import sqlite3

@contextmanager
def run_as_identity(identity):
    token=set_background_identity(identity)
    try: yield
    finally: reset_background_identity(token)
from ipaper.tools.basic_tools.category_manager import save_categories, get_categories


def test_two_virtual_category_roots_and_transaction_rollback(tmp_path, monkeypatch):
    app,one,two=make_workbench_fixture(tmp_path,monkeypatch)
    def tree(ident):return {'id':'root','name':'Root','children':[{'id':ident,'name':'分类','children':[],'color':'#123456','pinned':True}]}
    with app.app_context():
        with run_as_identity(Identity(one['id'],'reader_one','admin')):
            save_categories('unused',tree('first'))
        with run_as_identity(Identity(two['id'],'reader_two','user')):
            save_categories('unused',tree('second'))
            assert get_categories('unused')['children'][0]['id']=='second'
            with pytest.raises(PermissionError):save_categories('unused',tree('first'))
            got=get_categories('unused')['children'][0]
            assert got['id']=='second' and got['pinned'] and got['color']=='#123456'
        with run_as_identity(Identity(one['id'],'reader_one','admin')):
            assert get_categories('unused')['children'][0]['id']=='first'
