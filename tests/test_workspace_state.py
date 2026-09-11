import pytest
from tests.workbench_support import make_workbench_fixture
from tests.test_workbench import login
from paperpilot.database.connection import get_db
from paperpilot.security.identity import Identity, set_background_identity, reset_background_identity
from contextlib import contextmanager
import sqlite3

@contextmanager
def run_as_identity(identity):
    token=set_background_identity(identity)
    try: yield
    finally: reset_background_identity(token)
from paperpilot.tools.basic_tools.category_manager import save_categories, get_categories


def test_workspace_and_positions_are_owned_bounded_and_durable(tmp_path, monkeypatch):
    app, one, two = make_workbench_fixture(tmp_path, monkeypatch)
    a,b = app.test_client(),app.test_client()
    csrf=login(a);login(b,'reader_two');headers={'X-CSRF-Token':csrf}
    assert a.put('/api/workspace/state',json={'tabs':[]}).status_code==403
    state={'tabs':['a-0','a-1'],'activePaper':'a-0','theme':'dark','chatWidth':380}
    assert a.put('/api/workspace/state',json=state,headers=headers).status_code==200
    assert a.get('/api/workspace/state').json==state
    assert b.get('/api/workspace/state').json['tabs']==[]
    assert a.put('/api/workspace/state',json={'tabs':['b-0']},headers=headers).status_code==404
    assert a.put('/api/workspace/state',json={'tabs':[],'chatWidth':9999},headers=headers).status_code==400
    position={'document':'original','page':2,'offset':.3,'zoom':'width','rotation':90,'fingerprint':'test'}
    assert a.put('/api/paper/a-0/reading-position',json=position,headers=headers).status_code==200
    other=dict(position,document='translated',page=4)
    assert a.put('/api/paper/a-0/reading-position',json=other,headers=headers).status_code==200
    assert a.get('/api/paper/a-0/reading-position').json=={'original':position,'translated':other}
    assert b.get('/api/paper/a-0/reading-position').status_code==404
    assert a.put('/api/paper/a-0/reading-position',json=dict(position,page=-1),headers=headers).status_code==400
    fresh=app.test_client();login(fresh)
    assert fresh.get('/api/paper/a-0/reading-position').json['original']['page']==2



def test_failed_state_commit_is_reported_and_previous_data_survives(tmp_path, monkeypatch):
    import paperpilot.workspace_state as state_module
    app, _, _ = make_workbench_fixture(tmp_path, monkeypatch)
    client=app.test_client();headers={'X-CSRF-Token':login(client)}
    old={'tabs':['a-0'],'activePaper':'a-0','tabDocuments':{'a-0':'translated'}}
    assert client.put('/api/workspace/state',json=old,headers=headers).status_code==200
    original=state_module.get_db
    class FailedCommit:
        def __init__(self,db):self.db=db
        def execute(self,*args):return self.db.execute(*args)
        def commit(self):raise sqlite3.OperationalError('synthetic disk error')
        def rollback(self):self.db.rollback()
    with monkeypatch.context() as patch:
        patch.setattr(state_module,'get_db',lambda:FailedCommit(original()))
        response=client.put('/api/workspace/state',json={'tabs':[]},headers=headers)
        assert response.status_code==503 and response.json=={'error':'state_save_failed'}
    assert client.get('/api/workspace/state').json==old
    for value in ({'tabs':['a-0'],'tabDocuments':{'b-0':'original'}},{'tabs':[],'chatWidth':True},{'tabs':[],'taskRefs':[{'id':'x','kind':'upload','label':'x','secret':'not-allowed'}]}):
        assert client.put('/api/workspace/state',json=value,headers=headers).status_code==400
    assert client.put('/api/workspace/state',data='x'*65537,content_type='application/json',headers=headers).status_code in (400,413)
