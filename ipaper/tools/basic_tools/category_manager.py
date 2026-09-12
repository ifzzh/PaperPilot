from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional
from ipaper.database.dao.category_dao import CategoryDAO
from ipaper.security.paths import paper_directory

# Empty default classification structure (only root, no subcategories)
EMPTY_CATEGORIES: Dict[str, Any] = {
    "id": "root",
    "name": "Root",
    "children": [],
}


def init_categories(
    categories_file: str, default: Optional[Dict[str, Any]] = None
) -> None:
    # Check if DB has categories
    rows = CategoryDAO.get_all_categories()
    if rows:
        return

    if not os.path.exists(categories_file):
        # if not specified default, use an empty classification structure
        categories_to_save = default if default is not None else EMPTY_CATEGORIES
        save_categories(categories_file, categories_to_save)
    else:
        # Migrate from file
        with open(categories_file, "r", encoding="utf-8") as f:
            cats = json.load(f)
            save_categories(categories_file, cats)


def get_categories(categories_file: str) -> Dict[str, Any]:
    rows = CategoryDAO.get_all_categories()
    if not rows:
        # Fallback to file
        if os.path.exists(categories_file):
            try:
                with open(categories_file, "r", encoding="utf-8") as f:
                    cats = json.load(f)
                    # Optional: Auto-migrate
                    save_categories(categories_file, cats)
                    return cats
            except:
                pass
        return {"id": "root", "name": "Root", "children": []}

    from copy import deepcopy
    from ipaper.database.dao.settings_dao import SettingsDAO
    nodes = {row['id']: dict(row, children=[]) for row in rows}
    root = nodes.get('root', deepcopy(EMPTY_CATEGORIES))
    preferences = SettingsDAO.get_setting('category_ui', {})
    if not isinstance(preferences, dict):
        preferences = {}
    for node in nodes.values():
        if node['id'] == 'root':
            continue
        parent = nodes.get(node.get('parent_id'), root)
        parent['children'].append(node)
        for field in ('pinned', 'color'):
            value = preferences.get(node['id'], {}).get(field)
            if value is not None:
                node[field] = value
    return root


def save_categories(categories_file: str, categories: Dict[str, Any]) -> None:
    # Logical root belongs to each owner, not the globally keyed categories table.
    # Keep old IDs/asset directories; replace the tree and UI metadata atomically.
    CategoryDAO.replace_tree(categories)


def find_category_node(
    categories: Dict[str, Any], category_id: str
) -> Optional[Dict[str, Any]]:
    if categories.get("id") == category_id:
        return categories
    for child in categories.get("children", []):
        result = find_category_node(child, category_id)
        if result:
            return result
    return None


def get_category_path(
    categories: Dict[str, Any],
    category_id: str,
    path: Optional[List[str]] = None,
) -> Optional[List[str]]:
    if path is None:
        path = []
    if categories.get("id") == category_id:
        return path + [categories["name"]]
    for child in categories.get("children", []):
        result = get_category_path(child, category_id, path + [categories["name"]])
        if result:
            return result
    return None


def create_category_folder(upload_folder: str, category_id: str) -> str:
    return str(paper_directory(upload_folder, category_id, create=True))


def get_category_pdf_count(
    categories: Dict[str, Any],
    category_id: str,
    get_papers_in_category: Callable[[str, List[str]], List[Any]],
) -> int:
    target_node = find_category_node(categories, category_id)
    if not target_node:
        return 0

    def traverse(node: Dict[str, Any]) -> int:
        total = 0
        path = get_category_path(categories, node["id"])
        if path:
            total += len(get_papers_in_category(node["id"], path))
        for child in node.get("children", []):
            total += traverse(child)
        return total

    return traverse(target_node)


def add_pdf_counts_to_categories(
    categories: Dict[str, Any],
    count_func: Callable[[str], int],
) -> Dict[str, Any]:
    categories_copy = json.loads(json.dumps(categories))

    def add_counts(node: Dict[str, Any]) -> None:
        node["pdf_count"] = count_func(node["id"])
        for child in node.get("children", []):
            add_counts(child)

    add_counts(categories_copy)
    return categories_copy
