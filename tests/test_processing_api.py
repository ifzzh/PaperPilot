"""Real Flask/SQLite/source/history boundaries, exclusively synthetic suppliers."""
import json
import time
from pathlib import Path

import pytest
import app as app_module
from tests.workbench_support import make_workbench_fixture
from tests.workbench_reader_support import fake_openai, install_reader_fixture
from tests.test_workbench import login
from tests.dual_translation_support import install
from ipaper.database import connection
from ipaper.processing.service import ProcessingService
from ipaper.processing.routes import register_processing_routes


@pytest.fixture
def application(tmp_path,monkeypatch):
    connection.close_db()
    with fake_openai() as origin:
        app,a,b=make_workbench_fixture(tmp_path,monkeypatch,count=5)
        install_reader_fixture(app,tmp_path,(a,b),monkeypatch,origin)
        service=ProcessingService(connection.DB_PATH,tmp_path/'papers',tmp_path/'settings.key',
                                 app_module.AGENTIC_CREDENTIAL_STORE,app_module.OUTBOUND_POLICY)
        register_processing_routes(app,service)
        install(app,tmp_path,(a,b),origin,monkeypatch)
        try:
            yield app
        finally:
            service.shutdown()
            connection.close_db()


def generate(client,token,paper='a-4',**kwargs):
    headers={'X-CSRF-Token':token}
    preview=client.post(f'/api/paper/{paper}/processing/preview',json={},headers=headers)
    assert preview.status_code==200,preview.json
    response=client.post(f'/api/paper/{paper}/processing/jobs',json={'preflightId':preview.json['preflightId'],**kwargs},headers=headers)
    assert response.status_code in (200,202),response.json
    job=response.json['job']
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        job=client.get('/api/processing/jobs/'+job['id']).json['job']
        if job['status'] not in ('queued','running','cancelling'):
            break
        time.sleep(.05)
    assert job['status']=='completed',job
    return preview.json,job


def test_structure_api_selection_chat_history_and_ownership(application):
    a,b=application.test_client(),application.test_client()
    token=login(a);login(b,'reader_two');headers={'X-CSRF-Token':token}
    assert a.post('/api/paper/a-4/processing/preview',json={}).status_code==403
    preview,job=generate(a,token)
    rid=job['resultId']
    blocks=a.get(f'/api/results/{rid}/blocks').json['blocks']
    assert len(blocks)==8
    assert blocks[1]['translation']['content']['text'].startswith('合成译文')
    assert '<table' not in json.dumps(blocks)
    response=a.post('/api/paper/a-4/sources',headers=headers,json={'resultId':rid,'blockId':blocks[1]['id'],'start':0,'end':20})
    assert response.status_code==200,response.json
    source=response.json['source']
    for path in [f'/api/results/{rid}',f'/api/results/{rid}/blocks',f'/api/documents/{source["documentId"]}/file',f'/api/sources/{source["id"]}',f'/api/processing/jobs/{job["id"]}',f'/api/results/{rid}/reading-position']:
        foreign=b.get(path)
        assert foreign.status_code==404,(path,foreign.json)
        assert foreign.headers['Cache-Control']=='private, no-store'
    for path in [f'/api/processing/jobs/{job["id"]}/cancel',f'/api/processing/jobs/{job["id"]}/resume']:
        assert a.post(path,json={}).status_code==403
    reply=a.post('/api/paper/chat',headers=headers,json={'paper_id':'a-4','messages':[{'role':'user','content':'Explain selected text'}],'source_ids':[source['id']]})
    assert reply.status_code==200,reply.text
    header,answer=reply.text.split('\n',1)
    assert '[S1]' in answer and '[S99]' in answer
    sid=json.loads(header)['session_id']
    history=a.get(f'/api/paper/chat/session?paper_id=a-4&session_id={sid}').json['session']['messages']
    assert history[-1]['content']==answer
    assert history[-1]['sources']==[{'label':'S1','sourceId':source['id']}]
    assert a.post('/api/paper/chat',headers=headers,json={'paper_id':'a-4','messages':[{'role':'user','content':'invalid'}],'source_ids':['/etc/passwd']}).status_code==400
    bad=a.post('/api/paper/a-4/sources',headers=headers,json={'resultId':rid,'blockId':blocks[1]['id'],'start':0,'end':9000})
    assert bad.status_code==400
    table=blocks[3]
    cell=a.post('/api/paper/a-4/sources',headers=headers,json={'resultId':rid,'blockId':table['id'],'start':0,'end':6,'field':'cell:0:0'})
    assert cell.status_code==200 and cell.json['source']['text']=='Method'
    pdf=a.post('/api/paper/a-4/pdf-sources',headers=headers,json={'document':'original','page':1,'text':'Synthetic reader validation'})
    assert pdf.status_code==200,pdf.json
    assert pdf.json['source']['precision']=='page'
    invalid=a.post('/api/paper/a-4/pdf-sources',headers=headers,json={'document':'original','page':1,'text':'This was never in the PDF'})
    assert invalid.status_code==409
    position={'blockId':blocks[1]['id'],'display':'bilingual','offset':.35,'sessionId':sid}
    assert a.put(f'/api/results/{rid}/reading-position',headers=headers,json=position).status_code==200
    assert a.get(f'/api/results/{rid}/reading-position').json['position']==position
    # The old original/translated file endpoints remain byte-identical.
    assert a.get('/api/paper/a-4/file').data==a.get(f'/api/documents/{source["documentId"]}/file').data
    a.delete('/api/auth/session',headers=headers)
    assert a.get(f'/api/results/{rid}/blocks').status_code==401


