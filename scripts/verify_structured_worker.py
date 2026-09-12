#!/usr/bin/env python3
"""Local HTTP Worker acceptance; replays an existing archive, never calls cloud."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ipaper.document_worker.client import DocumentWorkerClient


def digest(path):
    sha=hashlib.sha256()
    with path.open('rb') as handle:
        for data in iter(lambda:handle.read(1024**2),b''):
            sha.update(data)
    return sha.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('url','jobs','token-file','archive','source','report'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    target=urlsplit(args.url)
    if target.scheme!='http' or not ipaddress.ip_address(target.hostname).is_private:
        parser.error('Acceptance requires an explicit local/internal Worker address.')
    client=DocumentWorkerClient(base_url=args.url,jobs_root=args.jobs,token_file=args.token_file)
    import requests
    assert client.health(),'worker_not_healthy'
    rejected=requests.get(args.url+'/v1/jobs/'+str(uuid.uuid4()),timeout=5)
    assert rejected.status_code==401
    source,archive=Path(args.source),Path(args.archive)
    job=str(uuid.uuid4());start=time.monotonic()
    try:
        with source.open('rb') as pdf,archive.open('rb') as bundle:
            client.stage_structure(job,bundle,pdf)
        client.create(job,'mineru_structure')
        state=client.wait(job,timeout=300)
        assert state['status']=='completed',state.get('error')
        manifest=client.verified_manifest(job,'mineru_structure')
        output=client.output(job)
        data=client.result_json(job)
        assert data['sourceSha256']==digest(source)
        blocks=[json.loads(line) for line in (output/'blocks.jsonl').read_text('utf-8').splitlines()]
        assert blocks and any(block['source']['precision']=='region' for block in blocks)
        report={'supplierCalls':0,'transport':'real Document Worker HTTP/subprocess','sourceSha256':digest(source),
                'archiveSha256':digest(archive),'pageCount':data['pageCount'],'blockCount':len(blocks),
                'precisions':{kind:sum(b['source']['precision']==kind for b in blocks) for kind in ('region','page','none')},
                'firstText':blocks[0]['text'][:100],'entries':manifest['entries'],'elapsedSeconds':round(time.monotonic()-start,3),
                'anonymousRejected':True,'retainedJson':[e['path'] for e in manifest['entries'] if e['path'].endswith('.json')]}
        destination=Path(args.report);destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2));destination.chmod(0o600)
        print(json.dumps({key:report[key] for key in ('supplierCalls','pageCount','blockCount','precisions','elapsedSeconds','anonymousRejected')}))
    finally:
        client.cleanup(job)
    assert not client.job_directory(job).exists(),'worker_cleanup_failed'


if __name__=='__main__':
    main()
