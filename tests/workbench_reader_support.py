"""Real PDF/chat routes backed exclusively by synthetic temporary assets and a loopback LLM."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import shutil
import threading
import time

from paperpilot.database.dao.paper_dao import PaperDAO
from paperpilot.core.base_paper import Paper
from paperpilot.database.dao.settings_dao import SettingsDAO
from paperpilot.security.identity import Identity, run_as_identity
from paperpilot.security.paths import paper_path, paper_asset_paths
from paperpilot.security.credentials import generate_settings_key
from paperpilot.security.agentic_credentials import AgenticCredentialStore
from paperpilot.security.outbound import OutboundPolicy, ValidatedTarget, OutboundPolicyError
from paperpilot.routes.agent_routes import agent_chat_route, agent_translate_route
from paperpilot.tools.basic_tools.chat_history_manager import ChatHistoryManager
import app as app_module


@contextmanager
def fake_openai():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/v1/chat/completions' or not 0 < length < 1024 * 1024:
                self.send_error(400); return
            data = json.loads(self.rfile.read(length))
            prompt = data['messages'][-1]['content']
            if prompt == 'startup-failure':
                self.send_error(400); return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            answer = ['你好，', '这是合成回答。\n', '<img src=x onerror=alert(1)>']
            if prompt == 'slow':
                answer = ['开始'] + [' 合成片段'] * 15
            try:
                for index, text in enumerate(answer):
                    event = {'id':'synthetic', 'object':'chat.completion.chunk','created':0,'model':'fixture',
                             'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode())
                    self.wfile.flush()
                    if prompt == 'mid-failure' and index == 0:
                        self.wfile.write(b'data: not-json\n\n'); self.wfile.flush(); return
                    if prompt == 'slow':
                        time.sleep(.1)
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


def install_reader_fixture(application, root, users, monkeypatch, origin):
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.delenv(name,raising=False)
    root=Path(root); (root/'papers').mkdir(exist_ok=True); store=app_module.paper_store
    application.config['PAPERPILOT_START_BACKGROUND_TASKS']=False
    monkeypatch.setattr(agent_chat_route,'paper_store',store)
    monkeypatch.setattr(agent_chat_route,'chat_history_manager',ChatHistoryManager(store))
    monkeypatch.setattr(agent_translate_route,'paper_store',store)
    key=generate_settings_key(root/'settings.key'); credentials=AgenticCredentialStore.from_key_file(str(key))
    class LoopbackFixturePolicy(OutboundPolicy):
        # Production policy intentionally forbids loopback. This exact-origin test
        # policy exists only in this fixture and can reach only the ephemeral fake.
        def validate(self, url, *, purpose):
            if purpose != 'ai' or url != origin + '/v1':
                raise OutboundPolicyError('test_origin_only')
            return ValidatedTarget(url, origin, ('127.0.0.1',))
    policy=LoopbackFixturePolicy(public_origins=[],private_origins=[],transfer_origins=[])
    common=dict(get_categories=lambda:{'children':[]},get_category_path=lambda *_:None,
                get_papers_in_category=lambda *_:[],agentic_settings_file='unused',credential_store=credentials,outbound_policy=policy)
    agent_chat_route.register_agent_chat_routes(application,**common)
    agent_translate_route.register_agent_translate_routes(application,translation_tasks={},translation_tasks_lock=threading.Lock(),
        save_paper_metadata=lambda *_:None,upload_folder=str(root/'papers'),**common)
    assets=Path(__file__).parent/'fixtures/workbench'
    with application.app_context():
        for user,prefix in zip(users,('a','b','c')):
            def seed():
                credentials.set('interpret','synthetic-test-only')
                SettingsDAO.save_setting('agentic_settings',{'llmConfigs':{'interpret':{'llmBaseUrl':origin+'/v1','llmModel':'fixture'}}})
                for i in range(1 if prefix=='b' else 4):
                    paper=store.get(f'{prefix}-{i}')
                    if not paper and prefix=='c':
                        paper=Paper(id=f'c-{i}',title='合成阅读验证文献',authors='PaperPilot tests',has_chinese_version=i==0)
                    if not paper: continue
                    target=paper_path(root/'papers','root',f'{prefix}-{i}.pdf',create_parent=True)
                    if i==0: shutil.copyfile(assets/'original.pdf',target)
                    elif i==1: shutil.copyfile(assets/'encrypted.pdf',target)
                    elif i==2: target.write_bytes(b'not a PDF')
                    paper.filename=target.name;paper.file_path=str(target)
                    PaperDAO.save_paper(paper.to_dict());store.upsert(paper,category_id='root',category_path=['Root'])
                    if i==0: shutil.copyfile(assets/'translated.pdf',paper_asset_paths(root/'papers',target).chinese_dual)
            run_as_identity(Identity(user['id'],user['username'],user['role']),seed)
