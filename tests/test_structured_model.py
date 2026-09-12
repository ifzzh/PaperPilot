from types import SimpleNamespace
import json
import httpx
import pytest
from tests.test_processing_store import store
from ipaper.processing.common import ProcessingError
from ipaper.processing.jobs import ProcessingJobs
from ipaper.processing.translation import StructuredModel,units_for


@pytest.fixture(autouse=True)
def isolate_transport(monkeypatch):
    for name in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
        monkeypatch.delenv(name,raising=False)

def setup(store,create):
    jobs=ProcessingJobs(store)
    job,_=jobs.create('paper','translate',{})
    jobs.claim(job['id'])
    seen=[]
    class Policy:
        def validate(self,url,**kw):
            assert url=='https://example.test/v1' and kw=={'purpose':'ai'}
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0 and kwargs['timeout']==120
            seen.append(kwargs)
            self.chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        def __enter__(self):return self
        def __exit__(self,*_):seen[-1]['http_client'].close()
    return StructuredModel(Policy(),{'key':'synthetic-only','model':'fake','baseUrl':'https://example.test/v1'},client_factory=Client),jobs,job['id'],seen


def response(value,finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value),finish_reason=finish)],usage=SimpleNamespace(prompt_tokens=1,completion_tokens=2))


@pytest.mark.parametrize('output,code', [('not json','invalid'),('{"invented":"text"}','id_mismatch'),('{"b/text/0":123}','invalid_translation_text')])
def test_model_malformed_output_never_associates_arbitrary_blocks(store,output,code):
    calls=[]
    model,jobs,jid,seen=setup(store,lambda **kwargs:(calls.append(kwargs) or response(output)))
    with pytest.raises(ProcessingError,match=code):
        model.translate(units_for({'id':'b','type':'text','text':'Source'}),'zh-CN',jobs,jid)
    assert len(calls)==1 and len(seen)==1
    assert json.loads(jobs.get(jid)['usage_json'])['requests']==1


def test_timeout_has_one_attempt_and_unknown_result(store):
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        raise TimeoutError()
    model,jobs,jid,_=setup(store,create)
    with pytest.raises(ProcessingError,match='model_result_unknown'):
        model.translate(units_for({'id':'b','type':'text','text':'Source'}),'zh-CN',jobs,jid)
    assert len(calls)==1
    with store.connection() as db:
        assert db.execute('SELECT status FROM processing_attempts').fetchone()[0]=='unknown'


def test_only_explicit_429_is_retried_once(store):
    from openai import RateLimitError
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        raise RateLimitError('test-only',response=httpx.Response(429,request=httpx.Request('POST','https://example.test/v1')),body=None)
    model,jobs,jid,_=setup(store,create)
    with pytest.raises(ProcessingError,match='rate_limited'):
        model.translate(units_for({'id':'b','type':'text','text':'Source'}),'zh-CN',jobs,jid)
    assert len(calls)==2
    assert json.loads(jobs.get(jid)['usage_json'])['requests']==2


def test_real_transport_child_has_wall_deadline_and_no_key_in_command(monkeypatch):
    import threading,time,subprocess
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from ipaper.processing.translation import process_request
    received=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']));received.set()
            time.sleep(5)
            try:self.send_response(500);self.end_headers()
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    real_popen=subprocess.Popen;commands=[]
    def launch(args,**kwargs):
        commands.append(args)
        assert 'synthetic-secret-only' not in repr(args)
        assert kwargs.get('start_new_session') is True and kwargs.get('stderr')==subprocess.DEVNULL
        return real_popen(args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',launch)
    try:
        start=time.monotonic()
        result=process_request({'model':'fake','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','key':'synthetic-secret-only'},
            [{'role':'user','content':'Synthetic deadline probe'}],32,deadline=2)
        assert result=={'status':'unknown'}
        assert time.monotonic()-start<3.5
        assert received.is_set() and len(commands)==1
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def test_thinking_adapter_is_exact_and_part_of_effective_options():
    from ipaper.processing.translation import generation_options
    assert generation_options('qwen3.8-flash')=={'temperature':0,'extra_body':{'enable_thinking':False}}
    assert generation_options('unknown-model')=={'temperature':0}
    assert generation_options('qwen-unknown-alias')=={'temperature':0}
