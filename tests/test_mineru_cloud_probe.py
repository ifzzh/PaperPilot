"""Offline acceptance: fake transport, no credentials or network required."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import Mock
import uuid

import pytest

from scripts.verify_mineru_cloud import AuditFailure, Cloud, Probe, SAMPLE, SAMPLE_SHA
from ipaper.tools.basic_tools.mineru_api_client import finalize_mineru_output
from ipaper.document_worker.safety import DocumentLimitError
from ipaper.security.outbound import OutboundPolicy


class FakeWorker:
    def __init__(self, root, status='completed'):
        self.root, self.status, self.kind = root, status, None
        self.limits = Mock()
    def health(self): return True
    def stage(self, job, kind, source): self.kind = kind
    def create(self, *_): return {}
    def wait(self, *_args, **_kwargs):
        return {'status': 'completed' if self.kind == 'pdf_inspect' else self.status,
                'error': 'archive_type_forbidden' if self.status == 'failed' else None}
    def result_json(self, _): return {'page_count': 2}
    def cleanup(self, _): pass


class FakeCloud:
    def __init__(self, fail=None):
        self.fail = fail; self.creates = 0; self.uploads = 0; self.polls = 0
    def preflight(self): pass
    def create(self, _):
        self.creates += 1
        if self.fail == 'create': raise AuditFailure('cloud_auth_rejected')
        return str(uuid.uuid4()), 'https://allowed.invalid/signed?token=do-not-log'
    def upload(self, *_):
        self.uploads += 1
        if self.fail == 'upload': raise AuditFailure('upload_outcome_uncertain')
    def poll(self, _):
        self.polls += 1
        if self.fail == 'timeout': return {'extract_result': [{'state': 'pending'}]}
        return {'extract_result': [{'state': 'done', 'full_zip_url': 'https://allowed.invalid/result?token=do-not-log'}]}
    def download(self, _url, destination, _maximum):
        if self.fail == 'download': raise AuditFailure('download_rejected_or_interrupted')
        destination.write_bytes(b'opaque ZIP bytes; fake worker never parses this')


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.verify_mineru_cloud.DocumentJobDAO.create', lambda *_: None)
    monkeypatch.setattr('scripts.verify_mineru_cloud.DocumentJobDAO.update', lambda *_, **kw: None)
    clock = [0]
    def sleep(seconds): clock[0] += seconds
    def make(fail=None):
        cloud = FakeCloud(fail)
        probe = Probe(tmp_path, cloud, FakeWorker(tmp_path), clock=lambda: clock[0], sleep=sleep)
        return probe, cloud
    return make


@pytest.mark.parametrize('failure', ['create', 'upload', 'download'])
def test_uncertain_failure_never_creates_second_task(factory, failure, capsys):
    probe, cloud = factory(failure)
    with pytest.raises(AuditFailure): probe.cloud_run()
    again = Probe(probe.root, cloud, probe.worker)
    with pytest.raises(AuditFailure, match='already_attempted'): again.cloud_run()
    assert cloud.creates == 1 and cloud.uploads <= 1
    assert 'do-not-log' not in probe.state_path.read_text() + capsys.readouterr().out
    if failure != 'create':
        cloud.fail = None
        again.cloud_run(resume=True)
        assert cloud.creates == 1 and cloud.uploads == 1


def test_timeout_resume_and_worker_rejection(factory):
    probe, cloud = factory('timeout')
    with pytest.raises(AuditFailure, match='poll_timeout'): probe.cloud_run(max_wait=20)
    assert cloud.polls == 2
    cloud.fail = None
    archive = probe.cloud_run(resume=True)
    assert cloud.creates == 1 and cloud.uploads == 1
    probe.worker.status = 'failed'
    probe.compare_output(archive)
    assert probe.state['cloud'] == 'passed'
    assert probe.state['worker'] == 'blocked' and probe.state['final'] == 'unverified'


def test_preflight_rejection_cannot_spend_quota(factory):
    probe, cloud = factory()
    probe.worker.health = lambda: False
    with pytest.raises(AuditFailure, match='worker_unavailable'): probe.cloud_run()
    assert cloud.creates == 0
    probe.worker.health = lambda: True
    probe.worker.result_json = lambda _: {'page_count': 100}
    with pytest.raises(AuditFailure, match='sample_not_two_pages'): probe.cloud_run()
    assert cloud.creates == 0


def test_empty_transfer_allowlist_rejects_before_creation(factory, monkeypatch):
    probe, _ = factory()
    policy = OutboundPolicy(public_origins=[], private_origins=[], transfer_origins=[])
    probe.cloud = Cloud('synthetic-no-real-key', policy)
    send = Mock(side_effect=AssertionError('no network allowed'))
    monkeypatch.setattr('scripts.verify_mineru_cloud.requests.request', send)
    with pytest.raises(AuditFailure, match='transfer_origins_not_configured'):
        probe.cloud_run()
    assert probe.state['create_attempts'] == 0
    send.assert_not_called()


@pytest.mark.parametrize('status,payload,code', [
    (401, {}, 'cloud_auth_rejected'), (429, {}, 'cloud_rate_or_quota_rejected'),
    (200, b'not JSON', 'cloud_transport_or_json_error'),
    (200, {'code': -1}, 'cloud_business_error'),
])
def test_cloud_response_errors_are_bounded_and_redacted(monkeypatch, status, payload, code):
    response = Mock(status_code=status)
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response.iter_content.return_value = [data]
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    send = Mock(return_value=response)
    monkeypatch.setattr('scripts.verify_mineru_cloud.requests.request', send)
    with pytest.raises(AuditFailure, match=code):
        Cloud('synthetic-no-real-key', Mock()).create('test')
    assert send.call_count == 1
    assert send.call_args.kwargs['allow_redirects'] is False


def test_download_limit_has_no_raw_exception_leak(monkeypatch, tmp_path):
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('scripts.verify_mineru_cloud.guarded_request', lambda *_a, **_kw: response)
    def reject(*_): raise DocumentLimitError('secret-sentinel-should-not-appear')
    monkeypatch.setattr('scripts.verify_mineru_cloud.bounded_copy', reject)
    with pytest.raises(AuditFailure, match='download_rejected_or_interrupted') as error:
        Cloud('synthetic-no-real-key', Mock()).download('https://test.invalid', tmp_path/'result', 1)
    assert 'secret-sentinel' not in str(error.value)


def test_retention_extraction_preserves_existing_behavior(tmp_path):
    (tmp_path/'full.md').write_text('synthetic markdown')
    (tmp_path/'layout.json').write_text('{"bbox": [1,2,3,4]}')
    (tmp_path/'other').mkdir(); (tmp_path/'other'/'data.json').write_text('{}')
    (tmp_path/'images').mkdir(); (tmp_path/'images'/'figure.png').write_bytes(b'synthetic')
    with contextlib.redirect_stdout(io.StringIO()):
        result = finalize_mineru_output('sample.pdf', str(tmp_path))
    assert result == str(tmp_path/'sample.md')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['images', 'sample.md']
    assert (tmp_path/'images'/'figure.png').exists()


def test_missing_markdown_does_not_clean_files(tmp_path):
    (tmp_path/'layout.json').write_text('{}')
    assert finalize_mineru_output('sample.pdf', str(tmp_path)) is None
    assert (tmp_path/'layout.json').exists()


@pytest.mark.parametrize('has_markdown', [True, False])
def test_comparison_uses_validated_output_and_records_retention(factory, tmp_path, has_markdown):
    probe, _ = factory()
    output = tmp_path/'fake-validated-worker'
    output.mkdir()
    (output/'layout.json').write_text('{}')
    if has_markdown:
        (output/'full.md').write_text('synthetic result')
    from scripts.verify_mineru_cloud import fingerprint
    entries = [{'path': p.name, **fingerprint(p)} for p in output.iterdir()]
    probe.worker.verified_manifest = Mock(return_value={'kind':'mineru_zip', 'entries':entries})
    probe.worker.output = lambda _: output
    archive = tmp_path/'opaque.zip'
    archive.write_bytes(b'fake worker owns validation')
    probe.compare_output(archive)
    probe.worker.verified_manifest.assert_called_once()
    assert probe.state['worker'] == 'passed'
    assert probe.state['final'] == ('passed' if has_markdown else 'blocked_missing_markdown')
    retention = json.loads((tmp_path/'retention.json').read_text())
    assert ('layout.json' in retention['removed']) is has_markdown
    assert (tmp_path/'worker-output'/'layout.json').exists()
