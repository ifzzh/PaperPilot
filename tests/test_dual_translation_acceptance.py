"""The opt-in real acceptance program is first exercised with zero paid calls."""
import io
import json
import uuid
import pytest
from types import SimpleNamespace


def test_live_program_is_offline_by_default(tmp_path,monkeypatch,capsys):
    from tests.verify_dual_translation_live import main
    monkeypatch.setattr('sys.argv',['verify','--root',str(tmp_path)])
    main()
    assert json.loads(capsys.readouterr().out)['requests']==0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('relative_root',[False,True])
def test_complete_live_program_with_fake_suppliers(tmp_path,monkeypatch,relative_root):
    from tests.verify_dual_translation_live import main
    from tests.workbench_reader_support import fake_openai
    from tests.test_structured_document import pdf
    from tests.test_processing_pipeline import LocalDocument
    from tests.dual_translation_support import SyntheticCloud
    from ipaper.processing.pipeline import file_digest
    source=tmp_path/'source.pdf';pdf(source,22)
    stage=tmp_path/'worker';stage.mkdir()
    root=tmp_path/'acceptance'
    with fake_openai() as origin:
        config={'paperId':str(uuid.uuid4()),'ownerId':str(uuid.uuid4()),'title':'Own synthetic 22-page acceptance',
                'sourceSha256':file_digest(source),'expectedPages':22,'translateCredentialRevision':'fake-revision',
                'mineruKey':'test-only','publicOrigins':[],'transferOrigins':[],
                'translation':{'model':'fixture','baseUrl':origin+'/v1','key':'synthetic-model-only','revision':str(uuid.uuid4())},
                'chat':{'model':'fixture','baseUrl':origin+'/v1','key':'synthetic-chat-only'}}
        monkeypatch.setattr('sys.stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(config).encode())))
        import os
        root_argument=os.path.relpath(root) if relative_root else str(root)
        monkeypatch.setattr('sys.argv',['verify','--live','--root',root_argument,'--original',str(source),'--document-origin','http://unused.invalid',
                                      '--document-staging',str(stage),'--document-token',str(tmp_path/'unused-token')])
        class Policy:
            def validate(self,url,**kwargs):assert url==origin+'/v1'
        main({'policy':Policy(),'document':LocalDocument(jobs_root=stage),'cloud':SyntheticCloud})
    result=json.loads((root/'result.json').read_text())
    assert result['passed'] and result['cloudCreates']==result['chatRequests']==1
    assert result['pages']==22 and result['parsedBlocks']==88 and result['cacheRequests']==0
    assert len(result['translatedBlocks'])<=6
    assert result['history'][-1]['sources']
    assert json.loads((root/'stage.json').read_text())['stage']=='completed'
    stream=json.loads((root/'chat-response.json').read_text())
    assert stream['status']==200 and stream['contentType'].startswith('text/plain')
    assert json.loads((root/'chat-history.json').read_text())==result['history']
    # Synthetic test key of the fixture may exist; provider keys must not be
    # written even in this controlled rehearsal database or diagnostic files.
    for path in root.rglob('*'):
        if path.is_file():
            payload=path.read_bytes()
            assert b'synthetic-model-only' not in payload and b'synthetic-chat-only' not in payload

    # Promote only verified new artifacts into a distinct synthetic account/DB.
    import sqlite3,shutil
    import pytest
    from ipaper.processing.schema import SCHEMA
    from ipaper.processing.store import ProcessingStore
    from ipaper.processing.profiles import StructuredProfiles,StructuredCredentialCipher
    from ipaper.processing.sources import Sources
    from scripts.promote_processing_acceptance import promote
    target_root=tmp_path/'target-papers';target_root.mkdir()
    original=target_root/'.users'/config['ownerId']/'paper.pdf';original.parent.mkdir(parents=True)
    shutil.copyfile(source,original)
    target_db=tmp_path/'target.db'
    with sqlite3.connect(target_db) as db:
        db.executescript("""CREATE TABLE papers(id TEXT PRIMARY KEY,owner_id TEXT,file_path TEXT);
          CREATE TABLE users(id TEXT PRIMARY KEY,status TEXT);
          CREATE TABLE agentic_secrets_v2(owner_id TEXT,name TEXT,updated_at TEXT);
          CREATE TABLE chats(session_id TEXT PRIMARY KEY,owner_id TEXT,paper_id TEXT,history TEXT,created_at REAL,updated_at REAL,title TEXT);
        """+SCHEMA)
        db.execute('INSERT INTO papers VALUES(?,?,?)',(config['paperId'],config['ownerId'],str(original)))
        db.execute('INSERT INTO users VALUES(?,?)',(config['ownerId'],'active'))
        db.execute('INSERT INTO agentic_secrets_v2 VALUES(?,?,?)',(config['ownerId'],'translate','fake-revision'))
    store=ProcessingStore(target_db,target_root,config['ownerId'])
    StructuredProfiles(store,StructuredCredentialCipher(b'z'*32)).save('fixture',origin+'/v1',key='separate-target-key')
    assert promote(root,store,config['paperId'])['apply'] is False
    with store.connection() as db:assert db.execute('SELECT count(*) FROM processing_results').fetchone()[0]==0
    original.write_bytes(b'changed-source')
    with pytest.raises(ValueError,match='source_changed'):promote(root,store,config['paperId'],apply=True)
    shutil.copyfile(source,original)
    bad=ProcessingStore(target_db,target_root,str(uuid.uuid4()))
    with pytest.raises(ValueError,match='identity_mismatch'):promote(root,bad,config['paperId'],apply=True)
    report=promote(root,store,config['paperId'],apply=True)
    assert report['apply'] and not report['credentialsCopied'] and not report['oldRowsOverwritten']
    blocks=store.blocks(result['resultId'])
    assert any(b.get('translation',{}).get('content') for b in blocks if b.get('translation'))
    reference=Sources(store,lambda _:original).resolve(result['source']['id'])
    assert reference['paperId']==config['paperId'] and reference['canNavigate']
    with pytest.raises(ValueError,match='already_exists'):promote(root,store,config['paperId'],apply=True)
    assert file_digest(original)==config['sourceSha256']
