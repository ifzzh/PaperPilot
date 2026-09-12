#!/usr/bin/env python3
"""Opt-in, one-task MinerU acceptance. Default mode never uses a credential/network.

Live credentials arrive as JSON on stdin from a read-only server-side exporter.
Never run this with the production database, jobs root or Document Worker URL.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from ipaper.document_worker.client import DocumentWorkerClient
from ipaper.document_worker.safety import DocumentLimits, bounded_copy
from ipaper.database import connection
from ipaper.database.db_manager import init_db_schema
from ipaper.database.dao.document_job_dao import DocumentJobDAO
from ipaper.security.identity import Identity, run_as_identity
from ipaper.security.outbound import OutboundPolicy, guarded_request
from ipaper.tools.basic_tools.mineru_api_client import MinerUAPIClient, finalize_mineru_output

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'tests/fixtures/workbench/translated.pdf'
SAMPLE_SHA = '15e992c1f6adb29cc13861018899b85ae5bcb49446eb11effba6d0e3369afc07'


class AuditFailure(RuntimeError):
    """A fixed, credential-free error code."""


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(65536), b''):
            digest.update(chunk)
    return {'size': Path(path).stat().st_size, 'sha256': digest.hexdigest()}


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as out:
        os.chmod(temp, 0o600)
        json.dump(data, out, ensure_ascii=False, indent=2)
        out.write('\n'); out.flush(); os.fsync(out.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class Cloud:
    def __init__(self, token, policy):
        self.client = MinerUAPIClient(token, policy)
        self.policy = policy

    def preflight(self):
        # Configured credentials alone do not enable signed file transfers.
        # Check this before spending the sole batch creation attempt.
        if not self.policy.transfer_origins:
            raise AuditFailure('transfer_origins_not_configured')

    def json_request(self, method, suffix, body=None):
        # Same v4 contract as MinerUAPIClient, with an explicit durable checkpoint
        # between batch creation and upload. Never print response bodies/URLs.
        try:
            with requests.request(method, self.client.base_url + suffix,
                                  headers=self.client.headers, json=body, timeout=(10, 30),
                                  allow_redirects=False, stream=True) as response:
                if response.status_code in (401, 403): raise AuditFailure('cloud_auth_rejected')
                if response.status_code == 429: raise AuditFailure('cloud_rate_or_quota_rejected')
                if response.status_code != 200: raise AuditFailure('cloud_http_error')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 1024 * 1024: raise AuditFailure('cloud_metadata_too_large')
                result = json.loads(data)
                if not isinstance(result, dict) or result.get('code') != 0:
                    raise AuditFailure('cloud_business_error')
                if not isinstance(result.get('data'), dict): raise AuditFailure('cloud_invalid_response')
                return result['data']
        except AuditFailure: raise
        except Exception: raise AuditFailure('cloud_transport_or_json_error') from None

    def create(self, data_id):
        result = self.json_request('POST', '/file-urls/batch', {
            'files': [{'name': SAMPLE.name, 'data_id': data_id}], 'model_version': 'vlm'})
        try:
            batch = str(uuid.UUID(result['batch_id']))
            urls = result['file_urls']
            if len(urls) != 1 or not isinstance(urls[0], str): raise ValueError
            return batch, urls[0]
        except Exception: raise AuditFailure('cloud_invalid_batch_response') from None

    def upload(self, url, sample):
        try:
            with Path(sample).open('rb') as source:
                with guarded_request(self.policy, 'PUT', url, purpose='transfer', data=source,
                                     timeout=(10, 300)) as response:
                    if response.status_code != 200: raise AuditFailure('upload_failed')
        except AuditFailure: raise
        except Exception: raise AuditFailure('upload_outcome_uncertain') from None

    def poll(self, batch):
        return self.json_request('GET', '/extract-results/batch/' + str(uuid.UUID(batch)))

    def download(self, url, destination, maximum):
        try:
            with guarded_request(self.policy, 'GET', url, purpose='transfer', stream=True,
                                 timeout=(10, 300)) as response:
                if response.status_code != 200: raise AuditFailure('download_failed')
                response.raw.decode_content = True
                bounded_copy(response.raw, destination, maximum)
        except AuditFailure: raise
        except Exception: raise AuditFailure('download_rejected_or_interrupted') from None


class Probe:
    def __init__(self, evidence, cloud, worker, *, clock=time.monotonic, sleep=time.sleep):
        self.root = Path(evidence)
        self.cloud, self.worker, self.clock, self.sleep = cloud, worker, clock, sleep
        self.state_path = self.root / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            'run_id': str(uuid.uuid4()), 'sample': fingerprint(SAMPLE),
            'account': 'ifzzh', 'model_version': 'vlm', 'create_attempts': 0,
            'cloud': 'unverified', 'worker': 'unverified', 'final': 'unverified',
        }
        if self.state.get('sample', {}).get('sha256') != SAMPLE_SHA:
            raise AuditFailure('sample_changed')

    def save(self):
        write_json(self.state_path, self.state)

    def preflight(self):
        if fingerprint(SAMPLE)['sha256'] != SAMPLE_SHA: raise AuditFailure('sample_changed')
        if not self.worker.health(): raise AuditFailure('worker_unavailable')
        job = str(uuid.uuid4())
        try:
            with SAMPLE.open('rb') as source: self.worker.stage(job, 'pdf_inspect', source)
            DocumentJobDAO.create(job, 'pdf_inspect')
            self.worker.create(job, 'pdf_inspect')
            state = self.worker.wait(job, timeout=90)
            DocumentJobDAO.update(job, state['status'])
            if state['status'] != 'completed': raise AuditFailure('sample_inspection_failed')
            result = self.worker.result_json(job)
            if result.get('page_count') != 2: raise AuditFailure('sample_not_two_pages')
            self.state['sample_pages'] = 2
            self.state['preflight'] = 'passed'; self.save()
        finally:
            self.worker.cleanup(job)

    def cloud_run(self, *, resume=False, max_wait=1800):
        if max_wait <= 0 or max_wait > 1800: raise AuditFailure('invalid_wait_limit')
        self.preflight()
        if resume:
            if not self.state.get('batch_id'): raise AuditFailure('no_batch_do_not_resubmit')
        else:
            if self.state.get('create_attempts'): raise AuditFailure('already_attempted_use_resume')
            self.cloud.preflight()
            self.state.update(create_attempts=1, cloud='creation_attempted')
            self.save()  # Commit intent before any external side effect.
            batch, upload_url = self.cloud.create(self.state['run_id'])
            self.state.update(batch_id=batch, cloud='upload_attempted'); self.save()
            self.cloud.upload(upload_url, SAMPLE)
            del upload_url
            self.state['cloud'] = 'uploaded'; self.save()
        deadline = self.clock() + max_wait
        while self.clock() < deadline:
            result = self.cloud.poll(self.state['batch_id'])
            rows = result.get('extract_result', [])
            if not isinstance(rows, list) or len(rows) > 1: raise AuditFailure('unexpected_result_count')
            if rows:
                row = rows[0]
                if not isinstance(row, dict): raise AuditFailure('invalid_result')
                if row.get('state') == 'failed': raise AuditFailure('cloud_parse_failed')
                if row.get('state') == 'done':
                    url = row.get('full_zip_url')
                    if not isinstance(url, str): raise AuditFailure('missing_result_url')
                    self.state['cloud'] = 'passed'; self.save()
                    target = self.root / 'cloud-result.zip'
                    self.cloud.download(url, target, DocumentLimits().max_archive_bytes)
                    os.chmod(target, 0o600)
                    self.state['archive'] = fingerprint(target); self.save()
                    return target
            self.sleep(min(10, max(0, deadline - self.clock())))
        raise AuditFailure('poll_timeout_remote_state_unknown')

    def compare_output(self, archive):
        job = str(uuid.uuid4())
        self.state['worker_job_id'] = job; self.save()
        # Keep the failed staging input for Worker-only directory diagnosis.
        with Path(archive).open('rb') as source: self.worker.stage(job, 'mineru_zip', source)
        DocumentJobDAO.create(job, 'mineru_zip')
        self.worker.create(job, 'mineru_zip')
        state = self.worker.wait(job, timeout=300)
        DocumentJobDAO.update(job, state['status'], error=state.get('error'))
        if state['status'] != 'completed':
            self.state['worker'] = 'blocked'
            # Existing Worker emits a stable reason, not arbitrary PDF/ZIP text.
            self.state['worker_error'] = state.get('error')
            self.save(); return
        manifest = self.worker.verified_manifest(job, 'mineru_zip')
        output = self.worker.output(job)
        validated = self.root / 'worker-output'
        if validated.exists(): raise AuditFailure('comparison_already_exists')
        validated.mkdir(mode=0o700)
        for entry in manifest['entries']:
            target = validated.joinpath(*Path(entry['path']).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with (output / entry['path']).open('rb') as source:
                bounded_copy(source, target, int(entry['size']))
        write_json(self.root / 'worker-manifest.json', manifest)
        self.state['worker'] = 'passed'; self.save()
        final = self.root / 'final-output'
        shutil.copytree(validated, final)
        with contextlib.redirect_stdout(io.StringIO()):
            markdown = finalize_mineru_output(str(SAMPLE), str(final))
        before = {p.relative_to(validated).as_posix(): fingerprint(p) for p in validated.rglob('*') if p.is_file()}
        after = {p.relative_to(final).as_posix(): fingerprint(p) for p in final.rglob('*') if p.is_file()}
        write_json(self.root / 'retention.json', {'before': before, 'after': after,
            'removed': sorted(before.keys() - after.keys()), 'markdown': Path(markdown).name if markdown else None})
        self.state['final'] = 'passed' if markdown else 'blocked_missing_markdown'; self.save()
        self.worker.cleanup(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--resume', action='store_true', help='query recorded batch; never create/upload')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--worker-url')
    parser.add_argument('--jobs-root')
    parser.add_argument('--worker-token-file')
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({'mode': 'offline', 'sample': fingerprint(SAMPLE),
                          'matches_expected': fingerprint(SAMPLE)['sha256'] == SAMPLE_SHA,
                          'cloud_submissions': 0, 'tests': 'pytest tests/test_mineru_cloud_probe.py'}))
        return
    if not all([args.evidence, args.worker_url, args.jobs_root, args.worker_token_file]):
        parser.error('live mode requires an isolated evidence directory and Worker configuration')
    os.umask(0o077)
    args.evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.evidence.is_symlink(): raise SystemExit('unsafe_evidence_directory')
    lock = (args.evidence / '.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    probe = None
    try:
        config = json.loads(sys.stdin.buffer.read(65537))
        if not config.get('token') or config.get('account') != 'ifzzh': raise AuditFailure('credential_input_invalid')
        policy = OutboundPolicy(public_origins=[], private_origins=[],
            transfer_origins=config.get('transfer_origins', []),
            proxy_fake_ip_networks=config.get('proxy_fake_ip_networks', []))
        cloud = Cloud(config.pop('token'), policy)
        worker = DocumentWorkerClient(base_url=args.worker_url, jobs_root=args.jobs_root,
                                      token_file=args.worker_token_file)
        connection.DB_PATH = str(args.evidence / 'probe.db')
        init_db_schema(connection.DB_PATH)
        probe = Probe(args.evidence, cloud, worker)
        def execute():
            archive = probe.cloud_run(resume=args.resume)
            probe.compare_output(archive)
        run_as_identity(Identity('00000000-0000-4000-8000-000000000004', 'mineru-probe', 'admin'), execute)
        print(json.dumps({'cloud': probe.state['cloud'], 'worker': probe.state['worker'],
                          'final': probe.state['final'], 'create_attempts': probe.state['create_attempts']}))
    except Exception as error:
        code = str(error) if isinstance(error, AuditFailure) else 'probe_failed'
        if probe:
            probe.state['error'] = code; probe.save()
        print(json.dumps({'error': code}))
        raise SystemExit(1)
    finally:
        connection.close_db()
        lock.close()


if __name__ == '__main__':
    main()
