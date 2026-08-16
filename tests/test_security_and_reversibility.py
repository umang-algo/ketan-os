"""Tests for Security Path Isolation, Symlink Protection, and Reversibility Classification."""
import unittest
import tempfile
import shutil
import os
from pathlib import Path
from ketan.verifier import InvariantVerifier
from ketan.shadow_fs import KetanShadowFS
from ketan.dual_ledger import ReversibilityKind, ExecutionTurn, KetanLedger


class TestSecurityAndReversibility(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_sec_test_")
        self.workspace = Path(self.tmp_dir).resolve()
        self.verifier = InvariantVerifier()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_path_traversal_blocked(self):
        # 1. Attempt writing outside workspace via relative traversal (../../etc/passwd)
        payload_bad = {
            "workspace_root": str(self.workspace),
            "filepath": "../../some_external_file.txt",
            "content": "malicious"
        }
        res = self.verifier.verify_pre_flight("write_file", payload_bad)
        failed = [r for r in res if not r.passed]
        self.assertTrue(len(failed) > 0)
        self.assertIn("Security path traversal violation", failed[0].message)

        # 2. Safe workspace relative file path
        payload_good = {
            "workspace_root": str(self.workspace),
            "filepath": "src/main.py",
            "content": "print('hello')"
        }
        res_good = self.verifier.verify_pre_flight("write_file", payload_good)
        self.assertTrue(all(r.passed for r in res_good))

    def test_symlink_escape_blocked(self):
        # Create external file outside workspace
        ext_dir = tempfile.mkdtemp(prefix="ketan_ext_sec_")
        ext_file = Path(ext_dir) / "sensitive.txt"
        ext_file.write_text("SENSITIVE DATA")

        try:
            # Create symlink inside workspace pointing outside
            symlink_path = self.workspace / "symlink_escape.txt"
            os.symlink(ext_file, symlink_path)

            payload_sym = {
                "workspace_root": str(self.workspace),
                "filepath": "symlink_escape.txt",
                "content": "overwrite attempt"
            }
            res = self.verifier.verify_pre_flight("write_file", payload_sym)
            failed = [r for r in res if not r.passed]
            self.assertTrue(len(failed) > 0)
            self.assertIn("violation", failed[0].message.lower())
        finally:
            shutil.rmtree(ext_dir, ignore_errors=True)

    def test_reversibility_kind_classification(self):
        turn_rev = ExecutionTurn(
            turn_id="turn_1",
            step_number=1,
            prompt_snapshot=[],
            reversibility=ReversibilityKind.REVERSIBLE
        )
        self.assertEqual(turn_rev.reversibility, ReversibilityKind.REVERSIBLE)
        self.assertEqual(turn_rev.to_dict()["reversibility"], "REVERSIBLE")

        turn_irrev = ExecutionTurn(
            turn_id="turn_2",
            step_number=2,
            prompt_snapshot=[],
            reversibility=ReversibilityKind.IRREVERSIBLE
        )
        self.assertEqual(turn_irrev.reversibility, ReversibilityKind.IRREVERSIBLE)
        self.assertEqual(turn_irrev.to_dict()["reversibility"], "IRREVERSIBLE")


if __name__ == "__main__":
    unittest.main()
