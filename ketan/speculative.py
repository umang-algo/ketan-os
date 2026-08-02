"""
Speculative Parallel Branch Execution for Ketan-OS (केतन).

When agent decision confidence is low, fork the workspace into
2-N isolated branches that run strategies in parallel.
The first branch to pass all invariant checks WINS — others are discarded
with zero side effects on the main workspace.
"""

import os
import shutil
import tempfile
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("KetanSpeculative")


@dataclass
class BranchStrategy:
    """A single speculative branch — one strategy to try in isolation."""
    name: str
    tool_name: str
    tool_args: Dict[str, Any]
    tool_fn: Callable[[Dict[str, Any], str], Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BranchOutcome:
    """Result of one speculative branch execution."""
    branch_name:  str
    success:      bool
    result:       Any
    error:        Optional[str]
    elapsed_ms:   float
    workspace_dir: str

    def __repr__(self):
        status = "WIN" if self.success else "FAIL"
        return f"<BranchOutcome [{status}] '{self.branch_name}' {self.elapsed_ms:.1f}ms>"


@dataclass
class SpeculativeResult:
    """Aggregated result from a speculative parallel execution."""
    winner:          Optional[BranchOutcome]
    all_outcomes:    List[BranchOutcome]
    total_elapsed_ms: float
    merged_to_workspace: bool

    @property
    def succeeded(self) -> bool:
        return self.winner is not None

    def summary(self) -> str:
        if self.winner:
            losers = [o.branch_name for o in self.all_outcomes if not o.success]
            return (
                f"Speculative execution SUCCEEDED — "
                f"Winner: '{self.winner.branch_name}' "
                f"({self.winner.elapsed_ms:.1f}ms) | "
                f"Discarded: {losers} | "
                f"Total: {self.total_elapsed_ms:.1f}ms"
            )
        return (
            f"Speculative execution FAILED — "
            f"All {len(self.all_outcomes)} branches exhausted. "
            f"Workspace unchanged."
        )


class SpeculativeExecutor:
    """
    Forks the workspace into N isolated branches, runs each in parallel,
    and commits the first winning branch back to the main workspace.
    """

    def __init__(
        self,
        main_workspace: str,
        max_workers: int = 4,
        timeout_seconds: float = 30.0,
        causal_graph=None,
        current_step: int = 0,
    ):
        self.main_workspace  = os.path.abspath(main_workspace)
        self.max_workers     = max_workers
        self.timeout_seconds = timeout_seconds
        self.causal_graph    = causal_graph
        self.current_step    = current_step
        self._branch_dirs: List[str] = []

    def run_speculative(
        self,
        strategies: List[BranchStrategy],
        validator: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
    ) -> SpeculativeResult:
        if not strategies:
            raise ValueError("At least one BranchStrategy is required.")

        start = time.time()
        branch_dirs = self._fork_workspaces(len(strategies))
        self._branch_dirs = branch_dirs

        if self.causal_graph:
            self.causal_graph.record_decision(
                label=f"Speculative fork: {len(strategies)} branches",
                step=self.current_step,
                metadata={"branches": [s.name for s in strategies]}
            )

        all_outcomes: List[BranchOutcome] = []
        winner: Optional[BranchOutcome] = None

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(strategies))) as pool:
            future_to_strategy: Dict[Future, Tuple[BranchStrategy, str]] = {
                pool.submit(
                    self._run_branch,
                    strategy,
                    branch_dir,
                    validator
                ): (strategy, branch_dir)
                for strategy, branch_dir in zip(strategies, branch_dirs)
            }

            for future in as_completed(future_to_strategy, timeout=self.timeout_seconds):
                outcome: BranchOutcome = future.result()
                all_outcomes.append(outcome)

                logger.info(f"[Speculative] Branch '{outcome.branch_name}': "
                            f"{'SUCCESS' if outcome.success else 'FAIL'} "
                            f"({outcome.elapsed_ms:.1f}ms)")

                if outcome.success and winner is None:
                    winner = outcome
                    for f in future_to_strategy:
                        if not f.done():
                            f.cancel()

        merged = False
        if winner:
            self._merge_winner(winner.workspace_dir)
            merged = True
            logger.info(f"[Speculative] Merged winner '{winner.branch_name}' → main workspace")

        self._cleanup_branches(branch_dirs)

        total_ms = (time.time() - start) * 1000
        result = SpeculativeResult(
            winner=winner,
            all_outcomes=all_outcomes,
            total_elapsed_ms=total_ms,
            merged_to_workspace=merged
        )

        if self.causal_graph:
            if winner:
                self.causal_graph.record_tool_call(
                    tool_name=winner.branch_name,
                    args={"winner": winner.branch_name, "total_branches": len(strategies)},
                    step=self.current_step
                )
            else:
                self.causal_graph.record_failure(
                    reason="All speculative branches failed",
                    step=self.current_step,
                    hint="Increase branch count or revise strategies"
                )

        logger.info(f"[Speculative] {result.summary()}")
        return result

    def _fork_workspaces(self, n: int) -> List[str]:
        branch_dirs = []
        for i in range(n):
            branch_dir = tempfile.mkdtemp(prefix=f"ketan_branch_{i}_")
            if os.path.isdir(self.main_workspace):
                shutil.copytree(
                    self.main_workspace,
                    os.path.join(branch_dir, "workspace"),
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".ketan_*", ".chronos_*")
                )
            branch_dirs.append(os.path.join(branch_dir, "workspace"))
        return branch_dirs

    def _run_branch(
        self,
        strategy: BranchStrategy,
        branch_dir: str,
        validator: Optional[Callable]
    ) -> BranchOutcome:
        start = time.time()
        try:
            result = strategy.tool_fn(strategy.tool_args, branch_dir)
            if validator:
                passed, error = validator(branch_dir)
                if not passed:
                    elapsed = (time.time() - start) * 1000
                    return BranchOutcome(
                        branch_name=strategy.name,
                        success=False,
                        result=result,
                        error=error or "Validator rejected branch",
                        elapsed_ms=elapsed,
                        workspace_dir=branch_dir
                    )
            elapsed = (time.time() - start) * 1000
            return BranchOutcome(
                branch_name=strategy.name,
                success=True,
                result=result,
                error=None,
                elapsed_ms=elapsed,
                workspace_dir=branch_dir
            )
        except Exception as ex:
            elapsed = (time.time() - start) * 1000
            return BranchOutcome(
                branch_name=strategy.name,
                success=False,
                result=None,
                error=str(ex),
                elapsed_ms=elapsed,
                workspace_dir=branch_dir
            )

    def _merge_winner(self, winner_workspace_dir: str) -> None:
        if not os.path.isdir(winner_workspace_dir):
            return
        for root, dirs, files in os.walk(winner_workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            rel_root = os.path.relpath(root, winner_workspace_dir)
            target_root = os.path.join(self.main_workspace, rel_root)
            os.makedirs(target_root, exist_ok=True)
            for fname in files:
                src = os.path.join(root, fname)
                dst = os.path.join(target_root, fname)
                shutil.copy2(src, dst)

    def _cleanup_branches(self, branch_dirs: List[str]) -> None:
        for branch_dir in branch_dirs:
            parent = os.path.dirname(branch_dir)
            try:
                shutil.rmtree(parent, ignore_errors=True)
            except Exception:
                pass
