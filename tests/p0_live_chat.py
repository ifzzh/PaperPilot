"""Opt-in release acceptance; one real request, credentials only via stdin."""
import argparse,json,os,sys,tempfile,re
from pathlib import Path
from types import SimpleNamespace
from pytest import MonkeyPatch
from tests.workbench_support import make_workbench_fixture
from tests.workbench_reader_support import install_reader_fixture
from tests.test_workbench import login
from paperpilot.routes.agent_routes import agent_chat_route
from paperpilot.security.outbound import OutboundPolicy
from openai import OpenAI,DefaultHttpxClient


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--selection-sample',type=Path)
    args=parser.parse_args()
    if not args.live: print('offline: no model calls');return
    os.umask(0o077);args.evidence.mkdir(parents=True,exist_ok=True)
    prompt='这是合成验收样例。请只回复：已收到合成样例。'
    if args.selection_sample:
        sample=json.loads(args.selection_sample.read_text())
        assert sample['document'] in ('original','translated') and 1 <= sample['page'] <= 100000
        assert 0 < len(sample['quote']) <= 8000 and len(sample['question']) <= 2000
        variant='译文' if sample['document']=='translated' else '原文'
        prompt=f"引用《{sample['title']}》{variant}第 {sample['page']} 页：\n> "+sample['quote'].replace('\n','\n> ')+ '\n\n'+sample['question']
    config=json.loads(sys.stdin.buffer.read(65537))
    policy=OutboundPolicy(public_origins=[config['origin']],private_origins=[],transfer_origins=[],proxy_fake_ip_networks=config.get('fake_ip_ranges',[]))
    policy.validate(config['base_url'],purpose='ai')
    proxy={k:v for k,v in os.environ.items() if k.upper() in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY')}
    with tempfile.TemporaryDirectory() as root, MonkeyPatch.context() as patch:
        app,a,b=make_workbench_fixture(root,patch,count=1)
        install_reader_fixture(app,root,(a,b),patch,'http://127.0.0.1:1')
        for k,v in proxy.items():patch.setenv(k,v)
        calls=[]
        client=OpenAI(api_key=config.pop('token'),base_url=config['base_url'],max_retries=0,timeout=120,http_client=DefaultHttpxClient(follow_redirects=False))
        def create(**kwargs):
            if calls: raise RuntimeError('duplicate_request_forbidden')
            policy.validate(config['base_url'],purpose='ai');calls.append(1)
            kwargs.update(model=config['model'],max_completion_tokens=512,extra_body={'enable_thinking':False})
            (args.evidence/'request-started.json').write_text(json.dumps({'requests':1}))
            try:
                stream=client.chat.completions.create(**kwargs)
                def observe():
                    stats={'chunks':0,'empty_choices':0,'content_chars':0,'reasoning_chars':0,'finish_reasons':[]}
                    try:
                        for chunk in stream:
                            stats['chunks']+=1
                            if not chunk.choices:stats['empty_choices']+=1
                            for choice in chunk.choices:
                                stats['content_chars']+=len(getattr(choice.delta,'content',None) or '')
                                stats['reasoning_chars']+=len(getattr(choice.delta,'reasoning_content',None) or '')
                                if choice.finish_reason:stats['finish_reasons'].append(choice.finish_reason)
                            yield chunk
                    finally:
                        (args.evidence/'stream-stats.json').write_text(json.dumps(stats))
                return observe()
            except Exception as error:
                code=getattr(error,'code',None)
                safe={'error_type':type(error).__name__,'http_status':getattr(error,'status_code',None),'code':code if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',code) else None}
                (args.evidence/'upstream-error.json').write_text(json.dumps(safe))
                raise
        patch.setattr(agent_chat_route,'create_openai_client',lambda *_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        c=app.test_client();csrf=login(c)
        with (args.evidence/'attempt.json').open('x') as f:json.dump({'attempts':1,'model':config['model'],'max_completion_tokens':512,'max_retries':0},f);f.flush();os.fsync(f.fileno())
        result=c.post('/api/paper/chat',json={'paper_id':'a-0','messages':[{'role':'user','content':prompt}]},headers={'X-CSRF-Token':csrf})
        (args.evidence/'route-result.json').write_text(json.dumps({'status':result.status_code,'mimetype':result.mimetype,'requests':len(calls),'has_protocol_newline':'\n' in result.text}))
        header,answer=result.text.split('\n',1);sid=json.loads(header)['session_id']
        path=f'/api/paper/chat/session?paper_id=a-0&session_id={sid}'
        history=c.get(path).json['session']['messages']
        (args.evidence/'stream-result.json').write_text(json.dumps({'answer':answer,'history':history},ensure_ascii=False,indent=2))
        assert len(calls)==1 and answer.strip() and 'llm_request_failed' not in answer
        assert history[-1]['role']=='assistant' and history[-1]['content']==agent_chat_route.strip_think_blocks(answer)
        fresh=app.test_client();login(fresh)
        assert fresh.get(path).json['session']['messages']==history
        other=app.test_client();login(other,'reader_two');assert other.get(path).status_code==404
        report={'passed':True,'requests':len(calls),'model':config['model'],'answer':answer,'history_verified':True,'fresh_session_verified':True,'owner_isolation':True}
        (args.evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));client.close()

if __name__=='__main__':
    try:main()
    except Exception:print('live_chat_acceptance_failed_no_retry');raise SystemExit(1)
