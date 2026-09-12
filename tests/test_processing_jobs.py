import json
import pytest
from tests.test_processing_store import store, OWNER, OTHER
from ipaper.processing.common import ProcessingError
from ipaper.processing.jobs import ProcessingJobs
from ipaper.processing.translation import units_for, restore, assemble


def test_duplicate_admission_cancel_and_restart_do_not_resubmit(store):
    jobs = ProcessingJobs(store)
    job, created = jobs.create("paper", "parse_translate", {"source": "a"})
    assert created
    same, created = jobs.create("paper", "parse_translate", {"source": "a"})
    assert not created and same["id"] == job["id"]
    with pytest.raises(ProcessingError, match="user_processing_busy"):
        jobs.create("paper", "parse", {"source": "b"})
    assert jobs.claim(job["id"])
    attempt = jobs.reserve_attempt(job["id"], "cloud_create", "part1")
    jobs.recover()
    assert jobs.get(job["id"])["status"] == "interrupted"
    with pytest.raises(ProcessingError, match="no_resubmit"):
        jobs.resume(job["id"])
    jobs.cancel(job["id"])
    assert jobs.get(job["id"])["status"] == "cancelled"


def test_budget_reserved_before_requests_and_cancel_blocks_next(store):
    jobs = ProcessingJobs(store)
    job, _ = jobs.create("paper", "translate", {}, budget={"requests": 1})
    jobs.claim(job["id"])
    first = jobs.reserve_attempt(job["id"], "model", "1", input_tokens=20, output_tokens=100)
    jobs.finish_attempt(job["id"], first, "unknown")
    with pytest.raises(ProcessingError, match="budget_exceeded"):
        jobs.reserve_attempt(job["id"], "model", "2")
    jobs.cancel(job["id"])
    with pytest.raises(ProcessingError, match="cancelled"):
        jobs.reserve_attempt(job["id"], "model", "3")
    assert json.loads(jobs.get(job["id"])["usage_json"])["requests"] == 1


def test_math_numbers_table_structure_survive_translation():
    block = {"id": "b1", "type": "table", "text": "", "caption": "Accuracy 95.2% ($x+1$)",
             "table": [[{"text": "Value 3", "rowspan": 2, "colspan": 1, "header": True}]]}
    units = units_for(block)
    response = {unit["id"]: restore(unit, unit["text"].replace("Accuracy", "准确率").replace("Value", "数值")) for unit in units}
    translated = assemble(block, units, response)
    assert translated["caption"] == "准确率 95.2% ($x+1$)"
    assert translated["table"][0][0]["rowspan"] == 2
    assert translated["table"][0][0]["text"] == "数值 3"
    with pytest.raises(ProcessingError, match="protected_content_changed"):
        restore(units[0], "伪造内容")


def test_known_cloud_batch_survives_crash_without_recreation(store):
    jobs=ProcessingJobs(store)
    job,_=jobs.create("paper","parse",{})
    jobs.claim(job["id"])
    jobs.reserve_attempt(job["id"],"cloud_create","part-0")
    jobs.checkpoint(job["id"],"cloud_upload",{"parts":{"0":{"batchId":"accepted-batch"}}})
    jobs.recover()
    jobs.resume(job["id"])
    assert jobs.get(job["id"])["status"]=="queued"
    assert json.loads(jobs.get(job["id"])["checkpoint_json"])["parts"]["0"]["batchId"]=="accepted-batch"


def test_cancelled_checkpoint_storage_counts_against_admission(store):
    jobs=ProcessingJobs(store,result_quota=100,owner_quota=150)
    job,_=jobs.create("paper","translate",{"version":1})
    jobs.claim(job["id"])
    scratch=store.artifact_directory(job["id"],create=True)
    (scratch/"cache.json").write_bytes(b"x"*80)
    jobs.finish(job["id"],"failed",error="fake_failure")
    assert jobs.get(job["id"])["reserved_bytes"]==80
    with pytest.raises(ProcessingError,match="owner_quota"):
        jobs.create("paper","translate",{"version":2})
