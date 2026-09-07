import unittest

from paperpilot.core.base_paper import Paper, PaperUpdateError


class TestPaperMutationPolicy(unittest.TestCase):
    def test_allows_documented_user_editable_fields(self):
        paper = Paper(title="Old", starred=False, file_path="/safe/paper.pdf")
        paper.update_user_fields(
            {
                "title": "New",
                "authors": "Ada",
                "affiliation": "Lab",
                "year": "2026",
                "journal": "Venue",
                "abstract": "Abstract",
                "notes": "Notes",
                "starred": True,
                "github": "example/repo",
                "homepage": "example.test",
            }
        )
        self.assertEqual(paper.title, "New")
        self.assertTrue(paper.starred)
        self.assertEqual(paper.file_path, "/safe/paper.pdf")

    def test_rejects_internal_and_unknown_fields_atomically(self):
        paper = Paper(title="Original", file_path="/safe/paper.pdf")
        with self.assertRaises(PaperUpdateError) as captured:
            paper.update_user_fields(
                {
                    "title": "Changed",
                    "file_path": "/etc/passwd",
                    "thumbnail_path": "/etc/shadow",
                }
            )
        self.assertEqual(
            captured.exception.fields,
            ("file_path", "thumbnail_path"),
        )
        self.assertEqual(paper.title, "Original")
        self.assertEqual(paper.file_path, "/safe/paper.pdf")

    def test_requires_an_object_and_boolean_starred(self):
        paper = Paper()
        with self.assertRaises(PaperUpdateError):
            paper.update_user_fields({"starred": "true"})
        with self.assertRaises(PaperUpdateError):
            paper.update_user_fields(None)


if __name__ == "__main__":
    unittest.main()
