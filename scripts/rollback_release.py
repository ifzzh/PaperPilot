#!/usr/bin/env python3
"""Restore a captured digest/config baseline, retaining the CURRENT database/assets.

Dry-run unless --apply is supplied. This is not the historical brand/path rollback.
Run as an operator able to manage Docker and the saved configuration permissions.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SERVICES=('ipaper','ipaper-translation-worker','ipaper-document-worker')

def execute(args,**kwargs):
    result=subprocess.run(args,capture_output=True,text=True,**kwargs)
    if result.returncode:
        raise RuntimeError('operator_command_failed:'+args[0])
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();root=Path(args.backup).resolve()
    assert not (root/'INCOMPLETE').exists(),'incomplete_backup'
    manifest=json.loads((root/'rollback.json').read_text())
    assert manifest['kind']=='ipaper-feature-release' and manifest['retainCurrentDatabase'] is True
    deploy=Path(manifest['deployment'])
    for name,info in manifest['configuration'].items():
        assert name in ('.env','compose.yaml') and sha(root/name)==info['sha256']
    for service in SERVICES:
        image=manifest['images'][service]
        assert '@sha256:' in image and image.split('@')[0].split(':')[0] in (
            'ifzzh520/ipaper','ifzzh520/ipaper-translation-worker','ifzzh520/ipaper-document-worker')
    # Refuse unsafe manifests even in dry-run. Never infer new paths or volumes.
    assert manifest['documentVolume']=='deploy_document_jobs'
    if not args.apply:
        print(json.dumps({'dryRun':True,'restoreImages':manifest['images'],'retainCurrentDatabase':True,'retainArtifacts':True}))
        return
    env={k:v for k,v in os.environ.items() if not k.startswith(('IPAPER_','PAPERPILOT_'))}
    compose=['docker','compose','--project-directory',str(deploy),'--env-file',str(deploy/'.env'),'-f',str(deploy/'compose.yaml')]
    for image in manifest['images'].values():
        execute(['docker','image','inspect',image])  # old images must be ready first
    execute(compose+['stop',*SERVICES],env=env)
    for service in SERVICES:
        state=json.loads(execute(['docker','inspect',service]))[0]
        assert not state['State']['Running'],'old_writer_still_running'
    for name,info in manifest['configuration'].items():
        target=deploy/name
        assert target.is_file() and not target.is_symlink()
        # Keep the target inode/ownership/mode used by the runtime mount.
        with (root/name).open('rb') as source,target.open('wb') as writer:
            shutil.copyfileobj(source,writer);writer.flush();os.fsync(writer.fileno())
        os.chmod(target,info['mode']);os.chown(target,info['uid'],info['gid'])
    config=json.loads(execute(compose+['config','--format','json'],env=env))
    assert config['volumes']['document_jobs'].get('external') is True
    assert config['volumes']['document_jobs']['name']==manifest['documentVolume']
    for service in SERVICES: assert config['services'][service]['image']==manifest['images'][service]
    execute(compose+['up','-d','--pull','never',*SERVICES],env=env)
    for _ in range(60):
        states=[json.loads(execute(['docker','inspect',name]))[0]['State'] for name in SERVICES]
        if all(s.get('Health',{}).get('Status')=='healthy' for s in states): break
        time.sleep(2)
    else: raise RuntimeError('rollback_health_failed')
    execute(['docker','exec','ipaper','python','-c',
             "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7191/readyz',timeout=15).read()"])
    # Use the maintenance account's existing Docker credential helper. No token
    # is copied into the bundle, command line, environment or this script.
    registry=root/'regctl'
    assert sha(registry)==manifest['regctlSha256']
    def identity():
        os.setgroups([manifest['operatorGid']]);os.setgid(manifest['operatorGid']);os.setuid(manifest['operatorUid'])
    options={'preexec_fn':identity} if os.geteuid()==0 else {}
    registry_env={**env,'HOME':manifest['operatorHome'],'REGCTL_CONFIG':str(root/'regctl-config.json')}
    if manifest.get('registryProxy'):
        registry_env.update(HTTP_PROXY=manifest['registryProxy'],HTTPS_PROXY=manifest['registryProxy'])
    stable=manifest['images']['ipaper'].split('@')[1]
    execute([str(registry),'image','copy','docker.io/ifzzh520/ipaper@'+stable,'docker.io/ifzzh520/ipaper:latest'],env=registry_env,**options)
    assert execute([str(registry),'image','digest','docker.io/ifzzh520/ipaper:latest'],env=registry_env,**options).strip()==stable
    print(json.dumps({'rollback':True,'currentDatabaseRetained':True,'artifactsRetained':True,'healthy':True,'webLatest':stable}))

if __name__=='__main__':main()
