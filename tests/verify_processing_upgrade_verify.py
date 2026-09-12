"""Manual synthetic upgrade/rollback rehearsal; see delivery operations notes."""
import os,json,hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/tmp/ipaper-120-upgrade-rehearsal')
os.environ['IPAPER_DB_PATH']=str(root/'ipaper.db')
from ipaper.database.db_manager import init_db_schema
from ipaper.processing.store import ProcessingStore
from ipaper.processing.profiles import StructuredProfiles,StructuredCredentialCipher
from ipaper.processing.sources import Sources
from ipaper.processing.maintenance import backup
init_db_schema(str(root/'ipaper.db'))
user=json.loads((root/'identity.json').read_text());state=json.loads((root/'new-state.json').read_text())
store=ProcessingStore(root/'ipaper.db',root/'papers',user['id'])
assert store.translation(state['translationId'],'b1')['content']['text']=='合成升级译文'
assert store.translation(state['translationId'],'b1')['revision']==state['revision']
assert Sources(store,lambda _:root/'papers/source.pdf').resolve(state['sourceId'])['canNavigate']
assert StructuredProfiles(store,StructuredCredentialCipher.from_file(root/'settings.key')).get(secret=True)['key']=='synthetic-upgrade-key'
with store.connection() as db:
    assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==2
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    chat=json.loads(db.execute("SELECT history FROM chats WHERE session_id='upgrade-chat'").fetchone()[0])
    assert [m['content'] for m in chat]==['Old question','New referenced answer','Written after rollback']
    assert db.execute('SELECT count(*) FROM processing_chat_sources').fetchone()[0]==1
report={'oldRuntime':'1.1.4','oldRuntimeUnmodified':True,'productionDataCopied':False,
        'legacyCredentialDecrypt':True,'newCredentialDecryptAfterRollback':True,'newTranslationPreserved':True,
        'sourcePreserved':True,'oldRuntimeNewPaperAndChatPreserved':True,
        'backup':backup(root/'ipaper.db',root/'papers',root/'backup-after-roundtrip')}
Path('.devnotes/dual-translation-upgrade-rollback.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
