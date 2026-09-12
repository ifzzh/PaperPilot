"""Run inside an unmodified 1.1.4 image on a synthetic upgrade database."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,'/app')
root=Path('/work/acceptance')
os.umask(0o007)
os.environ['IPAPER_DB_PATH']=str(root/'ipaper.db')
from ipaper.database.db_manager import init_db_schema
from ipaper.local_auth import LocalAuthService
from ipaper.database.dao.paper_dao import PaperDAO
from ipaper.database.dao.chat_dao import ChatDAO
from ipaper.database.dao.settings_dao import SettingsDAO
from ipaper.security.credentials import generate_settings_key
from ipaper.security.agentic_credentials import AgenticCredentialStore
from ipaper.security.identity import Identity,run_as_identity
init_db_schema(str(root/'ipaper.db'))
if sys.argv[1]=='init':
    auth=LocalAuthService()
    user=auth.create_bootstrap_admin('upgrade_reader','isolated-upgrade-password')
    (root/'identity.json').write_text(json.dumps({k:user[k] for k in ('id','username','role')}))
    generate_settings_key(root/'settings.key')
else:
    user=json.loads((root/'identity.json').read_text())
credentials=AgenticCredentialStore.from_key_file(str(root/'settings.key'))
def phase():
    if sys.argv[1]=='init':
        SettingsDAO.save_setting('agentic_settings',{'llmConfigs':{'translate':{'llmModel':'fixture','llmBaseUrl':'https://example.test/v1'}}})
        credentials.set('translate','synthetic-upgrade-key')
        PaperDAO.save_paper({'id':'upgrade-paper','title':'Synthetic before upgrade','file_path':'/work/acceptance/papers/source.pdf'})
        ChatDAO.save_chat('upgrade-chat',{'paper_id':'upgrade-paper','history':[{'role':'user','content':'Old question','timestamp':1.0}],'title':'Old chat','created_at':1,'updated_at':1})
    else:
        credentials.validate_all()
        assert credentials.get('translate')=='synthetic-upgrade-key'
        PaperDAO.save_paper({'id':'rollback-added','title':'Created by unchanged 1.1.4 after rollback'})
        chat=ChatDAO.get_chat('upgrade-chat')
        assert any(m['content']=='New referenced answer' for m in chat['history'])
        chat['history'].append({'role':'user','content':'Written after rollback','timestamp':3.0})
        ChatDAO.save_chat('upgrade-chat',chat)
run_as_identity(Identity(user['id'],user['username'],user['role']),phase)
print(json.dumps({'oldRuntimePhase':sys.argv[1],'passed':True}))
