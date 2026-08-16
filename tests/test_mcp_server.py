"""Tests for Ketan-OS MCP Server tools and safety features."""
import unittest
import tempfile
import shutil
from pathlib import Path
from ketan.mcp import server as mcp_server
from ketan.epistemic import EpistemicBeliefEngine
from ketan.verifier import InvariantVerifier


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_mcp_test_")
        mcp_server.ketan_init_workspace(self.tmp_dir)

    def tearDown(self):
        if mcp_server._harness is not None:
            mcp_server._harness.cleanup()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init_workspace(self):
        status = mcp_server.ketan_get_status()
        self.assertIn("current_step", status)
        self.assertIn("workspace_dir", status)

    def test_write_file_safe(self):
        res = mcp_server.ketan_write_file_safe("test.txt", "hello world")
        self.assertIn("File written safely", res)
        written_path = Path(self.tmp_dir) / "test.txt"
        self.assertTrue(written_path.exists())
        self.assertEqual(written_path.read_text(), "hello world")

    def test_bash_safe_success_and_failure(self):
        # Successful command
        res_ok = mcp_server.ketan_run_bash_safe("echo 'v1' > out.txt")
        self.assertIn("Command executed safely", res_ok)

        # Create a file before failing command
        Path(self.tmp_dir, "before.txt").write_text("keep")

        # Failing command (exit code 1) should record failure without AttributeError and trigger rollback
        res_fail = mcp_server.ketan_run_bash_safe("echo 'mutated' > mutated.txt && exit 1")
        self.assertIn("Command failed (exit 1)", res_fail)
        self.assertIn("Rolled back", res_fail)

        # Mutated file created during failing command must be rolled back!
        self.assertFalse(Path(self.tmp_dir, "mutated.txt").exists())

    def test_dangerous_command_guard(self):
        verifier = InvariantVerifier()

        # 1. rm -rf /*
        res1 = verifier.verify_pre_flight("bash", {"command": "rm -rf /*"})
        self.assertTrue(any(not r.passed for r in res1))

        # 2. rm -rf $HOME
        res2 = verifier.verify_pre_flight("bash", {"command": "rm  -rf  $HOME"})
        self.assertTrue(any(not r.passed for r in res2))

        # 3. Base64 pipe
        res3 = verifier.verify_pre_flight("bash", {"command": "echo 'cm0gLXJmIC8=' | base64 -d | sh"})
        self.assertTrue(any(not r.passed for r in res3))

        # 4. Safe command
        res_safe = verifier.verify_pre_flight("bash", {"command": "pytest tests/"})
        self.assertTrue(all(r.passed for r in res_safe))

    def test_epistemic_type_coercion(self):
        engine = EpistemicBeliefEngine()
        engine.assert_belief(subject="config:port", predicate="value", object_val=8080)

        # Stringified number should NOT trigger false contradiction
        events = engine.inspect_observation(subject="config:port", predicate="value", observed_val="8080")
        self.assertEqual(len(events), 0)

        # Different value SHOULD trigger contradiction
        events_diff = engine.inspect_observation(subject="config:port", predicate="value", observed_val="9090")
        self.assertEqual(len(events_diff), 1)
