"""Synthetic-only adapters for browser acceptance. Never imported by runtime."""
import json
import uuid
import zipfile
from pathlib import Path

from tests.test_processing_pipeline import LocalDocument
from ipaper.processing.pipeline import ProcessingPipeline
from ipaper.processing.profiles import StructuredProfiles
from ipaper.processing.store import ProcessingStore
from ipaper.security.identity import Identity, run_as_identity
from ipaper.database.dao.settings_dao import SettingsDAO


class SyntheticCloud:
    submitted = {}
    def __init__(self, *_):
        pass
    def submit(self, path, unit, jobs, job_id, save_batch):
        import fitz
        with fitz.open(path) as pdf:
            pages = [(page.rect.width, page.rect.height, page.get_text()) for page in pdf]
        batch = str(uuid.uuid4())
        self.submitted[batch] = pages
        save_batch(batch)
        return batch
    def wait_download(self, batch, destination, jobs, job_id):
        content, layout = [], []
        for index, (width, height, text) in enumerate(self.submitted[batch]):
            layout.append({"page_idx": index, "page_size": [width,height]})
            content.append({"type":"text","text":text.strip().splitlines()[0],"text_level":1 if index==0 else 0,
                "page_idx":index,"bbox":[75,65,900,145]})
            content.extend([
                {"type":"text","text":"This synthetic paragraph explains the controlled experiment. Accuracy is 95.2% and the sample contains $n=12$ observations.","page_idx":index,"bbox":[75,185,900,310]},
                {"type":"equation","text":"$$E = mc^2$$","page_idx":index,"bbox":[100,360,700,430]},
                {"type":"table","table_body":"<table><tr><th>Method</th><th>Score</th></tr><tr><td>Baseline</td><td>90</td></tr><tr><td>Ours</td><td>95.2</td></tr></table>","table_caption":["Synthetic results, not a production paper."],"page_idx":index,"bbox":[75,520,900,700]},
            ])
        with zipfile.ZipFile(destination,"w") as archive:
            archive.writestr("synthetic_content_list.json",json.dumps(content))
            archive.writestr("layout.json",json.dumps({"_version_name":"3.4.4","_backend":"hybrid","pdf_info":layout}))
            archive.writestr("full.md","# Synthetic structured paper\nOwn generated content for offline acceptance.")


def install(application, directory, users, origin, patch):
    service = application.extensions["processing"]
    root=Path(directory)
    staging=root/'structured-document-jobs';staging.mkdir()
    original_pipeline=service.pipeline
    def pipeline(owner=None):
        current=original_pipeline(owner)
        return ProcessingPipeline(current.store,current.profiles,current.credentials,current.policy,
                 document_client=LocalDocument(jobs_root=staging),cloud_factory=SyntheticCloud)
    service.pipeline=pipeline
    for user in users:
        def seed():
            current=service.pipeline(user['id'])
            settings=current.settings()
            settings['mineruUseApi']=True
            SettingsDAO.save_setting('agentic_settings',settings)
            service.credentials.set('mineru','synthetic-cloud-only')
            current.profiles.save('fixture',origin+'/v1',key='synthetic-model-only')
        run_as_identity(Identity(user['id'],user['username'],user['role']),seed)
    service.start()
