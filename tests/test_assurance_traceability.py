"""Check evidence links and stable identifiers without claiming validation."""

import ast
import csv
from pathlib import Path
import re
import unittest


class TraceabilityTests(unittest.TestCase):
    def test_requirements_matrix_and_test_references_are_consistent(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs/safety_requirements.md").read_text(encoding="utf-8")
        requirements = re.findall(r"^## (SRQ\d{3})$", text, flags=re.MULTILINE)
        with (root / "docs/traceability_matrix.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, [
                "requirement_id", "source", "rationale", "implementation",
                "validation_evidence", "verification_evidence", "test_ids", "status",
            ])
            rows = list(reader)
        self.assertEqual([row["requirement_id"] for row in rows], requirements)
        self.assertEqual(len(set(requirements)), len(requirements))
        tests = set()
        for path in (root / "tests").glob("test_*.py"):
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef):
                    tests.update(f"{path.stem}.{node.name}.{method.name}"
                                 for method in node.body if isinstance(method, ast.FunctionDef)
                                 and method.name.startswith("test_"))
        for row in rows:
            with self.subTest(requirement=row["requirement_id"]):
                self.assertIn(row["status"], {"verified", "partial", "planned"})
                section = text.split(f'## {row["requirement_id"]}\n', 1)[1].split("\n## ", 1)[0]
                self.assertIn(f'- status: {row["status"]}', section)
                if row["status"] == "verified":
                    self.assertTrue(row["implementation"])
                    self.assertTrue(row["verification_evidence"])
                    self.assertTrue(row["test_ids"])
                for test in filter(None, row["test_ids"].split("; ")):
                    self.assertIn(test, tests)
        hazards = (root / "docs/hazard_log.md").read_text(encoding="utf-8")
        self.assertTrue(set(re.findall(r"SRQ\d{3}", hazards)) <= set(requirements))
