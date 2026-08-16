"""
Process Crash Durability & Multi-Process Recovery Test Suite for Ketan-OS (केतन).

Tests true crash durability across process restarts:
1. Instantiate Harness 1, take checkpoint, mutate workspace.
2. Abruptly kill/del Harness 1 (simulating process termination / SIGKILL).
3. Instantiate Harness 2 in new process context.
4. Run h2.recover_pending_transactions() and verify workspace state restoration.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from ketan import KetanHarness
from ketan.journal import TransactionJournal, TransactionState


class TestProcessCrashDurability(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_crash_test_")
        self.workspace = Path(self.tmp_dir).resolve()
        
        # Initial file state
        (self.workspace / "main.py").write_text("def run(): return 42\n")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_process_restart_crash_recovery(self):
        # PROCESS 1 Context
        h1 = KetanHarness(str(self.workspace))
        cp1 = h1.create_checkpoint(prompt_stack=[{"role": "user", "content": "Initial code"}])
        
        # Mutate workspace (simulating crashed turn)
        (self.workspace / "main.py").write_text("MUTATED_CORRUPTED_CODE")
        
        # Abrupt process crash (delete h1 without clean exit)
        h1_workspace_dir = h1.workspace_dir
        del h1

        # PROCESS 2 Context (New Process Instance reading persistent .ketan/ storage)
        h2 = KetanHarness(h1_workspace_dir)
        
        # Recover uncommitted transactions
        recovered_txs = h2.recover_pending_transactions()
        self.assertEqual(len(recovered_txs), 1)
        self.assertEqual(recovered_txs[0], cp1.checkpoint_id)

        # Verify main.py content restored from persistent .ketan/ snapshots
        restored_content = (self.workspace / "main.py").read_text()
        self.assertEqual(restored_content, "def run(): return 42\n")

        h2.cleanup()


if __name__ == "__main__":
    unittest.main()
