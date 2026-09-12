"""MinerU v4 transport contract with local in-memory responses; no cloud calls."""
import io,json
import pytest
from tests.test_processing_store import store
from ipaper.processing.jobs import ProcessingJobs
from ipaper.processing.cloud import MinerUCloud
from ipaper.processing.common import ProcessingError


def running(store):
    jobs=ProcessingJobs(store);job,_=jobs.create('paper','parse',{})
    jobs.claim(job['id']);return jobs,job['id']


def test_accepted_batch_saved_before_uncertain_upload_and_not_recreated(store,tmp_path,monkeypatch):
    import ipaper.processing.cloud as module
    jobs,jid=running(store);cloud=MinerUCloud('synthetic-key',None)
    path=tmp_path/'input.pdf';path.write_bytes(b'own fixture')
    calls=[];saved=[]
    def response(method,url,payload):
        calls.append((method,url,payload))
        assert payload['model_version']=='vlm' and set(payload)=={'files','model_version'}
        name=payload['files'][0]['name'];assert name.endswith('.pdf') and len(name)==40
        return {'batch_id':'accepted-batch','file_urls':['https://transfer.example.test/opaque']}
    monkeypatch.setattr(cloud,'_json',response)
    def upload(*_,**kwargs):
        assert saved==['accepted-batch']
        raise TimeoutError()
    monkeypatch.setattr(module,'guarded_request',upload)
    with pytest.raises(ProcessingError,match='upload_unknown'):
        cloud.submit(path,'part-0',jobs,jid,lambda batch:saved.append(batch))
    assert len(calls)==1
    with store.connection() as db:
        assert [r[0] for r in db.execute('SELECT status FROM processing_attempts ORDER BY created_at')]==['completed','unknown']


def test_non_json_and_oversized_response_fail_without_provider_details(monkeypatch):
    import ipaper.processing.cloud as module
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def iter_content(self,_):yield b'<html>not JSON</html>'
    monkeypatch.setattr(module.requests,'request',lambda *a,**k:Response())
    cloud=MinerUCloud('synthetic-key',None)
    with pytest.raises(ProcessingError,match='response_unknown'):cloud._json('POST','/file-urls/batch',{})
    monkeypatch.setattr(Response,'iter_content',lambda *_:iter([b'x'*(1024**2+1)]))
    with pytest.raises(ProcessingError,match='response_too_large'):cloud._json('POST','/file-urls/batch',{})


def test_poll_ten_seconds_then_existing_batch_download(store,tmp_path,monkeypatch):
    import ipaper.processing.cloud as module
    jobs,jid=running(store);cloud=MinerUCloud('synthetic-key',None);polls=[];sleeps=[]
    def response(method,path,payload=None):
        assert method=='GET' and path=='/extract-results/batch/known-batch'
        polls.append(path)
        return {'extract_result':[{'state':'done','full_zip_url':'https://transfer.example.test/result'} if len(polls)>1 else {'state':'running'}]}
    class Response:
        status_code=200;raw=io.BytesIO(b'synthetic-zip-bytes')
        def __enter__(self):return self
        def __exit__(self,*_):pass
    monkeypatch.setattr(cloud,'_json',response)
    monkeypatch.setattr(module.time,'sleep',sleeps.append)
    monkeypatch.setattr(module,'guarded_request',lambda *a,**k:Response())
    cloud.wait_download('known-batch',tmp_path/'result.zip',jobs,jid)
    assert sum(sleeps)==pytest.approx(10) and len(polls)==2
    assert (tmp_path/'result.zip').read_bytes()==b'synthetic-zip-bytes'
    with store.connection() as db:assert db.execute('SELECT count(*) FROM processing_attempts').fetchone()[0]==0


def test_poll_deadline_does_not_create_task(store,tmp_path,monkeypatch):
    import ipaper.processing.cloud as module
    jobs,jid=running(store);cloud=MinerUCloud('synthetic-key',None)
    ticks=iter([0,1801]);monkeypatch.setattr(module.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(cloud,'_json',lambda *_:pytest.fail('must not submit or poll after deadline'))
    with pytest.raises(ProcessingError,match='poll_timeout'):cloud.wait_download('known-batch',tmp_path/'result.zip',jobs,jid)
