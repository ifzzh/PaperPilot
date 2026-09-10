"""Opt-in, same-origin entry for the experimental Web workbench."""
from pathlib import Path, PurePosixPath
import json

from flask import abort, redirect, render_template, request


def parse_workbench_flag(value: str = "false") -> bool:
    value = value.strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("PAPERPILOT_WORKBENCH_ENABLED must be true/false or 1/0")
    return value in {"true", "1"}


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


def register_workbench(app):
    app.config.setdefault("PAPERPILOT_WORKBENCH_ENABLED", False)

    @app.get("/workbench")
    @app.get("/workbench/")
    def workbench():
        if not app.config["PAPERPILOT_WORKBENCH_ENABLED"]:
            abort(404)
        if request.path.endswith("/"):
            query = request.query_string.decode("utf-8", errors="replace")
            target = "/workbench" + ("?" + query if query else "")
            return redirect(target, code=308)
        try:
            assets = build_assets(app.static_folder)
        except (OSError, ValueError, KeyError, TypeError):
            return render_template("workbench_unavailable.html"), 503
        response = app.make_response(render_template("workbench.html", **assets))
        response.headers["Cache-Control"] = "no-store"
        return response
