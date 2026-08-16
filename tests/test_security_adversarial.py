"""
Dedicated Adversarial Security & Confinement Test Suite for Ketan-OS (केतन).

Tests path traversal attacks, absolute path escapes, symlink boundary escapes,
dangerous subshell command obfuscation, fail-closed Docker sandbox,
parameterized SQL compensation, and WAL crash recovery engine.
"""

import unittest
import tempfile
import shutil
import os
from pathlib import Path
from ketan.verifier import InvariantVerifier
from ketan.sandboxes import LocalExecutionBackend, DockerContainerSandbox
from ketan.journal import TransactionJournal, TransactionState
from ketan.compensation import GitCompensationDriver, SQLCompensationDriver
from ketan import KetanHarness


class TestSecurityAdversarial(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_adv_sec_")
        self.workspace = Path(self.tmp_dir).resolve()
        self.verifier = InvariantVerifier()
        self.sandbox = LocalExecutionBackend(str(self.workspace))

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
        res1 = self.verifier.verify_pre_flight("bash", {"command": "echo 'cm0gLXJmIC8=' | base64 -d | bash"})
        self.assertTrue(any(not r.passed for r in res1))

        res2 = self.verifier.verify_pre_flight("bash", {"command": "rm -rf $HOME"})
        self.assertTrue(any(not r.passed for r in res2))

        res3 = self.verifier.verify_pre_flight("bash", {"command": "dd if=/dev/zero of=/dev/sda"})
        self.assertTrue(any(not r.passed for r in res3))

    def test_docker_unavailable_fails_closed(self):
        docker_sb = DockerContainerSandbox(str(self.workspace))
        docker_sb.docker_available = False

        with self.assertRaises(RuntimeError) as ctx:
            docker_sb.execute_bash("echo 'test'")
        self.assertIn("Fail-Closed", str(ctx.exception))

    def test_sql_parameterized_compensation_sanitization(self):
        # Test identifier sanitization
        with self.assertRaises(ValueError):
            SQLCompensationDriver.create_insert_compensation("users; DROP TABLE users;--", "id", 1, lambda q, p: None)

        executed = []
        def mock_exec(query, params):
            executed.append((query, params))

        handler = SQLCompensationDriver.create_insert_compensation("users", "user_id", "USR_42", mock_exec)
        handler({}, None)
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0][0], "DELETE FROM users WHERE user_id = ?")
        self.assertEqual(executed[0][1], ("USR_42",))

    def test_automated_crash_recovery_engine(self):
        harness = KetanHarness(str(self.workspace))
        cp = harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "Crash test"}])

        # Simulate uncommitted transaction from abrupt process crash
        recovered = harness.recover_pending_transactions()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0], cp.checkpoint_id)
        harness.cleanup()


if __name__ == "__main__":
    unittest.main()
