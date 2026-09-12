"""Real split/normalizer/persistence with fake cloud and model (zero paid calls)."""
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from tests.test_processing_store import store
from tests.test_structured_document import pdf, archive
from ipaper.document_worker.runner import run
from ipaper.document_worker.client import DocumentWorkerClient
from ipaper.processing.pipeline import ProcessingPipeline
from ipaper.processing.profiles import StructuredCredentialCipher, StructuredProfiles
from ipaper.processing.translation import restore


class LocalDocument(DocumentWorkerClient):
    def health(self):
        return True
    def create(self, job_id, kind):
        run(self.job_directory(job_id), kind)
    def wait(self, job_id, **kwargs):
        return {"status": "completed"}
    def cancel(self, job_id):
        return {}


class FakeCredentials:
    def configured(self, name):
        return True
    def get(self, name):
        return "test-only-synthetic-key"


class FakeCloud:
    creates = 0
    def __init__(self, *_):
        pass
    def submit(self, path, unit, jobs, job_id, save_batch):
        FakeCloud.creates += 1
        save_batch("test-batch")
        return "test-batch"
    def wait_download(self, batch, destination, *_):
        archive(destination)


class FakeModel:
    calls = 0
    def __init__(self, *_):
        pass
    def translate(self, units, language, *_):
        FakeModel.calls += 1
        return {unit["id"]: restore(unit, unit["text"].replace("Source page", "原始页")) for unit in units}


@pytest.fixture
def pipeline(store, tmp_path):
    source = store.papers_root / ".users" / store.owner / "source.pdf"
    source.parent.mkdir(parents=True)
    pdf(source)
    with store.connection(write=True) as db:
        db.execute("ALTER TABLE papers ADD COLUMN file_path TEXT")
        db.execute("UPDATE papers SET file_path=?", (str(source),))
        db.execute("CREATE TABLE user_settings_v2(owner_id TEXT,key TEXT,value TEXT)")
        db.execute("INSERT INTO user_settings_v2 VALUES (?, 'agentic_settings', ?)", (store.owner, json.dumps({"mineruUseApi": True})))
    staging = tmp_path / "staging"
    staging.mkdir()
    profiles = StructuredProfiles(store, StructuredCredentialCipher(b"x"*32))
    profiles.save("test-model", "https://example.test/v1", key="test-only")
    pipeline = ProcessingPipeline(store, profiles, FakeCredentials(), None,
          document_client=LocalDocument(jobs_root=staging), cloud_factory=FakeCloud, model_factory=FakeModel)
    FakeCloud.creates = FakeModel.calls = 0
    return pipeline


def test_real_pipeline_three_contents_and_duplicate_does_not_call(pipeline, store):
    source = pipeline.paper_file("paper")
    preview = pipeline.preflight("paper")
    assert preview["pageCount"] == 2
    assert preview["partCount"] == 1
    assert pipeline.preflight("paper")["preflightId"] == preview["preflightId"]
    data = {"preflightId": preview["preflightId"], "kind": "parse_translate"}
    job, created = pipeline.create("paper", data)
    pipeline.run(job["id"])
    outcome = pipeline.jobs.get(job["id"])
    assert outcome["status"] == "completed", outcome["error"]
    assert FakeCloud.creates == 1
    assert FakeModel.calls == 2
    blocks = store.blocks(outcome["result_id"])
    assert blocks[0]["translation"]["content"]["text"] == "原始页 1"
    assert blocks[0]["source"]["precision"] == "region"
    assert blocks[1]["source"]["precision"] == "page"
    assert source.exists()
    again, created = pipeline.create("paper", data)
    assert not created and again["id"] == job["id"]
    pipeline.run(again["id"])
    assert FakeCloud.creates == 1 and FakeModel.calls == 2


