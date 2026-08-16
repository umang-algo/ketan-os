"""Tests for Ketan-OS Durable Write-Ahead Transaction Journal (WAL) and Crash Recovery."""
import unittest
import tempfile
import shutil
from pathlib import Path
from ketan.journal import TransactionJournal, TransactionState
from ketan import KetanHarness


class TestJournalRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ketan_wal_test_")
        self.journal = TransactionJournal(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_wal_record_and_read(self):
        rec1 = self.journal.record_event("tx_101", TransactionState.BEGIN, step=1, payload={"cmd": "write"})
        self.assertEqual(rec1.tx_id, "tx_101")
        self.assertEqual(rec1.state, TransactionState.BEGIN)

        records = self.journal.read_all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tx_id, "tx_101")

    def test_uncommitted_transaction_recovery(self):
        # 1. Transaction 1: Begun and Committed
        self.journal.record_event("tx_clean", TransactionState.BEGIN, step=1)
        self.journal.record_event("tx_clean", TransactionState.COMMIT, step=1)

        # 2. Transaction 2: Begun but CRASHED (no commit/rollback)
        self.journal.record_event("tx_crashed", TransactionState.BEGIN, step=2)

        # Recover uncommitted
        uncommitted = self.journal.recover_uncommitted_transactions()
        self.assertEqual(len(uncommitted), 1)
        self.assertEqual(uncommitted[0], "tx_crashed")

    def test_harness_journal_integration(self):
        harness = KetanHarness(self.tmp_dir)
        cp = harness.create_checkpoint(prompt_stack=[{"role": "user", "content": "test"}])
        
        # Verify WAL journal recorded TX_BEGIN
        recs = harness.journal.read_all_records()
        self.assertTrue(any(r.tx_id == cp.checkpoint_id for r in recs))
        harness.cleanup()


if __name__ == "__main__":
    unittest.main()
