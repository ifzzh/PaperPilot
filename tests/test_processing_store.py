import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from ipaper.processing.schema import SCHEMA
from ipaper.processing.store import ProcessingStore
from ipaper.processing.profiles import StructuredCredentialCipher, StructuredProfiles
from ipaper.processing.common import ProcessingError
from ipaper.security.credentials import SettingsCredentialCipher, CredentialDecryptionError

OWNER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def store(tmp_path):
    dbpath = tmp_path / "test.db"
    with sqlite3.connect(dbpath) as db:
        db.executescript("CREATE TABLE papers (id TEXT PRIMARY KEY,owner_id TEXT); CREATE TABLE users(id TEXT PRIMARY KEY,status TEXT);" + SCHEMA)
        db.execute("INSERT INTO users VALUES (?,'active')",(OWNER,))
        db.execute("INSERT INTO papers VALUES ('paper',?)", (OWNER,))
    (tmp_path / "papers").mkdir()
    return ProcessingStore(dbpath, tmp_path / "papers", OWNER)


def result(store, tmp_path):
    import hashlib
    doc = store.register_document("paper", kind="original", sha256="a"*64, size=99, geometry=[{"page": 1}])
    parsed = store.new_result(doc, "structure", {"normalizer": "1"})
    output = tmp_path / str(uuid.uuid4())
    output.mkdir()
    block = {"id": "b1", "order": 0, "text": "original", "textHash": "b"*64, "source": {"page": 1, "precision": "page"}}
    data = (json.dumps(block) + "\n").encode()
    (output / "blocks.jsonl").write_bytes(data)
    store.publish_structure(parsed, output, {"entries": [{"path": "blocks.jsonl", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]})
    return doc, parsed, store.new_result(doc, "structured_translation", {"model": "fake", "revision": "1"}, parse_id=parsed)


def test_history_preserved_on_failure_and_stale_generation(store, tmp_path):
    _, parsed, translated = result(store, tmp_path)
    first, _ = store.begin_translation(translated, "b1")
    assert store.finish_translation(translated, "b1", first, {"text": "原译文"})
    retry, _ = store.begin_translation(translated, "b1")
    assert store.finish_translation(translated, "b1", retry, error="request_unknown")
    assert store.translation(translated, "b1")["content"]["text"] == "原译文"
    old, _ = store.begin_translation(translated, "b1")
    latest, _ = store.begin_translation(translated, "b1")
    assert store.finish_translation(translated, "b1", latest, {"text": "新译文"})
    assert not store.finish_translation(translated, "b1", old, {"text": "晚到响应"})
    assert store.blocks(translated)[0]["translation"]["content"]["text"] == "新译文"
    assert store.blocks(parsed)[0]["text"] == "original"


def test_owner_cannot_read_or_reuse_other_outputs(store, tmp_path):
    doc, parsed, translated = result(store, tmp_path)
    other = ProcessingStore(store.db_path, store.papers_root, OTHER)
    for operation in (lambda: other.document(doc), lambda: other.blocks(parsed), lambda: other.translation(translated, "b1"), lambda: other.new_result(doc,"structure",{})):
        with pytest.raises(ProcessingError, match="not_found"):
            operation()


def test_bad_promotion_has_no_visible_result(store, tmp_path):
    doc = store.register_document("paper", kind="original", sha256="a"*64, size=99, geometry=[{}])
    parsed = store.new_result(doc, "structure", {})
    output = tmp_path / "out"
    output.mkdir()
    (output / "blocks.jsonl").write_text("{}");
    with pytest.raises(ProcessingError, match="hash_mismatch"):
        store.publish_structure(parsed, output, {"entries": [{"path": "blocks.jsonl", "size": 2, "sha256": "a"*64}]})
    assert store.result(parsed)["status"] == "pending"
    assert not store.artifact_directory(parsed).exists()


def test_profile_cipher_is_separate_and_initialization_does_not_overwrite(store):
    key = b"k"*32
    cipher = StructuredCredentialCipher(key)
    profile = StructuredProfiles(store, cipher)
    class Legacy:
        def get(self, name):
            assert name == "translate"
            return "synthetic-test-key"
    settings = {"llmConfigs": {"translate": {"llmModel": "fake", "llmBaseUrl": "https://example.test/v1"}}}
    assert profile.initialize_from_babeldoc(settings, Legacy())
    assert not profile.initialize_from_babeldoc(settings, Legacy())
    assert "key" not in profile.get()
    assert profile.get(secret=True)["key"] == "synthetic-test-key"
    with store.connection() as db:
        envelope = db.execute("SELECT secret_envelope FROM processing_profiles").fetchone()[0]
    with pytest.raises(CredentialDecryptionError):
        cipher.open(OTHER, envelope)
    with pytest.raises(CredentialDecryptionError):
        SettingsCredentialCipher(key).decrypt("translate", envelope, owner_id=OWNER)


def test_consistent_backup_includes_revisions_and_preserves_key(store,tmp_path):
    from ipaper.processing.maintenance import backup
    _, parsed, translated = result(store,tmp_path)
    generation,_=store.begin_translation(translated,'b1')
    store.finish_translation(translated,'b1',generation,{'text':'已保存译文'})
    report=backup(store.db_path,store.papers_root,tmp_path/'backup')
    assert report['immutableFiles']==2
    with sqlite3.connect(tmp_path/'backup/ipaper.db') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM processing_translation_revisions').fetchone()[0]==1
    manifest=json.loads((tmp_path/'backup/manifest.json').read_text())
    assert all((tmp_path/'backup'/item['path']).is_file() for item in manifest['files'])
    assert (tmp_path/'backup/ipaper.db').stat().st_mode & 0o777 == 0o600
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM processing_backup_leases').fetchone()[0]==0


def test_frozen_layout_reference_survives_legacy_alias_registration(store,tmp_path):
    import hashlib
    source=tmp_path/'output.pdf';source.write_bytes(b'%PDF-synthetic-layout')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    doc=store.register_document('paper',kind='babeldoc_mono',sha256=sha,size=source.stat().st_size,geometry=[{}],file_ref='legacy.pdf')
    rid=store.new_result(doc,'babeldoc_mono',{'outputMode':'mono'})
    store.publish_layout(rid,source)
    original_ref=store.document(doc)['file_ref']
    assert '/.artifacts/' in original_ref
    assert store.register_document('paper',kind='babeldoc_mono',sha256=sha,size=source.stat().st_size,geometry=[{}],file_ref='other-legacy.pdf')==doc
    assert store.document(doc)['file_ref']==original_ref
    source.write_bytes(b'%PDF-overwritten-alias')
    assert (store.papers_root/original_ref).read_bytes()==b'%PDF-synthetic-layout'