def test_historical_layouts_are_registered_without_retranslation(application):
    c=application.test_client();token=login(c)
    legacy=c.get('/api/paper/a-0/chinese/file').data
    results=c.get('/api/paper/a-0/results')
    assert results.status_code==200 and results.json['registrationWarning'] is None
    layout=next(r for r in results.json['results'] if r['kind']=='babeldoc_dual')
    assert layout['provenance']=='historical_config_unknown'
    assert c.get('/api/documents/'+layout['documentId']+'/file').data==legacy
    assert c.get('/api/processing/jobs').json['jobs']==[]


def test_partial_scope_reuse_and_budget_before_model(application):
    c=application.test_client();token=login(c);headers={'X-CSRF-Token':token}
    preview,job=generate(c,token,pages=[1])
    result=c.get('/api/results/'+job['resultId']).json['result']
    assert result['status']=='partial'
    blocks=c.get('/api/results/'+result['id']+'/blocks').json['blocks']
    assert all(b['translation'] is None for b in blocks if b['source'].get('page')==2)
    denied=c.post('/api/paper/a-4/processing/jobs',headers=headers,json={'preflightId':preview['preflightId'],'parseResultId':result['parseId'],'budget':{'requests':1}})
    assert denied.status_code==409 and denied.json['error']=='processing_scope_exceeds_budget'


def test_estimate_respects_cache_scope_config_and_never_creates_jobs(application):
    c = application.test_client(); token = login(c); headers = {"X-CSRF-Token": token}
    preview, job = generate(c, token, pages=[1])
    result = c.get('/api/results/'+job['resultId']).json['result']
    request = {"preflightId": preview['preflightId'], "parseResultId": result['parseId'], "pages": [1]}
    before = c.get('/api/processing/jobs').json
    assert c.post('/api/paper/a-4/processing/estimate', json=request).status_code == 403
    scope = c.post('/api/paper/a-4/processing/estimate', json=request, headers=headers)
    assert scope.status_code == 200, scope.json
    assert scope.json['estimate']['requests'] == 0
    assert scope.json['estimate']['cachedBlocks'] == scope.json['estimate']['selectedBlocks']
    second = c.post('/api/paper/a-4/processing/estimate', json={**request, 'pages':[2]}, headers=headers).json
    assert second['estimate']['requests'] > 0 and second['estimate']['cachedBlocks'] == 0
    new_language = c.post('/api/paper/a-4/processing/estimate', json={**request, 'targetLanguage':'ja'}, headers=headers).json
    assert new_language['estimate']['requests'] > 0 and new_language['estimate']['cachedBlocks'] == 0
    too_large = c.post('/api/paper/a-4/processing/estimate', json={**request, 'pages':[2], 'budget':{'requests':1}}, headers=headers).json
    assert too_large['exceedsBudget']
    assert c.get('/api/processing/jobs').json == before
    other = application.test_client(); other_token = login(other, 'reader_two')
    assert other.post('/api/paper/a-4/processing/estimate', json=request, headers={'X-CSRF-Token':other_token}).status_code == 404
