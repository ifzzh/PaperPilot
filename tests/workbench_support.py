"""Isolated workbench fixture: real auth/DAO/API, no workers or external services."""
from pathlib import Path

from flask import Flask

import app as app_module
from ipaper.auth import AuthConfig
from ipaper.database import connection
from ipaper.database.db_manager import init_db_schema
from ipaper.database.dao.paper_dao import PaperDAO
from ipaper.core.base_paper import Paper
from ipaper.core.paper_store import PaperStore
from ipaper.local_auth import LocalAuthService
from ipaper.routes.basic_routes.paper_operation_route import register_paper_operation_routes
from ipaper.security.identity import Identity, run_as_identity
from ipaper.workbench import register_workbench

ROOT = Path(__file__).resolve().parents[1]


def make_workbench_fixture(root, monkeypatch, count=3, *, cold=False):
    root = Path(root)
    (root / "papers").mkdir(exist_ok=True)
    monkeypatch.setattr(connection, 'DB_PATH', str(root / 'ipaper.db'))
    init_db_schema(connection.DB_PATH)
    application = Flask('workbench-test', static_folder=str(ROOT / 'static'), template_folder=str(ROOT / 'templates'))
    application.config.update(TESTING=True, IPAPER_WORKBENCH_ENABLED=True)
    register_workbench(application)
    application.before_request(app_module._require_auth_for_api)
    application.teardown_appcontext(connection.close_db)

    @application.after_request
    def headers(response):
        response.headers.update(app_module._browser_security_headers())
        return app_module._private_paper_asset_response(response)

    for path, endpoint, function, methods in [
        ('/', 'index', app_module.index, ['GET']),
        ('/api/auth/login', 'auth_login', app_module.auth_login, ['POST']),
        ('/api/auth/session', 'auth_session', app_module.auth_session, ['GET', 'DELETE']),
        ('/viewer/<paper_id>', 'pdf_viewer', app_module.pdf_viewer, ['GET']),
    ]:
        application.add_url_rule(path, endpoint, function, methods=methods)
    monkeypatch.setattr(app_module, 'AUTH_CONFIG', AuthConfig('development', 'local', False))
    monkeypatch.setattr(app_module, 'AUTH_SERVICE', LocalAuthService())
    app_module._rate_limiter.clear()
    store = PaperStore()
    monkeypatch.setattr(app_module, 'paper_store', store)
    from ipaper.tools.basic_tools import paper_repository, category_manager
    from ipaper.security.paths import paper_path
    from functools import partial
    monkeypatch.setattr(paper_repository, 'paper_store', store)
    categories = {'id': 'root', 'name': 'Root', 'children': [
        {'id': 'library', 'name': '文献分类', 'children': []}
    ]} if cold else {'id': 'root', 'name': 'Root', 'children': []}
    register_paper_operation_routes(
        application, get_categories=(partial(category_manager.get_categories, str(root / "unused.json")) if cold else lambda: categories),
        get_category_path=category_manager.get_category_path if cold else lambda *args: ['Root'], find_category_node=lambda *args: categories,
        get_papers_in_category=partial(paper_repository.get_papers_in_category, str(root / "papers")) if cold else lambda *args: [], save_paper_metadata=lambda *args: None,
        delete_paper_files=lambda *args: None, extract_pdf_metadata=None,
        search_arxiv_by_title=None, reading_list_file=str(root / 'reading.json'),
        upload_folder=str(root / 'papers'), paper_store=store,
    )
    with application.app_context():
        service = app_module.AUTH_SERVICE
        first = service.create_bootstrap_admin('reader_one', 'workbench-test-pass')
        _, invitation = service.create_invite(first['id'])
        second = service.register('reader_two', 'workbench-test-pass', invitation)
        connection.get_db().execute('UPDATE users SET must_change_password=0')
        connection.get_db().commit()
        for user, prefix, amount in [(first, 'a', count), (second, 'b', 1)]:
            def seed():
                if cold and prefix == "a":
                    category_manager.save_categories("unused", categories)
                for i in range(amount):
                    paper = Paper(id=f'{prefix}-{i}', title=(
                        'Learning to read the world: a unified framework for embodied reasoning' if i == 0 else
                        '<img src=x onerror=alert(1)> 不可信标题' if i == 1 else
                        f'研究文献 {i + 1} · 面向长时序任务的多模态理解与可靠推理'
                    ), authors='Chen Wang, Maya Lee, Alex Kim', year='2026',
                        abstract='' if i == 2 else '我们研究多模态系统如何从复杂环境中提取可靠的信息，并在长时序任务中保持稳定的推理能力。\n\nExperiments evaluate generalization, efficiency, and robust representations across varied environments.',
                        upload_date=f'2026-09-10T{i:04d}', starred=i == 0,
                        has_chinese_version=i == 0, translation_status='completed' if i == 0 else 'idle',
                        analysis_status='failed' if i == 1 else 'idle')
                    if cold:
                        category = ('root', 'library', 'reading_list_temp')[i % 3]
                        target = paper_path(root / 'papers', category, f'{prefix}-{i}.pdf', create_parent=True)
                        target.write_bytes((ROOT / 'tests/fixtures/workbench/original.pdf').read_bytes())
                        paper.filename = target.name
                        paper.file_path = str(target)
                    PaperDAO.save_paper(paper.to_dict())
                    if not cold:
                        store.upsert(paper, category_id='root', category_path=['Root'])
            run_as_identity(Identity(user['id'], user['username'], user['role']), seed)
    return application, first, second
