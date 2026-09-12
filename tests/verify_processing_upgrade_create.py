"""Manual synthetic upgrade/rollback rehearsal; see delivery operations notes."""
import os,json,hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/tmp/ipaper-120-upgrade-rehearsal')
os.environ['IPAPER_DB_PATH']=str(root/'ipaper.db')
from ipaper.database.db_manager import init_db_schema
from ipaper.database import connection
from ipaper.processing.store import ProcessingStore
from ipaper.processing.profiles import StructuredProfiles,StructuredCredentialCipher
from ipaper.processing.sources import Sources
from ipaper.security.agentic_credentials import AgenticCredentialStore
from ipaper.database.dao.settings_dao import SettingsDAO
from ipaper.security.identity import Identity,run_as_identity
init_db_schema(str(root/'ipaper.db'))
user=json.loads((root/'identity.json').read_text());papers=root/'papers';papers.mkdir(exist_ok=True)
store=ProcessingStore(root/'ipaper.db',papers,user['id'])
profiles=StructuredProfiles(store,StructuredCredentialCipher.from_file(root/'settings.key'))
def migrate():
    profiles.initialize_from_babeldoc(SettingsDAO.get_setting('agentic_settings'),AgenticCredentialStore.from_key_file(root/'settings.key'))
run_as_identity(Identity(user['id'],user['username'],user['role']),migrate)
source=papers/'source.pdf';source.write_bytes(Path('tests/fixtures/workbench/translated.pdf').read_bytes())
doc=store.register_document('upgrade-paper',kind='original',sha256=hashlib.sha256(source.read_bytes()).hexdigest(),size=source.stat().st_size,geometry=[{'page':1},{'page':2}],file_ref='source.pdf')
parsed=store.new_result(doc,'structure',{'normalizer':'synthetic-upgrade'})
output=root/'normalized';output.mkdir()
block={'id':'b1','order':0,'type':'text','text':'Synthetic upgrade content','textHash':'a'*64,'source':{'precision':'page','page':1,'regions':[]}}
body=(json.dumps(block)+'\n').encode();(output/'blocks.jsonl').write_bytes(body)
store.publish_structure(parsed,output,{'entries':[{'path':'blocks.jsonl','size':len(body),'sha256':hashlib.sha256(body).hexdigest()}]})
translated=store.new_result(doc,'structured_translation',{'model':'fixture'},parse_id=parsed)
generation,_=store.begin_translation(translated,'b1');store.finish_translation(translated,'b1',generation,{'text':'合成升级译文'})
sources=Sources(store,lambda _:source)
reference=sources.create_block_selection('upgrade-paper',translated,'b1',start=0,end=9)
sources.save_answer('upgrade-paper','upgrade-chat','New referenced answer',{'S1':reference['id']})
(root/'new-state.json').write_text(json.dumps({'parseId':parsed,'translationId':translated,'sourceId':reference['id'],'revision':store.translation(translated,'b1')['revision']}))
print('new_additive_schema_and_test_artifacts_created')
connection.close_db()
