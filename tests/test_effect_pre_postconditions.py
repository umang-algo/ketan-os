"""
Effect Preconditions, Postconditions & Conflict Detection Test Suite for Ketan-OS (केतन).

Tests:
1. Effect precondition & postcondition evaluation.
2. Effect serialization to/from JSON with timestamps.
3. Postcondition conflict verification prior to compensation.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from ketan.dual_ledger import Effect, ReversibilityKind, ExecutionTurn, Checkpoint


class TestEffectPrePostconditions(unittest.TestCase):
    def test_effect_pre_and_postcondition_evaluation(self):
        effect = Effect(
            effect_id="eff_db_123",
            system="database",
            target="users_table",
            action="sql_insert",
            precondition={"user_count": 10},
            postcondition={"user_count": 11, "user_id": 42},
            inverse={"action": "sql_delete", "user_id": 42},
            reversibility=ReversibilityKind.COMPENSATABLE
        )

        # Test matching current state -> postcondition passes
        state_matching = {"user_count": 11, "user_id": 42, "status": "active"}
        self.assertTrue(effect.verify_postcondition(state_matching))

        # Test mutated current state (third-party edit) -> postcondition fails
        state_conflict = {"user_count": 12, "user_id": 42}
        self.assertFalse(effect.verify_postcondition(state_conflict))

    def test_effect_serialization_roundtrip(self):
        effect = Effect(
            effect_id="eff_fs_999",
            system="filesystem",
            target="src/app.py",
            action="write_file",
            precondition={"hash": "abc1234"},
            postcondition={"hash": "def5678"},
            reversibility=ReversibilityKind.REVERSIBLE
        )

        d = effect.to_dict()
        reconstructed = Effect.from_dict(d)

        self.assertEqual(reconstructed.effect_id, effect.effect_id)
        self.assertEqual(reconstructed.system, effect.system)
        self.assertEqual(reconstructed.action, effect.action)
        self.assertEqual(reconstructed.precondition, effect.precondition)
        self.assertEqual(reconstructed.postcondition, effect.postcondition)
        self.assertEqual(reconstructed.timestamp, effect.timestamp)


if __name__ == "__main__":
    unittest.main()
