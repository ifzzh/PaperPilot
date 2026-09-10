from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from flask import Flask, jsonify, request, send_file

from paperpilot.core.base_paper import Paper, PaperUpdateError
from paperpilot.core.paper_store import PaperStore
from paperpilot.database.dao.user_data_dao import ReadingListDAO, ReadingHistoryDAO
from paperpilot.database.dao.document_job_dao import DocumentJobDAO
from paperpilot.document_worker.client import DocumentWorkerClient
from paperpilot.security.paths import (
    PathSecurityError,
    ensure_confined,
    ensure_confined_tree,
    paper_asset_paths,
    paper_path,
    paper_directory,
    verified_paper_path,
)
from paperpilot.security.identity import current_user_id
from paperpilot.tools.basic_tools.paper_repository import scan_papers_in_directory
from paperpilot.tools.basic_tools.upload_paper import (
    search_arxiv_by_title_only,
)


_paper_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="paper-metadata")


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
    ) -> Optional[Dict[str, Any]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Paper]: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


class DeletePaperFilesFn(Protocol):
    def __call__(self, pdf_path: str) -> None: ...


class AddToReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


class RemoveFromReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


def register_paper_operation_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    find_category_node: FindCategoryNodeFn,
    get_papers_in_category: GetPapersInCategoryFn,
    save_paper_metadata: SavePaperMetadataFn,
    delete_paper_files: DeletePaperFilesFn,
    extract_pdf_metadata: Optional[Any],  # No longer used, reserved for compatibility
    search_arxiv_by_title: Optional[Any],  # No longer used, reserved for compatibility
    reading_list_file: str,
    upload_folder: str,
    paper_store: PaperStore,
    document_client: DocumentWorkerClient | None = None,
) -> None:
    document_client = document_client or DocumentWorkerClient()
    reading_list_scan_mtime_by_owner: dict[str, float] = {}

    def load_reading_list() -> List[str]:
        items = ReadingListDAO.get_list()
        return [item['paper_id'] for item in items]

    def save_reading_list(paper_ids: List[str]) -> None:
        pass

    def add_to_reading_list(paper_id: str) -> None:
        ReadingListDAO.add_item(paper_id, datetime.now().isoformat())

    def remove_from_reading_list(paper_id: str) -> None:
        ReadingListDAO.remove_item(paper_id)

    def is_in_reading_list(paper_id: str) -> bool:
        return paper_id in load_reading_list()

    def find_paper(paper_id: str) -> Optional[Tuple[Paper, List[str], str]]:
        entry = paper_store.get_entry(paper_id)
        if not entry:
            return None
        return entry.paper, list(entry.category_path), entry.category_id

    def resolve_paper_file(
        paper: Paper,
        category_id: str,
        *,
        must_exist: bool = True,
    ) -> str:
        return str(
            verified_paper_path(
                upload_folder,
                category_id,
                paper.filename,
                paper.file_path,
                must_exist=must_exist,
            )
        )

    def unsafe_stored_path_response():
        return jsonify({"success": False, "error": "unsafe_stored_path"}), 409

    def move_asset_bundle(source_assets, target_assets) -> None:
        """Preflight and move one paper's exact asset set within storage."""
        pairs = (
            (source_assets.pdf, target_assets.pdf),
            (source_assets.metadata, target_assets.metadata),
            (source_assets.chinese_dual, target_assets.chinese_dual),
            (source_assets.chinese_mono, target_assets.chinese_mono),
            (source_assets.translation_log, target_assets.translation_log),
        )
        moves = []
        for source, target in pairs:
            if source.exists():
                safe_source = ensure_confined(
                    upload_folder,
                    source,
                    must_exist=True,
                    require_file=True,
                )
                safe_target = ensure_confined(upload_folder, target)
                if safe_target.exists():
                    raise FileExistsError("paper asset destination already exists")
                moves.append((safe_source, safe_target))

        analysis_move = None
        if source_assets.analysis_directory.exists():
            safe_source = ensure_confined_tree(
                upload_folder,
                source_assets.analysis_directory,
            )
            safe_target = ensure_confined(
                upload_folder,
                target_assets.analysis_directory,
            )
            if safe_target.exists():
                raise FileExistsError("paper analysis destination already exists")
            analysis_move = (safe_source, safe_target)

        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        if analysis_move:
            source, target = analysis_move
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))

    def collect_papers_by_ids(paper_ids: Iterable[str]) -> List[Paper]:
        ordered_ids = list(paper_ids)
        collected: List[Paper] = []
        seen: set[str] = set()
        for pid in ordered_ids:
            if pid in seen:
                continue
            paper = paper_store.get(pid)
            if paper:
                collected.append(paper)
                seen.add(pid)
        return collected

    @app.route("/api/papers/all")
    def api_all_papers():
        """Get all papers, sorted by upload date in descending order"""
        all_papers = paper_store.iter_all()
        # Sort by upload date in descending order (newest first)
        sorted_papers = sorted(
            all_papers, key=lambda p: p.upload_date or "", reverse=True
        )
        return jsonify([paper.to_dict() for paper in sorted_papers])

    @app.route("/api/papers/<category_id>")
    def api_papers(category_id: str):
        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"error": "Category not found"}), 404

        papers = get_papers_in_category(category_id, category_path)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/papers/<category_id>/recursive")
    def api_papers_recursive(category_id: str):
        """Recursively obtain papers under a category and all its subcategories (for first-level directories/Project）"""
        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if not category_node:
            return jsonify({"error": "Category not found"}), 404

        def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
            """Recursively collect all papers under a category and its subcategories"""
            all_papers = []

            # Get papers in the current category
            node_path = get_category_path(categories, node["id"])
            if node_path:
                node_papers = get_papers_in_category(node["id"], node_path)
                all_papers.extend(node_papers)

            # Recursively process subcategories
            for child in node.get("children", []):
                all_papers.extend(collect_papers_recursive(child))

            return all_papers

        all_papers = collect_papers_recursive(category_node)

        # Sort by upload time (newest first)
        sorted_papers = sorted(
            all_papers, key=lambda p: p.upload_date or "", reverse=True
        )

        return jsonify([paper.to_dict() for paper in sorted_papers])

    @app.route("/api/paper/<paper_id>")
    def api_paper_info(paper_id: str):
        result = find_paper(paper_id)
        if result:
            paper, _, _ = result
            return jsonify(paper.to_dict())
        return jsonify({"error": "Paper not found"}), 404

    @app.route("/api/paper/<paper_id>/move", methods=["PUT"])
    def api_move_paper(paper_id: str):
        data = request.json or {}
        target_category_id = data.get("target_category_id")

        if not target_category_id:
            return (
                jsonify({"success": False, "error": "Target category ID is required"}),
                400,
            )

        categories = get_categories()
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper_obj, _, source_category_id = result

        target_category = find_category_node(categories, target_category_id)
        if not target_category:
            return (
                jsonify({"success": False, "error": "Target category not found"}),
                404,
            )

        target_path = get_category_path(categories, target_category_id)
        if not target_path:
            return (
                jsonify({"success": False, "error": "Target category path not found"}),
                404,
            )

        try:
            source_file_path = resolve_paper_file(paper_obj, source_category_id)
            source_assets = paper_asset_paths(upload_folder, source_file_path)

            target_file_path = str(
                paper_path(
                    upload_folder,
                    target_category_id,
                    paper_obj.filename,
                    create_parent=True,
                )
            )
            counter = 1
            original_filename = paper_obj.filename
            while os.path.exists(target_file_path):
                name, ext = os.path.splitext(original_filename)
                new_filename = f"{name}_{counter}{ext}"
                target_file_path = str(
                    paper_path(upload_folder, target_category_id, new_filename)
                )
                counter += 1

            target_assets = paper_asset_paths(upload_folder, target_file_path)

            move_asset_bundle(source_assets, target_assets)

            paper_obj.chinese_version_path = (
                str(target_assets.chinese_dual)
                if target_assets.chinese_dual.exists()
                else None
            )
            paper_obj.analysis_result_path = (
                str(target_assets.analysis_result)
                if target_assets.analysis_result.exists()
                else None
            )

            # renewPaperBasic information about the object
            paper_obj.filename = os.path.basename(target_file_path)
            paper_obj.file_path = target_file_path

            # First update the category information in paper_store
            # so that the search index sees the latest category when saving metadata.
            paper_store.update_category(
                paper_id,
                category_id=target_category_id,
                category_path=target_path,
            )

            # Save updated metadata and update search index (with the new category)
            save_paper_metadata(target_file_path, paper_obj)

            return jsonify(
                {
                    "success": True,
                    "paper": paper_obj.to_dict(),
                    "source_category": source_category_id,
                    "target_category": target_category_id,
                }
            )

        except PathSecurityError:
            return unsafe_stored_path_response()
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to move paper: {exc}")
            return (
                jsonify({"success": False, "error": f"Failed to move file: {exc}"}),
                500,
            )

    @app.route("/api/paper/<paper_id>/file")
    def api_get_paper_file(paper_id: str):
        result = find_paper(paper_id)
        if not result:
            return jsonify({"error": "Paper not found"}), 404

        paper, _, category_id = result
        try:
            # Validate confinement/mismatch before classifying an absent file.
            resolve_paper_file(paper, category_id, must_exist=False)
            file_path = resolve_paper_file(paper, category_id)
        except PathSecurityError as exc:
            if str(exc) == "missing_path":
                return jsonify({"error": "PDF file not found"}), 404
            return unsafe_stored_path_response()

        try:
            response = send_file(
                file_path,
                as_attachment=False,
                mimetype="application/pdf",
            )
        except FileNotFoundError:
            return jsonify({"error": "PDF file not found"}), 404
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/api/paper/<paper_id>", methods=["DELETE"])
    def api_delete_paper(paper_id: str):
        try:
            result = find_paper(paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, _, category_id = result
            try:
                file_path = resolve_paper_file(paper, category_id)
            except PathSecurityError:
                return unsafe_stored_path_response()
            delete_paper_files(file_path)
            paper_store.remove(paper_id)

            return jsonify(
                {
                    "success": True,
                    "message": "Paper deleted successfully",
                    "paper": paper.to_dict(),
                    "category_id": category_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to delete paper: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>", methods=["PUT"])
    def api_update_paper(paper_id: str):
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "invalid_payload"}), 400
            result = find_paper(paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Check whether the user has modified it manually title
            old_title = paper.title
            title_changed = False
            if "title" in data and data["title"] != old_title:
                title_changed = True
                new_title = data["title"]
                print(
                    f"[Title update] User changes title: '{old_title}' → '{new_title}'"
                )

            try:
                paper.update_user_fields(data)
            except PaperUpdateError as exc:
                payload = {"error": exc.reason}
                if exc.fields:
                    payload["fields"] = list(exc.fields)
                return jsonify(payload), 400
            paper.extra["updated_date"] = datetime.now().isoformat()

            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # If the user modified title, automatically re-crawl in the background
            if title_changed and new_title:

                def _auto_refresh_on_title_change():
                    try:
                        print(
                            f"[Automatic recapture] The title has been modified, start crawling again: {new_title}"
                        )

                        # Search using the new interface arXiv
                        best_match = search_arxiv_by_title_only(new_title)

                        if best_match:
                            print(
                                f"[Automatic recapture] found match: {best_match.get('title')[:50]}..."
                            )

                            # Update only arXiv Related information, do not modify the manual settings set by the user title
                            paper_obj = paper_store.get(paper_id)
                            if paper_obj:
                                # Update except title All fields except
                                paper_obj.authors = best_match.get("authors", "")
                                paper_obj.affiliation = best_match.get(
                                    "affiliation", ""
                                )
                                paper_obj.abstract = best_match.get("abstract", "")
                                paper_obj.year = best_match.get("year", "")
                                paper_obj.bibtex = best_match.get("bibtex", "")
                                paper_obj.arxiv_id = best_match.get("arxiv_id", "")
                                paper_obj.arxiv_published_date = best_match.get(
                                    "published_date"
                                )
                                paper_obj.summary = best_match.get("summary", "")
                                paper_obj.extra["auto_refreshed_date"] = (
                                    datetime.now().isoformat()
                                )

                                # Save updates
                                paper_store.upsert(
                                    paper_obj,
                                    category_id=category_id,
                                    category_path=category_path,
                                )
                                if paper_obj.file_path:
                                    save_paper_metadata(paper_obj.file_path, paper_obj)

                                print(
                                    f"[Automatic recapture] Completed: Author, affiliation, abstract and other information has been updated"
                                )
                            else:
                                print(
                                    f"[Automatic recapture] warn: not found paper {paper_id}"
                                )
                        else:
                            print(
                                f"[Automatic recapture] No match found, keep the information entered by the user unchanged"
                            )

                    except Exception as exc:  # noqa: BLE001
                        print(f"[Automatic recapture] fail: {exc}")

                _paper_workers.submit(_auto_refresh_on_title_change)

            return jsonify(
                {
                    "success": True,
                    "message": "Paper updated successfully",
                    "paper": paper.to_dict(),
                    "auto_refresh_triggered": title_changed,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to update paper: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/reading-list", methods=["GET"])
    def api_get_reading_list():
        paper_ids = load_reading_list()

        # Auto-sync: scan _ReadingListTemp directory
        # Optimization: Only scan if the directory has been modified
        reading_list_temp_path = str(paper_directory(upload_folder, "reading_list_temp"))
        should_scan = False
        
        if os.path.exists(reading_list_temp_path):
            try:
                # Check directory mtime
                mtime = os.path.getmtime(reading_list_temp_path)
                
                owner_id = current_user_id()
                if mtime > reading_list_scan_mtime_by_owner.get(owner_id, 0):
                    should_scan = True
                    reading_list_scan_mtime_by_owner[owner_id] = mtime
            except Exception:
                # If checking mtime fails, default to scanning (safer)
                should_scan = True

        if should_scan and os.path.exists(reading_list_temp_path):
            # Scan all papers in the directory
            temp_papers = scan_papers_in_directory(
                reading_list_temp_path,
                category_id="reading_list_temp",
                category_path=["Root", "_ReadingListTemp"],
            )

            # Add papers from _ReadingListTemp to the reading list (if not already present)
            for paper in temp_papers:
                if paper.id not in paper_ids:
                    add_to_reading_list(paper.id)
                    paper_ids.append(paper.id)

        # Return all reading list papers
        papers = collect_papers_by_ids(paper_ids)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/reading-list/<paper_id>/add", methods=["POST"])
    def api_add_to_reading_list(paper_id: str):
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        add_to_reading_list(paper_id)
        return jsonify({"success": True})

    @app.route("/api/reading-list/<paper_id>/remove", methods=["POST"])
    def api_remove_from_reading_list(paper_id: str):
        if not is_in_reading_list(paper_id):
            return (
                jsonify({"success": False, "error": "Paper not in reading list"}),
                404,
            )

        # Get paper information
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper, category_path, category_id = result

        # Check if it is still in the temporary directory used by the reading list.
        # We require BOTH the category information and the actual file path to match
        # the temp directory, to avoid accidentally deleting papers that have already
        # been moved into a normal category.
        is_temp_category = (
            category_id == "reading_list_temp"
            or (
                category_path
                and len(category_path) > 1
                and category_path[1] == "_ReadingListTemp"
            )
        )
        try:
            verified_file_path = resolve_paper_file(paper, category_id)
        except PathSecurityError:
            return unsafe_stored_path_response()
        is_in_temp_dir = category_id == "reading_list_temp"
        is_in_temp = is_temp_category and is_in_temp_dir

        # Get delete options
        data = request.json or {}
        delete_files = data.get("delete_files", False)

        # If it is in the temporary directory, the user is required to confirm the deletion of the file (regardless of the source)
        if is_in_temp and not delete_files:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Need to confirm deletion",
                        "requires_confirmation": True,
                        "message": "The paper has not been moved to a certain directory. Do you want to delete the paper file?",
                    }
                ),
                200,
            )  # return 200 for front-end processing

        # If file deletion is confirmed, delete the paper and its related files
        # As long as temp Delete files from directory
        if delete_files and is_in_temp:
            delete_paper_files(verified_file_path)
            paper_store.remove(paper_id)
        elif not is_in_temp:
            # if not temp Directory, only removed from the to-read list, files are not deleted
            # The paper remains in its original catalog
            pass

        # Remove from to-read list
        remove_from_reading_list(paper_id)

        # Returns whether the file was deleted (the file is only deleted when it is in the temporary directory and the user confirms the deletion)
        return jsonify({"success": True, "deleted_files": delete_files and is_in_temp})

    @app.route("/api/paper/<paper_id>/read-time", methods=["POST"])
    def api_record_read_time(paper_id: str):
        """Record paper reading time (cumulative increment)"""
        try:
            import json as json_lib
            import os
            from datetime import datetime

            data = request.json or {}
            # Use incremental mode
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "read_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Cumulative reading time increment
            paper.record_read_time(int(increment))

            # save to file
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # Update reading history
            today = datetime.now().strftime("%Y-%m-%d")
            duration = int(increment)
            timestamp = int(datetime.now().timestamp())
            
            ReadingHistoryDAO.add_history(today, duration, paper_id, timestamp)

            return jsonify({"success": True, "read_time": paper.read_time})

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to record reading time: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/analysis-view-time", methods=["POST"])
    def api_record_analysis_view_time(paper_id: str):
        """Record AI Interpretation reading time (cumulative increments)"""
        try:
            data = request.json or {}
            # Use incremental mode
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "analysis_view_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Cumulative interpretation reading time increment
            paper.record_analysis_view_time(int(increment))

            # save to file
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            return jsonify(
                {"success": True, "analysis_view_time": paper.analysis_view_time}
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Record interpretation reading time failed: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/refresh-metadata", methods=["POST"])
    def api_refresh_paper_metadata(paper_id: str):
        """Re-crawl PDF metadata"""
        try:
            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result
            try:
                file_path = resolve_paper_file(paper, category_id)
            except PathSecurityError:
                return unsafe_stored_path_response()

            # Start background thread processing
            def _refresh_metadata_async():
                try:
                    print(f"[Re-crawl] Start processing: {file_path}")

                    filename = os.path.basename(file_path)
                    validation_id = str(uuid.uuid4())
                    try:
                        with open(file_path, "rb") as source:
                            document_client.stage(validation_id, "pdf_inspect", source)
                        DocumentJobDAO.create(validation_id, "pdf_inspect", paper_id)
                        document_client.create(validation_id, "pdf_inspect")
                        state = document_client.wait(validation_id, timeout=100)
                        DocumentJobDAO.update(
                            validation_id, state["status"],
                            progress=int(state.get("progress") or 0), error=state.get("error")
                        )
                        if state["status"] != "completed":
                            return
                        result = document_client.result_json(validation_id)
                        raw_metadata = result.get("metadata", {})
                        paper_info = {
                            "title": raw_metadata.get("title", ""),
                            "authors": raw_metadata.get("author", ""),
                            "subject": raw_metadata.get("subject", ""),
                            "keywords": raw_metadata.get("keywords", ""),
                        }
                    finally:
                        try:
                            document_client.cleanup(validation_id)
                        except Exception:
                            pass

                    if not paper_info:
                        print("[Re-crawl] Unable to obtain paper information")
                        return

                    print(f"[Re-crawl] found match: {paper_info.get('title')[:50]}...")

                    # Use the information obtained
                    metadata = paper_info
                    arxiv_id = paper.arxiv_id
                    arxiv_published_date = paper.arxiv_published_date

                    # step2: Rename the file according to the new title (if the title changes)
                    current_filename = os.path.basename(file_path)
                    new_filename = current_filename
                    new_file_path = file_path
                    if metadata and metadata.get("title"):

                        def _clean_filename(text: Optional[str]) -> Optional[str]:
                            if not text:
                                return None
                            cleaned = text
                            cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
                            cleaned = re.sub(r"\s+", " ", cleaned)
                            cleaned = cleaned.strip()
                            return cleaned[:200] if cleaned else None

                        clean_title = _clean_filename(metadata["title"])
                        if (
                            clean_title
                            and clean_title != os.path.splitext(current_filename)[0]
                        ):
                            new_filename = f"{clean_title}.pdf"
                            new_file_path = str(
                                paper_path(
                                    upload_folder,
                                    category_id,
                                    new_filename,
                                )
                            )

                            counter = 1
                            original_new_filename = new_filename
                            while (
                                os.path.exists(new_file_path)
                                and new_file_path != file_path
                            ):
                                name, ext = os.path.splitext(original_new_filename)
                                new_filename = f"{name}_{counter}{ext}"
                                new_file_path = str(
                                    paper_path(
                                        upload_folder,
                                        category_id,
                                        new_filename,
                                    )
                                )
                                counter += 1

                            # Rename file
                            if new_file_path != file_path:
                                try:
                                    source_assets = paper_asset_paths(
                                        upload_folder, file_path
                                    )
                                    target_assets = paper_asset_paths(
                                        upload_folder, new_file_path
                                    )
                                    move_asset_bundle(source_assets, target_assets)
                                    print(
                                        f"[Re-crawl] File has been renamed: {new_filename}"
                                    )

                                except Exception as exc:  # noqa: BLE001
                                    print(f"[Re-crawl] Rename failed: {exc}")
                                    new_file_path = file_path
                                    new_filename = current_filename

                    # step3: renew Paper object
                    paper_obj = paper_store.get(paper_id)
                    if paper_obj and metadata:
                        paper_obj.filename = new_filename
                        paper_obj.file_path = new_file_path
                        paper_obj.title = metadata.get("title") or paper_obj.title
                        paper_obj.authors = metadata.get("authors") or paper_obj.authors
                        paper_obj.arxiv_id = arxiv_id
                        # if there is arxiv_id,set up arxiv_url
                        if arxiv_id:
                            paper_obj.arxiv_url = (
                                metadata.get("arxiv_url")
                                or f"https://arxiv.org/abs/{arxiv_id}"
                            )
                        paper_obj.arxiv_published_date = arxiv_published_date
                        paper_obj.keywords = metadata.get("keywords") or paper_obj.keywords
                        paper_obj.subject = metadata.get("subject") or paper_obj.subject
                        paper_obj.extra["updated_date"] = datetime.now().isoformat()

                        # Save updates
                        paper_store.upsert(
                            paper_obj,
                            category_id=category_id,
                            category_path=category_path,
                        )
                        save_paper_metadata(new_file_path, paper_obj)
                        print(f"[Re-crawl] Finish: {new_filename}")
                    else:
                        print(f"[Re-crawl] warn: not found paper {paper_id}")

                except Exception as exc:  # noqa: BLE001
                    print(f"[Re-crawl] fail: {exc}")

            _paper_workers.submit(_refresh_metadata_async)

            return jsonify(
                {
                    "success": True,
                    "message": "Metadata crawling has started and will be processed in the background",
                    "paper_id": paper_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to start re-crawling: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500
