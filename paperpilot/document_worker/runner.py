from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .safety import (
    DocumentLimits,
    extract_validated_archive,
    inspect_pdf,
    preflight_archive,
    validate_zotero_rdf,
)


def run(job: Path, kind: str) -> None:
    work = job / "work"
    output = work / "output"
    limits = DocumentLimits.from_env()
    if output.exists():
        raise RuntimeError("output_exists")
    if kind == "pdf_inspect":
        inspect_pdf(work / "input.pdf", output, limits)
        return
    if kind in {"metadata_zip", "mineru_zip"}:
        manifest = preflight_archive(work / "input.zip", kind, limits)
        extract_validated_archive(work / "input.zip", output, manifest, limits)
        return
    if kind == "zotero_rdf":
        data = (work / "input.rdf").read_bytes()
        count = validate_zotero_rdf(data, limits)
        output.mkdir(mode=0o700)
        from paperpilot.tools.basic_tools.zotero_parser import ZoteroRDFParser

        papers = ZoteroRDFParser(str(work / "input.rdf")).parse()
        if len(papers) > limits.max_rdf_records or len(papers) > count:
            raise RuntimeError("rdf_record_limit")
        result = {"papers": [paper.to_dict() for paper in papers]}
        target = output / "result.json"
        target.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.chmod(target, 0o600)
        return
    raise RuntimeError("unsupported_document_kind")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(2)
    job = Path(sys.argv[1]).resolve(strict=True)
    run(job, sys.argv[2])


if __name__ == "__main__":
    main()
