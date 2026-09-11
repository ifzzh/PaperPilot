"""Full Flask route graph with temporary synthetic data; never production state.

Run as a separate process: the application factory is process-local. The only
model origin is the existing loopback fake; no real credentials are loaded.
"""
import signal
import os
import tempfile
import json
import shutil
from pathlib import Path

from pytest import MonkeyPatch
from werkzeug.serving import make_server

from tests.workbench_support import make_workbench_fixture
from tests.workbench_reader_support import fake_openai, install_reader_fixture
from tests.test_document_upload_flow import ImmediateDocumentClient
from paperpilot.document_worker.safety import DocumentLimits
from paperpilot.routes.basic_routes import upload_from_pdf_route
from paperpilot.routes.basic_routes import daily_arxiv_route
from paperpilot.database.dao.paper_dao import PaperDAO
from paperpilot.database.dao.daily_arxiv_dao import DailyArxivDAO
from paperpilot.security.identity import Identity, set_background_identity
from paperpilot.database import connection
import app as app_module


if __name__ == "__main__":
    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with tempfile.TemporaryDirectory(prefix="paperpilot-unified-") as directory, MonkeyPatch.context() as patch, fake_openai() as origin:
        fixture, first, second = make_workbench_fixture(directory, patch, count=1000)
        with fixture.app_context():
            _, invite = app_module.AUTH_SERVICE.create_invite(first["id"])
            third = app_module.AUTH_SERVICE.register("reader_pdf", "workbench-test-pass", invite)
            _, invite = app_module.AUTH_SERVICE.create_invite(first['id'])
            app_module.AUTH_SERVICE.register('empty_reader','workbench-test-pass',invite)
            _, invite = app_module.AUTH_SERVICE.create_invite(first['id'])
            reviewer=app_module.AUTH_SERVICE.register('review_admin','workbench-test-pass',invite)
            app_module.AUTH_SERVICE.update_user(first['id'], reviewer['id'], role='admin')
        application = app_module.app
        application.config.update(TESTING=True, PAPERPILOT_START_BACKGROUND_TASKS=False)
        patch.setattr(app_module, "DB_PATH", connection.DB_PATH)
        set_background_identity(Identity(first["id"], first["username"], first["role"]))
        install_reader_fixture(application, directory, (first, second, third), patch, origin, register_routes=False)
        app_module.init_app(directory + "/papers")
        app_module.init_categories()
        # Browser flow validates Flask upload/promotion against a deterministic
        # worker double. Real worker isolation is covered by its separate suite.
        upload_client=ImmediateDocumentClient(directory+'/upload-jobs')
        upload_client.limits=DocumentLimits(max_pdf_bytes=16*1024*1024)
        if os.getenv('PAPERPILOT_BROWSER_REAL_WORKER') == '1':
            from urllib.parse import urlsplit
            import ipaddress
            worker_url=urlsplit(os.environ['PAPERPILOT_DOCUMENT_WORKER_URL'])
            assert worker_url.scheme=='http' and worker_url.port==7193 and ipaddress.ip_address(worker_url.hostname).is_private
            assert os.environ['PAPERPILOT_DOCUMENT_JOBS_ROOT'].startswith('/tmp/paperpilot-unified-document-')
        else:
            register_upload=app_module.register_upload_from_pdf_routes
            patch.setattr(app_module,'register_upload_from_pdf_routes',lambda *args,**kwargs:register_upload(*args,**{**kwargs,'document_client':upload_client}))
        patch.setattr(daily_arxiv_route,'paper_store',app_module.paper_store)
        def no_external_metadata(*_args,**_kwargs):
            raise app_module.QueueFull('synthetic fixture disables outbound metadata')
        patch.setattr(app_module._daily_aux_executor,'submit',no_external_metadata)
        app_module.register_routes()
        from paperpilot.routes.basic_routes import import_route
        import_route.import_tasks['synthetic-import-completed']={'owner_id':third['id'],'status':'completed','progress':100,'current':3,'total':3,'success_count':3,'message':'合成导入完成'}
        with application.app_context():
            settings_path=Path(app_module.DAILY_ARXIV_SETTINGS_FILE)
            settings=json.loads(settings_path.read_text())
            settings.update(enabled=True,keywordList=[],topicFilteringEnabled=False,categories=['cs.AI'])
            settings_path.write_text(json.dumps(settings))
            daily_root=Path(app_module.TEMP_PAPERS_DIR)/'2026-09-10'/'cs.AI'
            daily_root.mkdir(parents=True,exist_ok=True)
            pdf=daily_root/'synthetic.pdf'
            shutil.copyfile(Path(__file__).parent/'fixtures/workbench/translated.pdf',pdf)
            paper={'id':'daily-synthetic','arxiv_id':'2609.99999','title':'Daily 合成验收：从发现到阅读','authors':'PaperPilot tests','abstract':'自制合成样例，不是生产论文。','is_daily':True,'daily_date':'2026-09-10','fetch_date':'2026-09-10','fetch_category':'cs.AI','subject':'cs.AI','categories':['cs.AI'],'file_path':str(pdf),'artifact_status':'ready'}
            PaperDAO.save_paper(paper);DailyArxivDAO.save_candidate(paper)
        server = make_server("127.0.0.2", 7191, application, threaded=True)
        print("Synthetic unified application ready", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            app_module.shutdown_application()
