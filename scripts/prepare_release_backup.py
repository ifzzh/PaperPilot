#!/usr/bin/env python3
"""Capture a stopped iPaper deployment and DB/artifacts for a feature release.

Does not stop/start services itself and never copies a database back over live
user data. The caller first checks idle tasks and gracefully stops all writers.
"""
import argparse
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ipaper.processing.maintenance import backup
from scripts.rollback_release import execute,SERVICES


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda:reader.read(1024**2),b''):value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('deployment','database','papers','destination','regctl'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--operator',default='ifzzh')
    parser.add_argument('--registry-proxy',default='http://127.0.0.1:7890')
    args=parser.parse_args()
    deploy,database,papers,dest,regctl=map(lambda v:Path(v).resolve(),(args.deployment,args.database,args.papers,args.destination,args.regctl))
    assert not dest.exists() and database.is_file() and papers.is_dir()
    states={name:json.loads(execute(['docker','inspect',name]))[0] for name in SERVICES}
    assert all(not s['State']['Running'] for s in states.values()),'stop_all_writers_before_backup'
    env={k:v for k,v in os.environ.items() if not k.startswith(('IPAPER_','PAPERPILOT_'))}
    config=json.loads(execute(['docker','compose','--project-directory',str(deploy),'--env-file',str(deploy/'.env'),'-f',str(deploy/'compose.yaml'),'config','--format','json'],env=env))
    assert config['volumes']['document_jobs'].get('external') and config['volumes']['document_jobs']['name']=='deploy_document_jobs'
    images={name:config['services'][name]['image'] for name in SERVICES}
    assert all('@sha256:' in image for image in images.values()),'baseline_must_pin_digests'
    for name,state in states.items():
        known=json.loads(execute(['docker','image','inspect',images[name]]))[0]['Id']
        assert known==state['Image'],'compose_runtime_image_mismatch'
    operator=pwd.getpwnam(args.operator)
    dest.mkdir(mode=0o700,parents=True)
    try:
        result=backup(database,papers,dest/'snapshot')
        configuration={}
        for name in ('.env','compose.yaml'):
            source=deploy/name;stat=source.stat()
            shutil.copyfile(source,dest/name)
            configuration[name]={'sha256':digest(dest/name),'mode':stat.st_mode&0o777,'uid':stat.st_uid,'gid':stat.st_gid}
        # Full existing paper tree is also retained. It contains original PDFs,
        # legacy aliases and metadata needed alongside the new immutable assets.
        # Symlinks are rejected to avoid following any unrelated host directory.
        for path in papers.rglob('*'):
            assert not path.is_symlink(),'paper_backup_symlink_rejected'
        shutil.copytree(papers,dest/'papers',copy_function=shutil.copy2)
        inventory=[]
        for path in (dest/'papers').rglob('*'):
            if path.is_file():
                relative=path.relative_to(dest/'papers');original=(papers/relative).stat()
                inventory.append({'path':str(relative),'size':path.stat().st_size,'sha256':digest(path),
                                  'uid':original.st_uid,'gid':original.st_gid,'mode':original.st_mode&0o777})
        (dest/'paper-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False))
        secrets=dest/'secrets';secrets.mkdir(mode=0o700)
        secret_files=[]
        for name,item in config.get('secrets',{}).items():
            if 'file' not in item:continue
            source=Path(item['file'])
            if not source.is_absolute():source=deploy/source
            assert source.is_file() and not source.is_symlink(),'secret_file_unavailable'
            target=secrets/name;shutil.copyfile(source,target)
            secret_files.append({'name':name,'sha256':digest(target)})
        shutil.copyfile(regctl,dest/'regctl')
        shutil.copyfile(Path(__file__).with_name('rollback_release.py'),dest/'rollback.py')
        execute([str(regctl),'config','set','--docker-cred'],env={**env,'REGCTL_CONFIG':str(dest/'regctl-config.json')})
        manifest={'kind':'ipaper-feature-release','deployment':str(deploy),'database':str(database),'papers':str(papers),
            'retainCurrentDatabase':True,'images':images,'configuration':configuration,'documentVolume':'deploy_document_jobs',
            'operatorUid':operator.pw_uid,'operatorGid':operator.pw_gid,'operatorHome':operator.pw_dir,
            'registryProxy':args.registry_proxy,'regctlSha256':digest(dest/'regctl'),'secrets':secret_files,
            'paperInventorySha256':digest(dest/'paper-inventory.json'),'snapshot':result}
        (dest/'rollback.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        for path in [dest,*dest.rglob('*')]:
            os.chown(path,operator.pw_uid,operator.pw_gid)
            path.chmod(0o700 if path.is_dir() or path.name=='regctl' else 0o600)
        print(json.dumps({'backupVerified':True,'paperFiles':len(inventory),'immutableFiles':result['immutableFiles'],'destination':str(dest),'secretsPrinted':False}))
    except BaseException:
        marker=dest/'INCOMPLETE';marker.write_text('Release backup incomplete. Do not use for rollback.\n');marker.chmod(0o600)
        raise

if __name__=='__main__':main()
