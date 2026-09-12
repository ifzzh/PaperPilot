"""Real files/SQLite/configuration; simulated Docker/Registry control boundary."""
import json
import os
import pwd
import sqlite3
from pathlib import Path
import pytest
from scripts import prepare_release_backup as prepare, rollback_release as rollback


def test_release_backup_and_feature_rollback_preserve_current_data(tmp_path,monkeypatch):
    deployment=tmp_path/'deploy';deployment.mkdir()
    papers=tmp_path/'papers';papers.mkdir();(papers/'original.pdf').write_bytes(b'%PDF-own-synthetic')
    database=tmp_path/'ipaper.db'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE papers(id TEXT PRIMARY KEY)');db.execute("INSERT INTO papers VALUES ('existing')")
    (deployment/'.env').write_text('IPAPER_AUTH_MODE=local\n')
    (deployment/'.env').chmod(0o640)
    (deployment/'settings.key').write_bytes(b'synthetic-key-only')
    images={name:f'ifzzh520/{name}:1.1.4@sha256:'+str(i)*64 for i,name in enumerate(rollback.SERVICES,1)}
    config={'services':{name:{'image':image} for name,image in images.items()},
        'volumes':{'document_jobs':{'external':True,'name':'deploy_document_jobs'}},
        'secrets':{'settings_key':{'file':'settings.key'}}}
    (deployment/'compose.yaml').write_text(json.dumps(config))
    regctl=tmp_path/'regctl';regctl.write_text('synthetic-registry-tool')
    destination=tmp_path/'backup';commands=[];running=False
    def execute(args,**kwargs):
        commands.append(args)
        if args[:2]==['docker','inspect']:
            return json.dumps([{'Image':'sha256:container-image','State':{'Running':running,'Health':{'Status':'healthy'}}}])
        if args[:3]==['docker','image','inspect']:return json.dumps([{'Id':'sha256:container-image'}])
        if args[:2]==['docker','compose'] and 'config' in args:return (deployment/'compose.yaml').read_text()
        if args[1:4]==['config','set','--docker-cred']:
            Path(kwargs['env']['REGCTL_CONFIG']).write_text('{"dockerCreds":true}')
        if args[1:3]==['image','digest']:return images['ipaper'].split('@')[1]
        return ''
    monkeypatch.setattr(prepare,'execute',execute)
    monkeypatch.setattr(rollback,'execute',execute)
    args=['prepare','--deployment',str(deployment),'--database',str(database),'--papers',str(papers),
          '--destination',str(destination),'--regctl',str(regctl),'--operator',pwd.getpwuid(os.getuid()).pw_name]
    monkeypatch.setattr('sys.argv',args)
    running=True
    with pytest.raises(AssertionError,match='stop_all_writers'):prepare.main()
    assert not destination.exists()
    running=False;prepare.main()
    assert (destination/'rollback.py').is_file() and (destination/'snapshot/manifest.json').is_file()
    assert (destination/'secrets/settings_key').stat().st_mode&0o777==0o600
    assert (destination/'papers/original.pdf').read_bytes()==b'%PDF-own-synthetic'
    # New writes after backup are kept through an image/configuration rollback.
    with sqlite3.connect(database) as db:db.execute("INSERT INTO papers VALUES ('new-after-backup')")
    original_inode=(deployment/'.env').stat().st_ino
    (deployment/'.env').write_text('IPAPER_CANDIDATE_SETTING=1\n')
    monkeypatch.setattr('sys.argv',['rollback','--backup',str(destination),'--apply'])
    rollback.main()
    assert (deployment/'.env').read_text()=='IPAPER_AUTH_MODE=local\n'
    assert (deployment/'.env').stat().st_ino==original_inode
    assert (deployment/'.env').stat().st_mode&0o777==0o640
    with sqlite3.connect(database) as db:assert db.execute('SELECT count(*) FROM papers').fetchone()[0]==2
    assert any(command[1:3]==['image','copy'] and command[-1]=='docker.io/ifzzh520/ipaper:latest' for command in commands)
    assert not any('down' in c or '-v' in c for c in commands)
