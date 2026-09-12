import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from ipaper.document_worker.safety import (
    DocumentLimitError,
    DocumentLimits,
    bounded_copy,
    extract_validated_archive,
    inspect_pdf,
    preflight_archive,
    validate_zotero_rdf,
)
from ipaper.document_worker.runner import run


class DocumentSafetyContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.limits = DocumentLimits(
            max_pdf_bytes=1024 * 1024,
            max_archive_bytes=1024 * 1024,
            max_expanded_bytes=4096,
            max_entries=5,
            max_import_papers=2,
            max_entry_bytes=2048,
            max_compression_ratio=10,
            max_path_depth=8,
            max_json_bytes=2048,
            max_rdf_bytes=2048,
            max_rdf_records=2,
            max_pdf_pages=5,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _zip(self, name, entries):
        target = self.root / name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry_name, value in entries:
                if isinstance(value, zipfile.ZipInfo):
                    archive.writestr(value, b"payload")
                else:
                    archive.writestr(entry_name, value)
        return target

    def test_bounded_copy_does_not_leave_partial_file(self):
        destination = self.root / "upload.bin"
        with self.assertRaisesRegex(DocumentLimitError, "upload_too_large"):
            bounded_copy(io.BytesIO(b"x" * 17), destination, 16)
        self.assertFalse(destination.exists())

    def test_metadata_archive_is_preflighted_then_extracted(self):
        source = self._zip(
            "metadata.zip",
            [
                ("papers/.categories/abc/paper.json", b'{"title":"safe"}'),
                ("papers/categories.json", b"{}"),
                ("papers/.avatars/avatar.png", b"ignored"),
            ],
        )
        manifest = preflight_archive(source, "metadata_zip", self.limits)
        self.assertEqual([item.path for item in manifest.entries], [
            "papers/.categories/abc/paper.json",
            "papers/categories.json",
        ])
        self.assertEqual(manifest.ignored, ["papers/.avatars/avatar.png"])
        destination = self.root / "out"
        extract_validated_archive(source, destination, manifest, self.limits)
        self.assertTrue((destination / "papers/.categories/abc/paper.json").is_file())
        self.assertFalse((destination / "papers/.avatars/avatar.png").exists())

    def test_archive_rejects_paths_links_duplicates_and_types(self):
        symlink = zipfile.ZipInfo("papers/link.json")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = {
            "traversal.zip": [("papers/../escape.json", b"{}")],
            "absolute.zip": [("/papers/paper.json", b"{}")],
            "windows.zip": [(r"papers\\escape.json", b"{}")],
            "symlink.zip": [("ignored", symlink)],
            "type.zip": [("papers/payload.html", b"<script>")],
            "nested.zip": [("papers/archive.zip", b"PK")],
            "case.zip": [("papers/A.json", b"{}"), ("papers/a.json", b"{}")],
        }
        for filename, entries in cases.items():
            with self.subTest(filename=filename):
                source = self._zip(filename, entries)
                with self.assertRaises(DocumentLimitError):
                    preflight_archive(source, "metadata_zip", self.limits)

    def test_archive_rejects_entry_count_size_ratio_and_paper_count(self):
        cases = (
            ("entries.zip", [(f"papers/{i}.json", b"{}") for i in range(6)], "archive_entry_limit"),
            ("entry-size.zip", [("papers/a.json", b"a" * 2049)], "archive_entry_too_large"),
            ("ratio.zip", [("papers/a.json", b"a" * 1000)], "archive_ratio_limit"),
            ("papers.zip", [(f"papers/{i}.json", b"{}") for i in range(3)], "archive_paper_limit"),
        )
        for filename, entries, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(DocumentLimitError, reason):
                    preflight_archive(self._zip(filename, entries), "metadata_zip", self.limits)

    def test_mineru_archive_allows_only_declared_result_types(self):
        good = self._zip("mineru.zip", [("result.md", b"# ok"), ("images/page.png", b"png")])
        manifest = preflight_archive(good, "mineru_zip", self.limits)
        self.assertEqual({item.path for item in manifest.entries}, {"result.md", "images/page.png"})
        bad = self._zip("mineru-bad.zip", [("result.pdf", b"%PDF")])
        with self.assertRaisesRegex(DocumentLimitError, "archive_type_forbidden"):
            preflight_archive(bad, "mineru_zip", self.limits)

    def test_pdf_structure_page_limit_and_symlink_are_checked(self):
        import fitz

        valid = self.root / "valid.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Title")
        doc.save(valid)
        doc.close()
        output = self.root / "pdf-out"
        result = inspect_pdf(valid, output, self.limits)
        self.assertEqual(result["page_count"], 1)
        self.assertTrue((output / "thumbnail.jpg").is_file())

        invalid = self.root / "invalid.pdf"
        invalid.write_bytes(b"%PDF-not-valid")
        with self.assertRaisesRegex(DocumentLimitError, "pdf_invalid"):
            inspect_pdf(invalid, self.root / "invalid-out", self.limits)

        link = self.root / "link.pdf"
        link.symlink_to(valid)
        with self.assertRaisesRegex(DocumentLimitError, "unsafe_input"):
            inspect_pdf(link, self.root / "link-out", self.limits)

    def test_worker_outputs_are_readable_by_the_shared_web_group(self):
        import fitz

        job = self.root / "job"
        work = job / "work"
        work.mkdir(parents=True)
        pdf = work / "input.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Title")
        document.save(pdf)
        document.close()
        run(job, "pdf_inspect")
        output = work / "output"
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o2770)
        self.assertEqual(
            stat.S_IMODE((output / "result.json").stat().st_mode), 0o640
        )
        self.assertEqual(
            stat.S_IMODE((output / "thumbnail.jpg").stat().st_mode), 0o640
        )

    def test_rdf_rejects_entities_and_record_limit(self):
        with self.assertRaisesRegex(DocumentLimitError, "rdf_unsafe_xml"):
            validate_zotero_rdf(b'<!DOCTYPE x [<!ENTITY y "boom">]><x>&y;</x>', self.limits)
        too_many = b'<rdf:RDF xmlns:rdf="urn:rdf"><rdf:Description/><rdf:Description/><rdf:Description/></rdf:RDF>'
        with self.assertRaisesRegex(DocumentLimitError, "rdf_record_limit"):
            validate_zotero_rdf(too_many, self.limits)

