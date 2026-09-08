import datetime as dt
import json
import re
import unittest
from pathlib import Path


class SecurityScanContractTests(unittest.TestCase):
    def test_tools_and_actions_are_immutably_pinned(self):
        script = Path("scripts/security_scan.sh").read_text(encoding="utf-8")
        self.assertIn("pip-audit==2.10.1", script)
        self.assertIn("trivy_version=0.74.0", script)
        self.assertRegex(script, r"trivy_sha256=[0-9a-f]{64}")

        workflow = Path(".github/workflows/security.yml").read_text(encoding="utf-8")
        action_refs = re.findall(r"uses: [^@\s]+@([^\s]+)", workflow)
        self.assertTrue(action_refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs))

    def test_exceptions_are_specific_and_unexpired(self):
        entries = json.loads(
            Path("security/vulnerability-exceptions.json").read_text(encoding="utf-8")
        )["exceptions"]
        self.assertTrue(entries)
        for entry in entries:
            self.assertNotIn("*", entry["id"])
            self.assertNotIn("*", entry["package"])
            self.assertGreaterEqual(dt.date.fromisoformat(entry["expires"]), dt.date.today())
            self.assertTrue(entry["targets"])
            self.assertTrue(entry["rationale"].strip())


if __name__ == "__main__":
    unittest.main()
