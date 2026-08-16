"""Tests for Ketan-OS Compensation Action Engine and Side-Effect Reversibility."""
import unittest
import tempfile
import shutil
from pathlib import Path
from ketan import KetanHarness, ReversibilityKind


class TestCompensationEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_comp_test_")
        self.harness = KetanHarness(self.tmp_dir)
        self.compensated = False

    def tearDown(self):
        self.harness.cleanup()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_compensation_handler_execution(self):
        # Step 1: Initial clean checkpoint
        cp_initial = self.harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "Initial"}])

        # Define mock compensation function for a DB write
        def undo_db_write(args, result):
            self.compensated = True

        self.harness.register_compensation_action("db_write", undo_db_write)

        # Step 2: Compensatable turn
        cp_step2 = self.harness.create_checkpoint(
            prompt_stack=[{"role": "user", "content": "Write DB"}],
            tool_calls=[{"name": "db_write", "args": {"row": 1}}],
            reversibility=ReversibilityKind.COMPENSATABLE
        )

        # Trigger rollback back to initial checkpoint
        prompts = self.harness.rollback(cp_initial.checkpoint_id, "Corrupted DB write", "Revert DB")

        # Verify compensation handler executed
        self.assertTrue(self.compensated)
        system_msg = prompts[-1]["content"]
        self.assertIn("Executed compensation for 'db_write'", system_msg)

    def test_irreversible_warning(self):
        # Step 1: Initial clean checkpoint
        cp_initial = self.harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "Initial"}])

        # Step 2: Irreversible turn (e.g. sending email)
        cp_step2 = self.harness.create_checkpoint(
            prompt_stack=[{"role": "user", "content": "Send Email"}],
            tool_calls=[{"name": "send_email", "args": {"to": "user@test.com"}}],
            reversibility=ReversibilityKind.IRREVERSIBLE
        )

        # Trigger rollback back to initial checkpoint
        prompts = self.harness.rollback(cp_initial.checkpoint_id, "Email sent by mistake", "Revert")
        system_msg = prompts[-1]["content"]
        self.assertIn("Irreversible Actions Warning", system_msg)
        self.assertIn("send_email", system_msg)


if __name__ == "__main__":
    unittest.main()