class MinerUCloudOriginTests(unittest.TestCase):
    def test_origin_pdf_is_bounded_opaque_and_never_extracted(self):
        from dataclasses import replace
        name = '8559ed56-6701-42f4-84f2-6030687dc8e9_origin.pdf'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'input.zip'
            def make(entries):
                with zipfile.ZipFile(archive, 'w') as out:
                    for key, value in entries: out.writestr(key, value)
            make([(name, b'opaque; not parsed'), ('full.md', b'# synthetic'), ('layout.json', b'{}')])
            manifest = preflight_archive(archive, 'mineru_zip')
            self.assertEqual(manifest.ignored, [name])
            extract_validated_archive(archive, root/'output', manifest)
            self.assertFalse((root/'output'/name).exists())
            self.assertEqual({e.path for e in manifest.entries}, {'full.md', 'layout.json'})
            cases = [
                ([('nested/'+name,b'x')], 'archive_type_forbidden', DocumentLimits()),
                ([('arbitrary_origin.pdf',b'x')], 'archive_type_forbidden', DocumentLimits()),
                ([(name,b'x'),('9559ed56-6701-42f4-84f2-6030687dc8e9_origin.pdf',b'x')], 'archive_origin_pdf_limit', DocumentLimits()),
                ([(name,b'123')], 'archive_entry_too_large', replace(DocumentLimits(),max_pdf_bytes=2)),
                ([('layout.json',b'123')], 'archive_entry_too_large', replace(DocumentLimits(),max_json_bytes=2)),
                ([(name,b'123')], 'archive_expanded_limit', replace(DocumentLimits(),max_expanded_bytes=2)),
            ]
            link = zipfile.ZipInfo(name);link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
            cases.append(([(link,b'x')], 'archive_link_forbidden', DocumentLimits()))
            for entries, reason, limits in cases:
                with self.subTest(reason=reason, entries=str(entries)[:80]):
                    make(entries)
                    with self.assertRaisesRegex(DocumentLimitError,reason): preflight_archive(archive,'mineru_zip',limits)


if __name__ == "__main__":
    unittest.main()
