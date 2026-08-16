"""
Dedicated Adversarial Security & Confinement Test Suite for Ketan-OS (केतन).

Tests path traversal attacks, absolute path escapes, symlink boundary escapes,
dangerous subshell command obfuscation, and WAL crash recovery integrity.
"""

import unittest
import tempfile
import shutil
import os
from pathlib import Path
from ketan.verifier import InvariantVerifier
from ketan.sandboxes import LocalProcessSandbox
from ketan.journal import TransactionJournal, TransactionState


class TestSecurityAdversarial(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_adv_sec_")
        self.workspace = Path(self.tmp_dir).resolve()
        self.verifier = InvariantVerifier()
        self.sandbox = LocalProcessSandbox(str(self.workspace))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_path_traversal_relative_escape_blocked(self):
        payload = {
            "workspace_root": str(self.workspace),
            "filepath": "../../../etc/passwd",
            "content": "root:x:0:0:root:/root:/bin/bash"
        }
        res = self.verifier.verify_pre_flight("write_file", payload)
        failed = [r for r in res if not r.passed]
        self.assertTrue(len(failed) > 0)
        self.assertIn("path traversal violation", failed[0].message.lower())

    def test_absolute_path_escape_blocked(self):
        payload = {
            "workspace_root": str(self.workspace),
            "filepath": "/etc/passwd",
            "content": "malicious"
        }
        res = self.verifier.verify_pre_flight("write_file", payload)
        failed = [r for r in res if not r.passed]
        self.assertTrue(len(failed) > 0)
        self.assertIn("path traversal violation", failed[0].message.lower())

    def test_sandbox_direct_write_confinement(self):
        with self.assertRaises(PermissionError):
            self.sandbox.write_file("../../outside.txt", "blocked content")

    def test_symlink_escape_blocked(self):
        ext_dir = tempfile.mkdtemp(prefix="ketan_ext_sec_")
        ext_file = Path(ext_dir) / "sensitive_config.json"
        ext_file.write_text('{"secret": "12345"}')

        try:
            symlink_in_ws = self.workspace / "config_link.json"
            os.symlink(ext_file, symlink_in_ws)

            payload = {
                "workspace_root": str(self.workspace),
                "filepath": "config_link.json",
                "content": "overwritten"
            }
            res = self.verifier.verify_pre_flight("write_file", payload)
            failed = [r for r in res if not r.passed]
            self.assertTrue(len(failed) > 0)
            self.assertIn("violation", failed[0].message.lower())
        finally:
            shutil.rmtree(ext_dir, ignore_errors=True)

    def test_dangerous_subshell_commands_blocked(self):
        # 1. Base64 pipe to shell
        res1 = self.verifier.verify_pre_flight("bash", {"command": "echo 'cm0gLXJmIC8=' | base64 -d | bash"})
        self.assertTrue(any(not r.passed for r in res1))

        # 2. Destructive rm -rf $HOME
        res2 = self.verifier.verify_pre_flight("bash", {"command": "rm -rf $HOME"})
        self.assertTrue(any(not r.passed for r in res2))

        # 3. Disk wipe dd
        res3 = self.verifier.verify_pre_flight("bash", {"command": "dd if=/dev/zero of=/dev/sda"})
        self.assertTrue(any(not r.passed for r in res3))

    def test_wal_journal_durability_across_crashes(self):
        journal1 = TransactionJournal(str(self.workspace))
        journal1.record_event("tx_99", TransactionState.BEGIN, step=1, payload={"op": "insert"})

        # Simulate abrupt process restart by creating new journal instance reading existing file
        journal2 = TransactionJournal(str(self.workspace))
        uncommitted = journal2.recover_uncommitted_transactions()
        self.assertIn("tx_99", uncommitted)


if __name__ == "__main__":
    unittest.main()