def test_partial_unit_checkpoints_reduce_resume_budget(pipeline, store, monkeypatch):
    from ipaper.processing.common import ProcessingError
    from ipaper.processing.translation import request_payload
    preview = pipeline.preflight("paper")
    job, _ = pipeline.create("paper", {"preflightId": preview["preflightId"], "kind": "parse_translate", "budget":{"requests":2}})
    class CountedModel(FakeModel):
        def translate(self, units, language, jobs, job_id):
            _, inputs, outputs = request_payload(units, language)
            attempt = jobs.reserve_attempt(job_id,"model",units[0]["id"],input_tokens=inputs,output_tokens=outputs)
            answer = super().translate(units,language,jobs,job_id)
            jobs.finish_attempt(job_id,attempt,"completed")
            return answer
    pipeline.model_factory = CountedModel
    original_finish = store.finish_translation
    failed = False
    def interrupt_publish(*args, **kwargs):
        nonlocal failed
        if not kwargs.get("error") and not failed:
            failed=True
            raise ProcessingError("model_result_unknown")
        return original_finish(*args,**kwargs)
    monkeypatch.setattr(store,"finish_translation",interrupt_publish)
    pipeline.run(job["id"])
    assert pipeline.jobs.get(job["id"])["status"]=="interrupted"
    assert FakeModel.calls==1
    pipeline.jobs.resume(job["id"])
    pipeline.run(job["id"])
    outcome=pipeline.jobs.get(job["id"])
    assert outcome["status"]=="completed", outcome["error"]
    assert FakeModel.calls==2  # saved first block was published without resending
    assert json.loads(outcome["usage_json"])["requests"]==2


def test_source_replacement_and_preflight_concurrency_do_not_submit(pipeline, monkeypatch):
    from ipaper.processing.common import ProcessingError
    from ipaper.processing.pipeline import _PREFLIGHT_LOCK, _PREFLIGHT_OWNERS
    with _PREFLIGHT_LOCK:
        _PREFLIGHT_OWNERS.add(pipeline.store.owner)
    try:
        with pytest.raises(ProcessingError,match="preflight_busy"):
            pipeline.preflight("paper")
    finally:
        with _PREFLIGHT_LOCK:
            _PREFLIGHT_OWNERS.discard(pipeline.store.owner)
    preview=pipeline.preflight("paper")
    job,_=pipeline.create("paper",{"preflightId":preview["preflightId"]})
    pipeline.paper_file("paper").write_bytes(b"replaced")
    pipeline.run(job["id"])
    assert pipeline.jobs.get(job["id"])["error"]=="source_changed"
    assert FakeCloud.creates==FakeModel.calls==0


def test_201_page_merge_keeps_original_page_order(pipeline):
    import fitz
    import zipfile
    source=pipeline.paper_file("paper")
    source.unlink();pdf(source,201)
    class SegmentedCloud:
        parts={}
        def __init__(self,*_): pass
        def submit(self,path,unit,jobs,job_id,save_batch):
            with fitz.open(path) as document:
                self.parts[unit]=[(p.rect.width,p.rect.height,p.get_text()) for p in document]
            save_batch(unit)
        def wait_download(self,batch,destination,*_):
            pages=self.parts[batch]
            items=[{"type":"text","text":text,"page_idx":i,"bbox":[100,80,400,110]} for i,(w,h,text) in enumerate(pages)]
            layout=[{"page_idx":i,"page_size":[w,h]} for i,(w,h,text) in enumerate(pages)]
            with zipfile.ZipFile(destination,"w") as out:
                out.writestr("x_content_list.json",json.dumps(items))
                out.writestr("layout.json",json.dumps({"_version_name":"3.4.4","_backend":"hybrid","pdf_info":layout}))
                out.writestr("full.md","Own 201-page synthetic content")
    pipeline.cloud_factory=SegmentedCloud
    preview=pipeline.preflight("paper")
    assert preview["partCount"]==2
    job,_=pipeline.create("paper",{"preflightId":preview["preflightId"],"kind":"parse"})
    pipeline.run(job["id"])
    final=pipeline.jobs.get(job["id"])
    assert final["status"]=="completed",final["error"]
    boundary=pipeline.store.blocks(final["result_id"],after=198,limit=10)
    assert [b["source"]["page"] for b in boundary]==[200,201]
    assert [b["text"].strip() for b in boundary]==["Source page 200","Source page 201"]
    assert len({b["id"] for b in boundary})==2
