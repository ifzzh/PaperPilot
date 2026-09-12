"""Unified same-origin application assets and historical URL compatibility."""
from pathlib import Path, PurePosixPath
import json

from flask import abort, redirect, render_template, request


def build_assets(static_folder: str) -> dict:
    root = Path(static_folder) / "workbench"
    manifest = json.loads((root / ".vite/manifest.json").read_text())
    entry = manifest["src/main.tsx"]
    css, seen = [], set()

    def asset(name):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("invalid build asset")
        resolved = (root / name).resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            raise ValueError("missing build asset")
        return "workbench/" + name

    def visit(chunk):
        if not isinstance(chunk, dict):
            raise ValueError("invalid build manifest")
        for name in chunk.get("css", []):
            path = asset(name)
            if path not in css:
                css.append(path)
        for key in chunk.get("imports", []):
            if key not in seen:
                seen.add(key)
                visit(manifest[key])
                asset(manifest[key]["file"])

    # Check lazy reader chunks too, without loading their CSS on the list page.
    for chunk in manifest.values():
        if not isinstance(chunk, dict):
            raise ValueError("invalid build manifest")
        asset(chunk["file"])
        for name in chunk.get("css", []) + chunk.get("assets", []):
            asset(name)
    visit(entry)
    return {"script": asset(entry["file"]), "styles": css}


def render_workspace():
    from flask import current_app
    try:
        assets = build_assets(current_app.static_folder)
    except (OSError, ValueError, KeyError, TypeError):
        return render_template("workbench_unavailable.html"), 503
    response = current_app.make_response(render_template("workbench.html", **assets))
    response.headers["Cache-Control"] = "no-store"
    return response


def register_workbench(app):
    from ipaper.workspace_state import register_workspace_state
    register_workspace_state(app)

    @app.get("/workbench")
    @app.get("/workbench/")
    def workbench():
        query = request.query_string.decode("utf-8", errors="replace")
        return redirect("/" + ("?" + query if query else ""), code=302)
