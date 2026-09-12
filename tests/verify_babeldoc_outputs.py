"""Run the actual pinned BabelDOC program against a container-local fake model.

Not a paid-service or translation-quality test. Own generated PDF content CC0;
fonts/models downloaded by BabelDOC keep their upstream licenses.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import fitz

root=Path('/work/acceptance');root.mkdir(exist_ok=True)
requests_seen=[]
class Fake(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0'))
        if self.path!='/v1/chat/completions' or not 0<n<1024**2 or len(requests_seen)>100:
            self.send_error(400);return
        data=json.loads(self.rfile.read(n));prompt=data['messages'][-1]['content'];requests_seen.append({'chars':len(prompt),'model':data.get('model')})
        if '## Here is the input:' in prompt:
            units=json.loads(prompt.rsplit('## Here is the input:',1)[1].strip())
            text=json.dumps([{'id':u['id'],'output':'合成译文：'+u['input']} for u in units],ensure_ascii=False)
        elif 'Input:\n\n' in prompt:
            text='合成译文：'+prompt.rsplit('Input:\n\n',1)[1]
        else:
            text='[]'
        body=json.dumps({'id':'isolated-fake','object':'chat.completion','created':0,'model':'offline-fixture',
            'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

server=ThreadingHTTPServer(('127.0.0.1',0),Fake)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
report={'realSupplierCalls':0,'program':'BabelDOC 0.6.4','results':[]}
try:
    for mode in ('mono','dual'):
        work=root/mode;work.mkdir(exist_ok=True)
        with fitz.open() as doc:
            page=doc.new_page()
            page.insert_text((60,70),'Synthetic layout translation validation',fontsize=17)
            for row in range(8):page.insert_text((60,120+row*24),f'This synthetic document is owned by the test. Paragraph {row+1}.',fontsize=11)
            doc.save(work/'input.pdf')
        count=len(requests_seen)
        env=dict(os.environ);env.update(PYTHONPATH='/app',NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost',XDG_CACHE_HOME='/work/acceptance/cache')
        payload={'model':'offline-fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'synthetic-only-not-a-real-key','output_mode':mode}
        with (work/'program.log').open('wb') as log:
            result=subprocess.run([sys.executable,'-m','ipaper.translation_worker.babeldoc_runner'],input=(json.dumps(payload)+'\n').encode(),cwd=work,env=env,stdout=log,stderr=log,timeout=300)
        assert result.returncode==0,f'babeldoc_{mode}_failed'
        output=work/f'input.zh.{mode}.pdf'
        assert output.is_file(),f'missing_{mode}_output'
        assert not (work/f'input.zh.{"dual" if mode=="mono" else "mono"}.pdf').exists(),'unrequested_output'
        with fitz.open(output) as doc:
            text='\n'.join(page.get_text() for page in doc)
            assert '合成译文' in text,'fake_translation_not_visible_in_pdf'
            doc[0].get_pixmap().save(work/'render.png')
            report['results'].append({'mode':mode,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'pages':doc.page_count,'textSample':text[:150],
                                      'fakeRequests':len(requests_seen)-count,'sourceHash':hashlib.sha256((work/'input.pdf').read_bytes()).hexdigest()})
        print(json.dumps({'mode':mode,'passed':True,'fakeRequests':len(requests_seen)-count}),flush=True)
finally:
    server.shutdown();server.server_close()
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
