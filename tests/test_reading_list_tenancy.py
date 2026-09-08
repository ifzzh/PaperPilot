import tempfile
import unittest
import uuid
from pathlib import Path

from flask import Flask

from paperpilot.core.paper_store import paper_store
from paperpilot.database import connection
from paperpilot.database.db_manager import init_db_schema
from paperpilot.routes.basic_routes.paper_operation_route import (
    register_paper_operation_routes,
)
from paperpilot.security.identity import Identity, reset_background_identity, set_background_identity
from paperpilot.security.paths import paper_directory


class TestReadingListTenancy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "papers"
        self.root.mkdir()
        self.original_db = connection.DB_PATH
        connection.DB_PATH = str(Path(self.temp.name) / "paperpilot.db")
        init_db_schema(connection.DB_PATH)
        self.user_id = str(uuid.uuid4())
        self.identity_token = set_background_identity(
            Identity(self.user_id, "reader", "user")
        )
        paper_store.reset()
        reading_dir = paper_directory(self.root, "reading_list_temp", create=True)
        (reading_dir / "existing.pdf").write_bytes(b"%PDF-test")

        self.app = Flask(__name__)
        register_paper_operation_routes(
            self.app,
            get_categories=lambda: {"id": "root", "children": []},
            get_category_path=lambda *_args, **_kwargs: None,
            find_category_node=lambda *_args, **_kwargs: None,
            get_papers_in_category=lambda *_args, **_kwargs: [],
            save_paper_metadata=lambda *_args, **_kwargs: None,
            delete_paper_files=lambda *_args, **_kwargs: None,
            extract_pdf_metadata=None,
            search_arxiv_by_title=None,
            reading_list_file=str(self.root / "reading-list.json"),
            upload_folder=str(self.root),
            paper_store=paper_store,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        paper_store.reset()
        connection.close_db()
        connection.DB_PATH = self.original_db
        reset_background_identity(self.identity_token)
        self.temp.cleanup()

    def test_endpoint_discovers_existing_pdf_in_current_users_reading_directory(self):
        response = self.client.get("/api/reading-list")

        self.assertEqual(response.status_code, 200)
        papers = response.get_json()
        self.assertEqual([paper["filename"] for paper in papers], ["existing.pdf"])
        self.assertIn(f"/.users/{self.user_id}/_ReadingListTemp/", papers[0]["file_path"])


if __name__ == "__main__":
    unittest.main()
