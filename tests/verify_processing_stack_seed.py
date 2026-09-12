"""Manual isolated candidate-image fixture. Requires /acceptance/ISOLATED marker."""
import json
import sys
sys.path.insert(0,"/app")
import shutil
from pathlib import Path
from ipaper.database.connection import DB_PATH
from ipaper.database.db_manager import init_db_schema
from ipaper.local_auth import LocalAuthService
from ipaper.database.dao.paper_dao import PaperDAO
from ipaper.database.dao.settings_dao import SettingsDAO
from ipaper.security.credentials import generate_settings_key
from ipaper.security.identity import Identity, run_as_identity
from ipaper.security.paths import paper_path, paper_asset_paths

root=Path('/acceptance')
assert (root/'ISOLATED').is_file() and DB_PATH=='/app/db/ipaper.db'
assert not Path(DB_PATH).exists(), 'seed_requires_empty_isolated_database'
init_db_schema(DB_PATH)
user=LocalAuthService().create_bootstrap_admin('stack_reader','isolated-stack-password')
from ipaper.database import connection
connection.get_db().execute('UPDATE users SET must_change_password=0');connection.get_db().commit()
generate_settings_key(root/'settings.key')

def seed():
    for pid,title,filename,translated in [('stack-synthetic','自制结构验收论文','synthetic.pdf',None),
        ('stack-autosci','AutoSci: A Memory-Centric Agentic System for the Full Scientific Research Lifecycle','autosci.pdf','autosci-dual.pdf')]:
        original=Path('/fixtures')/filename
        if not original.exists(): continue
        target=paper_path('/data/papers','root',pid+'.pdf',create_parent=True)
        shutil.copyfile(original,target)
        if translated:
            shutil.copyfile(Path('/fixtures')/translated,paper_asset_paths('/data/papers',target).chinese_dual)
        PaperDAO.save_paper({'id':pid,'title':title,'authors':'Isolated acceptance','file_path':str(target),
                            'filename':target.name,'has_chinese_version':bool(translated),'translated':bool(translated)})
    SettingsDAO.save_setting('agentic_settings',{})
run_as_identity(Identity(user['id'],user['username'],user['role']),seed)
(root/'identity.json').write_text(json.dumps({k:user[k] for k in ('id','username','role')}))
print(json.dumps({'isolatedSeed':True,'papers':2,'productionDatabaseCopied':False}))
