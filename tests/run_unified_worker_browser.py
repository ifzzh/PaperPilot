"""Explicit isolated browser/real Document Worker acceptance; no cloud tasks."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.request
import uuid


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--real-worker',action='store_true')
    args=parser.parse_args()
    if not args.real_worker:
        print('offline: pass --real-worker to start isolated Docker acceptance')
        return
    root=Path(__file__).resolve().parents[1]
    component=json.loads((root/'docker/release-components.json').read_text())['document_worker']
    image=component['repository']+'@'+component['digest']
    ident='ipaper-p1-'+uuid.uuid4().hex[:10]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='ipaper-unified-document-') as temporary:
        directory=Path(temporary);jobs=directory/'jobs';jobs.mkdir(mode=0o2770);jobs.chmod(0o2770)
        token=directory/'token';token.write_text(secrets.token_urlsafe(48));token.chmod(0o440)
        network_created=False
        try:
            run('docker','network','create','--internal',ident,stdout=subprocess.DEVNULL)
            network_created=True
            run('docker','run','-d','--name',ident,'--network',ident,
                '--user',f'10003:{os.getgid()}',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                '--cpus','2','--memory','3g','--pids-limit','128',
                '--tmpfs','/tmp:size=256m,mode=1777',
                '-v',str(jobs)+':/work/document-jobs',
                '-v',str(token)+':/run/secrets/ipaper_document_worker_token:ro',
                image,stdout=subprocess.DEVNULL)
            inspect=json.loads(subprocess.check_output(['docker','inspect',ident]))[0]
            worker_url='http://'+inspect['NetworkSettings']['Networks'][ident]['IPAddress']+':7193'
            last_error=''
            for _ in range(50):
                try:
                    with opener.open(worker_url+'/healthz',timeout=1) as response:
                        if response.status==200:break
                except OSError as exc:last_error=type(exc).__name__;time.sleep(.2)
            else:
                logs=subprocess.run(['docker','logs','--tail','30',ident],capture_output=True,text=True)
                print(logs.stdout,logs.stderr)
                print(subprocess.check_output(['docker','inspect','--format','{{json .State}}',ident],text=True))
                raise RuntimeError('isolated worker did not become healthy: '+last_error)
            inspect=json.loads(subprocess.check_output(['docker','inspect',ident]))[0]
            assert {m['Destination'] for m in inspect['Mounts']}=={'/work/document-jobs','/run/secrets/ipaper_document_worker_token'}
            network=json.loads(subprocess.check_output(['docker','network','inspect',ident]))[0]
            assert network['Internal'] is True
            run('docker','exec',ident,'python','-c',
                'import socket\ntry:\n socket.create_connection(("1.1.1.1",443),1)\nexcept OSError:\n pass\nelse:\n raise SystemExit("unexpected public egress")')
            environment={**os.environ,'PYTHON_DOTENV_DISABLED':'1','IPAPER_BROWSER_REAL_WORKER':'1',
                'IPAPER_DOCUMENT_WORKER_URL':worker_url,
                'IPAPER_DOCUMENT_JOBS_ROOT':str(jobs),
                'IPAPER_DOCUMENT_WORKER_TOKEN_FILE':str(token)}
            run('npx','playwright','test','--config','playwright.unified.config.ts','upload.spec.ts',cwd=root/'frontend',env=environment)
            assert not list(jobs.iterdir()),'completed upload staging was not cleaned'
            print(json.dumps({'worker':image,'http_upload_and_read':'passed','staging_cleanup':'passed','public_egress':'blocked','production_asset_mounts':False}))
        finally:
            subprocess.run(['docker','rm','-f',ident],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if network_created:subprocess.run(['docker','network','rm',ident],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
