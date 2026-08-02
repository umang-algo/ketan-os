import tempfile
import unittest
from pathlib import Path

from ketan import (
    KetanHarness,
    EpistemicBeliefEngine,
    PredictiveSpeculativeKernel,
    SymbolicInvariantKernel,
    SymbolicRule,
    MicroPatch,
    BranchStrategy,
)


class TestKetanFrontier(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_ketan_frontier_")
        self.harness = KetanHarness(self.temp_dir)
        self.test_file = Path(self.temp_dir) / "app.py"
        self.test_file.write_text("# Ketan-OS Initial Code\ndef main():\n    return 42\n")

    def tearDown(self):
        self.harness.cleanup()

    def test_ketan_harness_transactional_execution(self):
        prompt_stack = [{"role": "user", "content": "Update main function"}]
        cp = self.harness.create_checkpoint(prompt_stack=prompt_stack)

        def write_fn(args):
            p = Path(self.temp_dir) / args["filepath"]
            p.write_text(args["content"])
            return "written"

        # Valid write
        success, result, hint = self.harness.execute_tool_transactional(
            tool_name="write_file",
            tool_args={"filepath": "app.py", "content": "def main():\n    return 100\n"},
            tool_fn=write_fn,
            prompt_stack=prompt_stack,
            current_checkpoint=cp
        )
        self.assertTrue(success)
        self.assertEqual(result, "written")
        self.assertIn("100", self.test_file.read_text())

    def test_epistemic_belief_engine_contradiction_and_pruning(self):
        engine = EpistemicBeliefEngine()

        # Assert initial belief
        engine.assert_belief(
            subject="file:app.py",
            predicate="state",
            object_val="v1_clean",
            source_step=1
        )
        self.assertEqual(len(engine.active_beliefs()), 1)

        # Inspect contradictory observation
        contradictions = engine.inspect_observation(
            subject="file:app.py",
            predicate="state",
            observed_val="v2_corrupted",
            step_number=2
        )

        self.assertEqual(len(contradictions), 1)
        self.assertEqual(len(engine.active_beliefs()), 0)
        self.assertEqual(len(engine.invalid_beliefs()), 1)

        # Prune prompt stack
        prompt_stack = [
            {"role": "user", "content": "Working on file:app.py assuming state v1_clean is present"}
        ]
        pruned_stack, reasons = engine.prune_prompt_stack(prompt_stack, contradictions)

        self.assertEqual(len(reasons), 1)
        self.assertIn("[EPISTEMIC CORRECTION]", pruned_stack[0]["content"])

    def test_symbolic_kernel_micro_patching(self):
        kernel = SymbolicInvariantKernel()

        # Test formatting micro-patching rule (adds missing trailing newline)
        tool_args = {"filepath": "script.py", "content": "print('hello')"}
        passed, msg, effective_args, patch = kernel.evaluate_pre_execution("write_file", tool_args)

        self.assertTrue(passed)
        self.assertIsNotNone(patch)
        self.assertTrue(effective_args["content"].endswith("\n"))

    def test_predictive_speculative_kernel(self):
        kernel = PredictiveSpeculativeKernel(self.temp_dir)

        def strategy_a(args, ws_dir):
            p = Path(ws_dir) / "output.txt"
            p.write_text("strategy_a")
            return "done_a"

        def strategy_b(args, ws_dir):
            p = Path(ws_dir) / "output.txt"
            p.write_text("strategy_b")
            return "done_b"

        strategies = [
            BranchStrategy("strat_a", "write_file", {}, strategy_a),
            BranchStrategy("strat_b", "write_file", {}, strategy_b),
        ]

        result = kernel.execute_predictive("write_file", {}, strategies)

        self.assertTrue(result.succeeded)
        self.assertIsNotNone(result.winner)
        self.assertIn(result.winner.branch_name, ["strat_a", "strat_b"])


if __name__ == "__main__":
    unittest.main()
