#!/usr/bin/env python3
"""Offline promotion of this release's verified, bounded acceptance artifacts.

This is an operator tool, not an upload/API format. Source is the controlled
acceptance directory produced by tests.verify_dual_translation_live. No user,
password, key, profile, old paper or settings row is copied. Both writers must be
stopped. Default dry-run validates all files and identities without modification.
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ipaper.processing.store import ProcessingStore
from ipaper.processing.common import encoded, fingerprint, identifier
from ipaper.processing.pipeline import file_digest
from ipaper.security.paths import safe_join, ensure_confined, user_storage_root


def insert(db,table,row):
    # table and column names come from the application's closed schema only.
    columns=','.join(row)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))


def promote(source_root, target_store, target_paper, *, apply=False):
    root=Path(source_root).resolve()
    report=json.loads((root/'result.json').read_text())
    receipt=json.loads((root/'request-receipt.json').read_text())
    if not report.get('passed') or receipt['ownerId']!=target_store.owner or receipt['paperId']!=target_paper:
        raise ValueError('acceptance_identity_mismatch')
    with target_store.connection() as db:
        target_store.paper_exists(db,target_paper)
        paper=db.execute('SELECT file_path FROM papers WHERE id=? AND owner_id=?',(target_paper,target_store.owner)).fetchone()
        source_file=ensure_confined(target_store.papers_root,paper['file_path'],must_exist=True,require_file=True)
        source_file.relative_to(user_storage_root(target_store.papers_root,target_store.owner))
        if file_digest(source_file)!=receipt['sourceSha256'] or report['sourceHash']!=receipt['sourceSha256']:
            raise ValueError('source_changed_before_promotion')
        if db.execute("SELECT 1 FROM processing_jobs WHERE status IN ('queued','running','cancelling')").fetchone():
            raise ValueError('processing_tasks_must_be_stopped')
        profile=db.execute('SELECT model,base_url,revision,created_at,updated_at FROM processing_profiles WHERE owner_id=?',(target_store.owner,)).fetchone()
        credential=db.execute("SELECT updated_at FROM agentic_secrets_v2 WHERE owner_id=? AND name='translate'",(target_store.owner,)).fetchone()
        if not profile or profile['created_at']!=profile['updated_at'] or not credential or credential[0]!=receipt['translateCredentialRevision']:
            raise ValueError('credential_configuration_changed')
    owner,paper_id=report['ownerId'],report['paperId']
    source_store=ProcessingStore(root/'ipaper.db',root/'papers',owner)
    rows={};files={};document_map={}
    # Open the controlled source read-only; never attach or migrate another DB.
    with sqlite3.connect(f'file:{root / "ipaper.db"}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if db.execute("SELECT 1 FROM processing_jobs WHERE status IN ('queued','running','cancelling')").fetchone():
            raise ValueError('source_tasks_must_be_stopped')
        rows['processing_documents']=[dict(r) for r in db.execute("SELECT * FROM processing_documents WHERE owner_id=? AND paper_id=? AND kind='original'",(owner,paper_id))]
        if not rows['processing_documents'] or any(r['sha256']!=receipt['sourceSha256'] for r in rows['processing_documents']):
            raise ValueError('document_version_mismatch')
        docs={r['id'] for r in rows['processing_documents']}
        rows['processing_results']=[dict(r) for r in db.execute("SELECT * FROM processing_results WHERE owner_id=? AND paper_id=? ORDER BY created_at,id",(owner,paper_id)) if r['document_id'] in docs]
        if any(r['status'] not in ('completed','partial') or r['kind'] not in ('document_parts','structure','structured_translation') for r in rows['processing_results']):
            raise ValueError('unpublished_acceptance_result')
        rows['processing_results'].sort(key=lambda r:r['kind']=='structured_translation')
        results={r['id'] for r in rows['processing_results']}
        if report['resultId'] not in results or len(results)>100:raise ValueError('result_set_mismatch')
        for table in ('processing_blocks','processing_block_translations','processing_translation_revisions'):
            rows[table]=[dict(r) for r in db.execute(f'SELECT t.* FROM {table} t JOIN processing_results r ON r.id=t.result_id WHERE r.owner_id=? AND r.paper_id=?',(owner,paper_id)) if r['result_id'] in results]
        rows['processing_jobs']=[dict(r) for r in db.execute('SELECT * FROM processing_jobs WHERE owner_id=? AND paper_id=? ORDER BY created_at',(owner,paper_id))]
        jobs={r['id'] for r in rows['processing_jobs']}
        if any(r['status']!='completed' or r['result_id'] not in results or r['parent_id'] for r in rows['processing_jobs']):
            raise ValueError('acceptance_job_not_completed')
        for table in ('processing_events','processing_attempts'):
            rows[table]=[dict(r) for r in db.execute(f'SELECT t.* FROM {table} t JOIN processing_jobs j ON j.id=t.job_id WHERE j.owner_id=? AND j.paper_id=?',(owner,paper_id))]
        rows['processing_sources']=[dict(r) for r in db.execute('SELECT * FROM processing_sources WHERE owner_id=? AND paper_id=?',(owner,paper_id))]
        if any(r['result_id'] not in results or r['document_id'] not in docs for r in rows['processing_sources']):
            raise ValueError('source_reference_mismatch')
        rows['chats']=[dict(r) for r in db.execute('SELECT * FROM chats WHERE owner_id=? AND paper_id=? AND session_id=?',(owner,paper_id,report['sessionId']))]
        if len(rows['chats'])!=1:raise ValueError('verified_chat_missing')
        rows['processing_chat_sources']=[dict(r) for r in db.execute('SELECT * FROM processing_chat_sources WHERE owner_id=? AND session_id=?',(owner,report['sessionId']))]
    if sum(len(values) for values in rows.values())>500000:raise ValueError('acceptance_row_limit')
    with target_store.connection() as db:
        for document in rows['processing_documents']:
            existing=db.execute("SELECT id FROM processing_documents WHERE owner_id=? AND paper_id=? AND kind='original' AND sha256=?",(target_store.owner,target_paper,document['sha256'])).fetchone()
            document_map[document['id']]=existing[0] if existing else document['id']
    for result in rows['processing_results']:
        identifier(result['id'])
        for entry in json.loads(result['manifest_json']).get('entries',[]):
            source=safe_join(source_store.artifact_directory(result['id']),entry['path'],must_exist=True,require_file=True)
            files[(result['id'],entry['path'])]=(source,entry['size'],entry['sha256'])
        if result['kind']=='structured_translation':
            config=json.loads(result['config_json'])
            if (config['model'],config['baseUrl'])!=(profile['model'],profile['base_url']):raise ValueError('model_configuration_changed')
            config['revision']=profile['revision'];result['config_json']=encoded(config);result['config_fingerprint']=fingerprint(config)
    for revision in rows['processing_translation_revisions']:
        source=safe_join(source_store.artifact_directory(revision['result_id']),revision['body_file'],must_exist=True,require_file=True)
        files[(revision['result_id'],revision['body_file'])]=(source,revision['bytes'],revision['sha256'])
    for source,size,sha in files.values():
        if not 0<=size<=1024**3 or source.stat().st_size!=size or file_digest(source)!=sha:raise ValueError('acceptance_file_hash_mismatch')
    total=sum(item[1] for item in files.values())
    if total>10*1024**3:raise ValueError('acceptance_size_limit')
    for table,values in rows.items():
        for row in values:
            if 'owner_id' in row:row['owner_id']=target_store.owner
            if 'paper_id' in row:row['paper_id']=target_paper
            if row.get('document_id'):row['document_id']=document_map[row['document_id']]
            if table=='processing_documents':row['file_ref']=str(source_file.relative_to(target_store.papers_root))
            if table=='processing_events':row.pop('sequence')
            if table=='processing_jobs':
                request=json.loads(row['request_json']);request['config']['revision']=profile['revision']
                row['request_json']=encoded(request);row['reserved_bytes']=0
                row['idempotency_key']=fingerprint({'paper':target_paper,'kind':row['kind'],'request':request,'budget':json.loads(row['budget_json'])})
    created=[]
    created_parent=None
    try:
        with target_store.connection(write=True) as db:
            occupied=db.execute('SELECT coalesce(sum(bytes),0) FROM processing_results WHERE owner_id=?',(target_store.owner,)).fetchone()[0]
            if occupied+total>target_store.quotas()[1]:raise ValueError('owner_quota_exceeded')
            for result in rows['processing_results']:
                if db.execute('SELECT 1 FROM processing_results WHERE id=?',(result['id'],)).fetchone() or target_store.artifact_directory(result['id']).exists():raise ValueError('target_result_already_exists')
            if apply:
                # A root-operated upgrade must not leave a root-only parent
                # above the correctly owned result directories. Existing
                # artifact parents belong to the deployment and are untouched.
                parent=target_store.artifact_directory(next(iter(results))).parent
                if not parent.exists():
                    parent.mkdir(mode=0o700)
                    created_parent=parent
                    if os.geteuid()==0:
                        stat=source_file.stat()
                        os.chown(parent,stat.st_uid,stat.st_gid)
                for rid in results:
                    target=target_store.artifact_directory(rid,create=True);created.append(target)
                    for (result_id,relative),(source,size,sha) in files.items():
                        if result_id!=rid:continue
                        destination=safe_join(target,relative);destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                        with source.open('rb') as reader,destination.open('xb') as writer:
                            shutil.copyfileobj(reader,writer,1024**2);writer.flush();os.fsync(writer.fileno())
                        destination.chmod(0o600)
                        if file_digest(destination)!=sha:raise ValueError('promotion_copy_hash_mismatch')
                if os.geteuid()==0:
                    stat=source_file.stat()
                    for directory in created:
                        for path in [directory,*directory.rglob('*')]:os.chown(path,stat.st_uid,stat.st_gid)
                for table,values in rows.items():
                    for row in values:
                        if table=='processing_documents' and document_map[row['id']]!=row['id']:continue
                        insert(db,table,row)
    except BaseException:
        for path in created:shutil.rmtree(path)
        if created_parent is not None:created_parent.rmdir()
        raise
    return {'apply':apply,'results':len(results),'files':len(files),'bytes':total,'chats':len(rows['chats']),
            'jobs':len(jobs),'owner':target_store.owner,'paper':target_paper,'credentialsCopied':False,'oldRowsOverwritten':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','database','papers','owner','paper'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    print(json.dumps(promote(args.source,ProcessingStore(args.database,args.papers,args.owner),args.paper,apply=args.apply)))

if __name__=='__main__':main()
