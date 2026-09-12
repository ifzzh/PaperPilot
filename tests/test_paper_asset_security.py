import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from flask import Flask

from ipaper.core.base_paper import Paper
from ipaper.core.paper_store import PaperStore
from ipaper.routes.basic_routes.paper_operation_route import (
    register_paper_operation_routes,
)
from ipaper.security.paths import category_directory, paper_asset_paths
from ipaper.tools.basic_tools.paper_repository import delete_paper_files


class TestPaperAssetSecurity(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "papers"
        self.root.mkdir()
        self.store = PaperStore()
        self.delete_callback = Mock()
        self.save_callback = Mock()
        app = Flask(__name__)
        categories = {
            "id": "root",
            "name": "Root",
            "children": [
                {"id": "category-a", "name": "Category A", "children": []}
            ],
        }
        register_paper_operation_routes(
            app,
            get_categories=lambda: categories,
            get_category_path=lambda tree, category_id, path=None: [
                "Root",
                "Category A",
            ],
            find_category_node=lambda tree, category_id: tree["children"][0],
            get_papers_in_category=lambda category_id, path: [],
            save_paper_metadata=self.save_callback,
            delete_paper_files=self.delete_callback,
            extract_pdf_metadata=None,
            search_arxiv_by_title=None,
            reading_list_file=str(self.root / "reading-list.json"),
            upload_folder=str(self.root),
            paper_store=self.store,
        )
        self.client = app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _register(self, paper: Paper):
        self.store.upsert(
            paper,
            category_id="category-a",
            category_path=["Root", "Category A"],
        )

    def test_download_rejects_stored_path_mismatch_without_leaking_path(self):
        outside = self.root.parent / "outside.pdf"
        outside.write_bytes(b"outside")
        paper = Paper(id="paper-id", filename="paper.pdf", file_path=str(outside))
        self._register(paper)

        response = self.client.get("/api/paper/paper-id/file")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "unsafe_stored_path")
        self.assertNotIn(str(outside), response.get_data(as_text=True))

    def test_delete_rejects_stored_path_mismatch_and_keeps_record(self):
        outside = self.root.parent / "outside.pdf"
        outside.write_bytes(b"outside")
        paper = Paper(id="paper-id", filename="paper.pdf", file_path=str(outside))
        self._register(paper)

        response = self.client.delete("/api/paper/paper-id")

        self.assertEqual(response.status_code, 409)
        self.assertTrue(outside.exists())
        self.assertIsNotNone(self.store.get("paper-id"))
        self.delete_callback.assert_not_called()

    def test_download_serves_only_server_derived_pdf(self):
        directory = category_directory(self.root, "category-a", create=True)
        pdf = directory / "paper.pdf"
        pdf.write_bytes(b"%PDF-test")
        self._register(Paper(id="paper-id", filename="paper.pdf", file_path=str(pdf)))

        response = self.client.get("/api/paper/paper-id/file")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF-test")

    def test_update_rejects_internal_fields_atomically(self):
        directory = category_directory(self.root, "category-a", create=True)
        pdf = directory / "paper.pdf"
        pdf.write_bytes(b"%PDF-test")
        paper = Paper(
            id="paper-id",
            title="Original",
            filename="paper.pdf",
            file_path=str(pdf),
        )
        self._register(paper)

        response = self.client.put(
            "/api/paper/paper-id",
            json={"title": "Changed", "file_path": "/etc/passwd"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["fields"], ["file_path"])
        self.assertEqual(paper.title, "Original")
        self.save_callback.assert_not_called()

    def test_delete_removes_only_exact_named_assets(self):
        directory = category_directory(self.root, "category-a", create=True)
        pdf = directory / "paper.pdf"
        pdf.write_bytes(b"pdf")
        assets = paper_asset_paths(self.root, pdf)
        assets.chinese_dual.write_bytes(b"translation")
        assets.analysis_result.parent.mkdir(parents=True)
        assets.analysis_result.write_text("analysis")
        similarly_named = directory / "outputs" / "paper-backup" / "keep.txt"
        similarly_named.parent.mkdir(parents=True)
        similarly_named.write_text("keep")

        delete_paper_files(str(self.root), str(pdf))

        self.assertFalse(pdf.exists())
        self.assertFalse(assets.chinese_dual.exists())
        self.assertFalse(assets.analysis_directory.exists())
        self.assertTrue(similarly_named.exists())


if __name__ == "__main__":
    unittest.main()
