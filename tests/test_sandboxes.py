"""Tests for Ketan-OS Modular Sandbox Engines."""
import unittest
import tempfile
import shutil
from pathlib import Path
from ketan.sandboxes import LocalProcessSandbox, DockerContainerSandbox


class TestSandboxes(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_sb_test_")
        self.sandbox = LocalProcessSandbox(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_local_sandbox_write_and_read(self):
        self.sandbox.write_file("sub/app.py", "x = 10\n")
        content = self.sandbox.read_file("sub/app.py")
        self.assertEqual(content, "x = 10\n")

    def test_local_sandbox_path_confinement(self):
        with self.assertRaises(PermissionError):
            self.sandbox.write_file("../../external.txt", "blocked")

    def test_local_sandbox_bash_execution(self):
        code, out, err = self.sandbox.execute_bash("echo 'hello sandbox'")
        self.assertEqual(code, 0)
        self.assertIn("hello sandbox", out)

    def test_docker_sandbox_fallback(self):
        docker_sb = DockerContainerSandbox(self.tmp_dir)
        code, out, err = docker_sb.execute_bash("echo 'docker test'")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
