"""Own generated fixtures: text, table markup and drawings, CC0 test content."""
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from ipaper.document_worker.structure import (
    bounded_json, normalize_mineru, split_pdf, _TableParser,
)
from ipaper.document_worker.safety import DocumentLimits, DocumentLimitError

fitz = pytest.importorskip("fitz")


def pdf(path, count=2):
    with fitz.open() as doc:
        for number in range(count):
            page = doc.new_page(width=600, height=800)
            page.insert_text((60, 80), f"Source page {number + 1}")
            if number == 1:
                page.set_rotation(90)
        doc.save(path)


def archive(path, *, items=None, extra=None):
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("x_content_list.json", json.dumps(items or [
            {"type": "text", "text": "Source page 1", "page_idx": 0,
             "bbox": [100, 80, 400, 110]},
            {"type": "text", "text": "Source page 2", "page_idx": 1,
             "bbox": [100, 80, 400, 110]},
        ]))
        out.writestr("layout.json", json.dumps({"_version_name":"3.4.4","_backend":"hybrid","pdf_info": [
            {"page_idx": 0, "page_size": [600, 800]},
            {"page_idx": 1, "page_size": [800, 600]},
        ]}))
        out.writestr("full.md", "# Synthetic source\nSource page 1")
        for name, value in (extra or {}).items():
            out.writestr(name, value)


def test_split_201_preserves_order_geometry_and_hashes(tmp_path):
    source = tmp_path / "input.pdf"
    pdf(source, 201)
    split_pdf(source, tmp_path / "out", DocumentLimits())
    result = json.loads((tmp_path / "out/result.json").read_text())
    assert result["pageCount"] == 201
    assert [(p["firstPage"], p["lastPage"]) for p in result["parts"]] == [(1, 200), (201, 201)]
    assert result["pages"][1]["rotation"] == 90
    with fitz.open(tmp_path / "out" / result["parts"][1]["path"]) as check:
        assert "Source page 201" in check[0].get_text()
    assert len(json.loads((tmp_path / "out/manifest.json").read_text())["entries"]) == 3


def test_normalize_keeps_json_and_only_proven_region(tmp_path):
    source, bundle, output = tmp_path / "input.pdf", tmp_path / "input.zip", tmp_path / "out"
    pdf(source)
    archive(bundle)
    normalize_mineru(bundle, source, output, DocumentLimits())
    blocks = [json.loads(line) for line in (output / "blocks.jsonl").read_text().splitlines()]
    assert blocks[0]["source"]["precision"] == "region"
    assert blocks[0]["source"]["regions"][0]["rect"] == pytest.approx([60, 712, 240, 736])
    assert blocks[1]["source"]["precision"] == "page"
    assert (output / "raw/x_content_list.json").is_file()
    assert (output / "raw/layout.json").is_file()
    assert (output / "raw/archive-manifest.json").is_file()
    other = tmp_path / "again"
    normalize_mineru(bundle, source, other, DocumentLimits())
    assert (output / "blocks.jsonl").read_bytes() == (other / "blocks.jsonl").read_bytes()


def test_missing_page_bbox_and_image_path_are_not_guessed(tmp_path):
    pdf(tmp_path / "input.pdf")
    archive(tmp_path / "input.zip", items=[
        {"type": "text", "text": "no page", "page_idx": 99, "bbox": [0, 0, 1, 1]},
        {"type": "image", "page_idx": 0, "img_path": "../../secret.png"},
        {"type": "text", "page_idx": 0, "bbox": [0.1, 0.1, 0.2, 0.2]},
    ])
    normalize_mineru(tmp_path / "input.zip", tmp_path / "input.pdf", tmp_path / "out", DocumentLimits())
    blocks = [json.loads(s) for s in (tmp_path / "out/blocks.jsonl").read_text().splitlines()]
    assert blocks[0]["source"]["precision"] == "none"
    assert blocks[1]["image"] is None


@pytest.mark.parametrize("extra", [
    {"../escape.json": "{}"}, {"arbitrary.pdf": "%PDF-1.7"},
    {"00000000-0000-0000-0000-000000000001_origin.pdf": "PDF",
     "00000000-0000-0000-0000-000000000002_origin.pdf": "PDF"},
])
def test_structure_retains_archive_rejections(tmp_path, extra):
    pdf(tmp_path / "input.pdf")
    archive(tmp_path / "input.zip", extra=extra)
    with pytest.raises(DocumentLimitError):
        normalize_mineru(tmp_path / "input.zip", tmp_path / "input.pdf", tmp_path / "out", DocumentLimits())


def test_json_depth_and_nonfinite_rejected(tmp_path):
    target = tmp_path / "a.json"
    target.write_text("[" * 40 + "0" + "]" * 40)
    with pytest.raises(DocumentLimitError, match="complexity"):
        bounded_json(target)
    target.write_text('{"x":NaN}')
    with pytest.raises(DocumentLimitError, match="invalid"):
        bounded_json(target)


def test_table_extracts_text_and_spans_without_html():
    parser = _TableParser()
    parser.feed('<table><tr><th colspan="2">Title<script>bad()</script></th></tr>'
                '<tr><td>A &amp; B</td><td><img src="https://evil">3</td></tr></table>')
    assert parser.rows[0][0] == {"text": "Title", "header": True, "colspan": 2, "rowspan": 1}
    assert parser.rows[1][0]["text"] == "A & B"
    assert parser.rows[1][1]["text"] == "3"


def test_unknown_parser_version_never_claims_region(tmp_path):
    pdf(tmp_path/'input.pdf')
    with zipfile.ZipFile(tmp_path/'input.zip','w') as bundle:
        bundle.writestr('x_content_list.json',json.dumps([{'type':'text','text':'data','page_idx':0,'bbox':[10,10,200,50]}]))
        bundle.writestr('layout.json',json.dumps({'_version_name':'future','_backend':'hybrid','pdf_info':[{'page_idx':0,'page_size':[600,800]}]}))
        bundle.writestr('full.md','data')
    normalize_mineru(tmp_path/'input.zip',tmp_path/'input.pdf',tmp_path/'out',DocumentLimits())
    block=json.loads((tmp_path/'out/blocks.jsonl').read_text())
    assert block['source']['precision']=='page'
    assert block['source']['parserCoordinates']=='unverified'
    assert block['source']['parserBox']==[10,10,200,50]
