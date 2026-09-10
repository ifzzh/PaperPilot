"""Failures must propagate out of the scanner command substitution."""
import os,shlex,subprocess
from pathlib import Path
import pytest

@pytest.mark.parametrize('failure',['download','checksum'])
def test_scanner_bootstrap_never_extracts_failed_download(tmp_path,failure):
    bindir=tmp_path/'bin';bindir.mkdir()
    for name,body in [('curl','exit '+('18' if failure=='download' else '0')),('sha256sum','exit 1'),('tar','touch "$TOUCHED"; exit 0')]:
        p=bindir/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
    source=Path('scripts/security_scan.sh').read_text()
    function='ensure_trivy() {'+source.split('ensure_trivy() {',1)[1].split('\n}',1)[0]+'\n}'
    shell='set -euo pipefail\ntool_dir='+shlex.quote(str(tmp_path))+'\ntrivy_version=0.74.0\ntrivy_sha256=fake\n'+function+'\nresult=$(ensure_trivy)\nprintf "%s" "$result"\n'
    marker=tmp_path/'extracted'
    result=subprocess.run(['bash','-c',shell],env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH'],'TOUCHED':str(marker)},capture_output=True)
    assert result.returncode!=0
    assert not marker.exists()
    assert not (tmp_path/'trivy-0.74.0').exists()
