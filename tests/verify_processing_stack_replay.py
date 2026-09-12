"""Run only inside a candidate Web container on isolated staged test files."""
import json
import sys
sys.path.insert(0,"/app")
import uuid
from pathlib import Path
from ipaper.processing.store import ProcessingStore
from ipaper.document_worker.client import DocumentWorkerClient
from ipaper.processing.pipeline import file_digest
from ipaper.security.identity import Identity,run_as_identity
from ipaper.database.dao.paper_dao import PaperDAO
root=Path('/acceptance');assert (root/'ISOLATED').is_file()
user=json.loads((root/'identity.json').read_text())
store=ProcessingStore('/app/db/ipaper.db','/data/papers',user['id'])
client=DocumentWorkerClient()

def execute():
    paper=PaperDAO.get_paper('stack-synthetic');source=Path(paper['file_path'])
    job=str(uuid.uuid4())
    try:
        with source.open('rb') as pdf,(root/'cloud-result.zip').open('rb') as archive:
            client.stage_structure(job,archive,pdf)
        client.create(job,'mineru_structure')
        status=client.wait(job,timeout=300)
        assert status['status']=='completed',status.get('error')
        data=client.result_json(job);manifest=client.verified_manifest(job,'mineru_structure')
        doc=store.register_document('stack-synthetic',kind='original',sha256=file_digest(source),size=source.stat().st_size,
                                   geometry=data['pages'],file_ref=str(source.relative_to('/data/papers')))
        parsed=store.new_result(doc,'structure',{'normalizer':data['normalizer'],'evidence':'saved_real_archive_replay'})
        store.publish_structure(parsed,client.output(job),manifest)
        translated=store.new_result(doc,'structured_translation',{'model':'隔离模拟模型','evidence':'synthetic_translation'},parse_id=parsed)
        after=-1
        while True:
            blocks=store.blocks(parsed,after=after,limit=50)
            if not blocks: break
            for block in blocks:
                generation,_=store.begin_translation(translated,block['id'])
                store.finish_translation(translated,block['id'],generation,{'text':'合成译文：'+block['text'],
                    'caption':block.get('caption',''),'table':block.get('table')})
            after=blocks[-1]['order']
        with store.connection(write=True) as db: db.execute("UPDATE processing_results SET status='completed' WHERE id=?",(translated,))
        report={'sourceSha256':file_digest(source),'blocks':data['blockCount'],'parseResult':parsed,'translationResult':translated,
                'realWorkerHttp':True,'paidCalls':0,'translation':'synthetic','productionDatabaseCopied':False}
        (root/'replay.json').write_text(json.dumps(report));print(json.dumps(report))
    finally: client.cleanup(job)
run_as_identity(Identity(user['id'],user['username'],user['role']),execute)
