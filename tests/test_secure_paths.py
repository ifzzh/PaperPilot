import tempfile
import unittest
from pathlib import Path

from paperpilot.security.paths import (
    PathSecurityError,
    category_directory,
    category_storage_id,
    ensure_confined,
    paper_path,
    safe_join,
    verified_paper_path,
    validate_filename,
)


class TestSecurePaths(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.root = self.base / "papers"
        self.root.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_accepts_regular_file_inside_root(self):
        nested = self.root / "category" / "paper.pdf"
        nested.parent.mkdir()
        nested.write_bytes(b"pdf")
        self.assertEqual(
            ensure_confined(self.root, nested, must_exist=True, require_file=True),
            nested.resolve(),
        )

    def test_accepts_missing_destination_with_safe_parent(self):
        destination = self.root / "category" / "new.pdf"
        destination.parent.mkdir()
        self.assertEqual(ensure_confined(self.root, destination), destination)

    def test_rejects_parent_traversal_and_adjacent_prefix(self):
        with self.assertRaises(PathSecurityError):
            safe_join(self.root, "..", "outside.pdf")
        adjacent = self.base / "papers-copy" / "outside.pdf"
        adjacent.parent.mkdir()
        adjacent.write_bytes(b"outside")
        with self.assertRaises(PathSecurityError):
            ensure_confined(self.root, adjacent, must_exist=True)

    def test_rejects_symlink_to_inside_outside_and_broken_targets(self):
        inside = self.root / "inside.pdf"
        inside.write_bytes(b"inside")
        outside = self.base / "outside.pdf"
        outside.write_bytes(b"outside")
        for name, target in (
            ("inside-link.pdf", inside),
            ("outside-link.pdf", outside),
            ("broken-link.pdf", self.base / "missing.pdf"),
        ):
            link = self.root / name
            link.symlink_to(target)
            with self.subTest(name=name), self.assertRaises(PathSecurityError):
                ensure_confined(self.root, link)

    def test_rejects_symlinked_parent_directory(self):
        real_dir = self.root / "real"
        real_dir.mkdir()
        link_dir = self.root / "linked"
        link_dir.symlink_to(real_dir, target_is_directory=True)
        with self.assertRaises(PathSecurityError):
            ensure_confined(self.root, link_dir / "paper.pdf")

    def test_rejects_root_and_non_regular_files(self):
        with self.assertRaises(PathSecurityError):
            ensure_confined(self.root, self.root)
        directory = self.root / "directory"
        directory.mkdir()
        with self.assertRaises(PathSecurityError):
            ensure_confined(self.root, directory, must_exist=True, require_file=True)

    def test_validates_single_filename_component(self):
        self.assertEqual(validate_filename("paper.pdf"), "paper.pdf")
        invalid_names = (
            "",
            ".",
            "..",
            "../paper.pdf",
            "/tmp/paper.pdf",
            "a/b.pdf",
            "a\\b.pdf",
            "bad\x00.pdf",
        )
        for value in invalid_names:
            with self.subTest(value=value), self.assertRaises(PathSecurityError):
                validate_filename(value)

    def test_category_storage_id_is_deterministic_and_path_safe(self):
        first = category_storage_id("category-id")
        self.assertEqual(first, category_storage_id("category-id"))
        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first, category_storage_id("other-category"))

    def test_category_directory_does_not_depend_on_display_hierarchy(self):
        expected = self.root / ".categories" / category_storage_id("category-id")
        self.assertEqual(category_directory(self.root, "category-id"), expected)

    def test_paper_path_uses_category_id_and_reserved_reading_list(self):
        regular = paper_path(self.root, "category-id", "paper.pdf")
        temporary = paper_path(self.root, "reading_list_temp", "paper.pdf")
        self.assertEqual(
            regular.parent,
            self.root / ".categories" / category_storage_id("category-id"),
        )
        self.assertEqual(temporary.parent, self.root / "_ReadingListTemp")

    def test_stored_path_must_match_server_derived_path(self):
        expected = paper_path(
            self.root,
            "category-id",
            "paper.pdf",
            create_parent=True,
        )
        expected.write_bytes(b"pdf")
        self.assertEqual(
            verified_paper_path(
                self.root,
                "category-id",
                "paper.pdf",
                str(expected),
            ),
            expected,
        )
        other = self.root / "other.pdf"
        other.write_bytes(b"other")
        with self.assertRaises(PathSecurityError):
            verified_paper_path(
                self.root,
                "category-id",
                "paper.pdf",
                str(other),
            )


if __name__ == "__main__":
    unittest.main()
