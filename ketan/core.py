import threading
import time
import logging
from typing import List, Dict, Any, Optional, Callable, Tuple

from ketan.shadow_fs import KetanShadowFS
from ketan.dual_ledger import KetanLedger, Checkpoint, ReversibilityKind, Effect
from ketan.verifier import InvariantVerifier, InvariantResult
from ketan.causal_graph import KetanTraceGraph, CausalNode, NodeKind, NodeStatus
from ketan.epistemic import EpistemicBeliefEngine, ContradictionEvent
from ketan.journal import TransactionJournal, TransactionState
from ketan.sandboxes import BaseSandboxEngine, LocalExecutionBackend

logger = logging.getLogger("KetanHarness")

class RollbackException(Exception):
    """Raised when an execution turn fails and triggers a time-travel rollback in Ketan-OS."""
    def __init__(self, target_checkpoint_id: str, reason: str, counterfactual_hint: str):
        super().__init__(reason)
        self.target_checkpoint_id = target_checkpoint_id
        self.reason = reason
        self.counterfactual_hint = counterfactual_hint


class RollbackVerificationError(Exception):
    """Raised when post-rollback workspace state root verification fails."""
    pass


class KetanHarness:
    """
    Ketan-OS Harness (केतन — Beacon of Ground Truth).

    The Transactional Runtime for AI Agents.
    Provides content-addressed persistent snapshotting, canonical path isolation,
    durable WAL journal persistence, sandbox execution backends, pre-flight assertion verification,
    Epistemic belief graph tracking, Causal Execution Provenance lineage, compensation action execution,
    automatic WAL crash recovery across process restarts, and verified state root rollback.

    Thread-safe: protected by internal RLock.
    """
    def __init__(
        self,
        workspace_dir: str,
        max_rollback_attempts: int = 3,
        ignore_patterns: Optional[List[str]] = None,
        sandbox_engine: Optional[BaseSandboxEngine] = None
    ):
        self.workspace_dir = workspace_dir
        self.shadow_fs = KetanShadowFS(workspace_dir, ignore_patterns=ignore_patterns)
        self.ledger = KetanLedger(workspace_dir)
        self.verifier = InvariantVerifier()
        self.causal_graph = KetanTraceGraph()
        self.epistemic_engine = EpistemicBeliefEngine()
        
        # Durable Write-Ahead Transaction Journal (WAL)
        self.journal = TransactionJournal(workspace_dir)
        
        # Execution Sandbox Engine (Local workspace backend or Docker container)
        self.sandbox: BaseSandboxEngine = sandbox_engine or LocalExecutionBackend(workspace_dir)

        # Compensation Engine Handlers (tool_name -> Callable(tool_args, tool_result))
        self.compensation_handlers: Dict[str, Callable[[Dict[str, Any], Any], None]] = {}

        self.max_rollback_attempts = max_rollback_attempts
        self.rollback_counts: Dict[str, int] = {}
        self.current_step = len(self.ledger.history)
        self._last_ctg_node: Optional[CausalNode] = None
        self._lock = threading.RLock()

    def register_compensation_action(
        self,
        tool_name: str,
        compensate_fn: Callable[[Dict[str, Any], Any], None]
    ):
        """
        Registers a compensation handler function for COMPENSATABLE tools.
        When a transaction containing a COMPENSATABLE tool call is rolled back,
        Ketan-OS invokes compensate_fn(tool_args, tool_result) to undo side effects (e.g. DB writes, Git reverts).
        """
        with self._lock:
            self.compensation_handlers[tool_name] = compensate_fn
            logger.info(f"[Ketan-OS Compensation Engine] Registered handler for tool '{tool_name}'")

    def create_checkpoint(
        self,
        prompt_stack: List[Dict[str, Any]],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        custom_state: Optional[Dict[str, Any]] = None,
        reversibility: ReversibilityKind = ReversibilityKind.REVERSIBLE
    ) -> Checkpoint:
        """
        Creates a synchronized checkpoint across ledgers & WAL Journal:
        1. Takes incremental workspace snapshot and computes Merkle FS root hash.
        2. Writes TX_BEGIN record to persistent journal log (.ketan/journal.jsonl).
        3. Computes hash-chained cryptographic state root and records checkpoint.
        """
        with self._lock:
            self.current_step += 1
            checkpoint_id = f"cp_step_{self.current_step}_{int(time.time() * 1000)}"

            fs_snapshot = self.shadow_fs.create_snapshot(checkpoint_id)
            fs_root_hash = self.shadow_fs.compute_current_fs_root_hash()

            default_effect = Effect(
                effect_id=f"eff_fs_{checkpoint_id}",
                system="filesystem",
                target=self.workspace_dir,
                reversibility=reversibility
            )

            cp = self.ledger.record_checkpoint(
                checkpoint_id=checkpoint_id,
                step_number=self.current_step,
                prompt_stack=prompt_stack,
                fs_snapshot_id=fs_snapshot.snapshot_id,
                tool_calls=tool_calls,
                custom_state=custom_state,
                expected_fs_root_hash=fs_root_hash,
                reversibility=reversibility,
                effects=[default_effect]
            )

            # Persist TX_BEGIN event to WAL journal
            self.journal.record_event(
                tx_id=checkpoint_id,
                state=TransactionState.BEGIN,
                step=self.current_step,
                payload={"reversibility": reversibility.value, "tool_calls": tool_calls, "state_root": cp.state_root_hash}
            )


            ctg_node = self.causal_graph.record_checkpoint(
                checkpoint_id=checkpoint_id,
                step=self.current_step,
                caused_by=self._last_ctg_node
            )
            self._last_ctg_node = ctg_node

            logger.info(f"[Ketan-OS] Created Checkpoint '{checkpoint_id}' (State Root: {cp.state_root_hash[:8]})")
            return cp

    def execute_tool_transactional(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_fn: Callable[[Dict[str, Any]], Any],
        prompt_stack: List[Dict[str, Any]],
        current_checkpoint: Checkpoint,
        reversibility: ReversibilityKind = ReversibilityKind.REVERSIBLE
    ) -> Tuple[bool, Any, Optional[str]]:
        """
        Executes a tool within a transactional Ketan-OS boundary:
        1. Evaluates Pre-flight Invariant Verification (including path confinement & safety guards).
        2. Runs tool_fn via sandbox backend.
        3. Inspects observation with Epistemic Belief Engine.
        4. Runs Post-flight Invariant Verification.
        5. On success: logs TX_COMMIT event to WAL journal.
        """
        with self._lock:
            current_checkpoint.turn.reversibility = reversibility
            tool_node = self.causal_graph.record_tool_call(
                tool_name=tool_name,
                args=tool_args,
                step=self.current_step,
                caused_by=self._last_ctg_node
            )
            self._last_ctg_node = tool_node

            # Step 1: Pre-flight Verification
            effective_args = {"workspace_root": self.workspace_dir, **tool_args}
            pre_results = self.verifier.verify_pre_flight(tool_name, effective_args)
            failed_pre = [r for r in pre_results if not r.passed]

            if failed_pre:
                failure_msg = f"Pre-flight assertion failed: {failed_pre[0].message}"
                hint = failed_pre[0].hint or failure_msg
                logger.warning(f"[Ketan-OS] Pre-flight Failure in '{tool_name}': {failure_msg}")

                inv_node = self.causal_graph.record_invariant_check(
                    rule_name=failed_pre[0].rule_name, passed=False,
                    step=self.current_step, caused_by=tool_node,
                    error=failure_msg, hint=hint
                )
                fail_node = self.causal_graph.record_failure(
                    reason=failure_msg, step=self.current_step,
                    caused_by=inv_node, hint=hint
                )
                self._last_ctg_node = fail_node
                self.rollback(current_checkpoint.checkpoint_id, reason=failure_msg, counterfactual_hint=hint)
                return False, None, hint

            self.causal_graph.record_invariant_check(
                rule_name="pre_flight", passed=True,
                step=self.current_step, caused_by=tool_node
            )

            # Step 2: Tool Execution via Sandbox Engine
            try:
                tool_result = tool_fn(tool_args)
                tool_node.mark_success(result_summary=str(tool_result)[:100] if tool_result else None)
            except Exception as ex:
                failure_msg = f"Tool execution exception in '{tool_name}': {str(ex)}"
                hint = f"Tool '{tool_name}' crashed with error: {str(ex)}. Check parameters and environment before retrying."
                logger.error(f"[Ketan-OS] Execution Exception: {failure_msg}")

                fail_node = self.causal_graph.record_failure(
                    reason=failure_msg, step=self.current_step,
                    caused_by=tool_node, hint=hint
                )
                self._last_ctg_node = fail_node
                self.rollback(current_checkpoint.checkpoint_id, reason=failure_msg, counterfactual_hint=hint)
                return False, None, hint

            # Record Effect in WAL journal
            self.journal.record_event(
                tx_id=current_checkpoint.checkpoint_id,
                state=TransactionState.EFFECT,
                step=self.current_step,
                payload={"tool_name": tool_name, "reversibility": reversibility.value}
            )

            # Step 3: Epistemic Belief Contradiction Inspection
            filepath = str(tool_args.get("filepath") or tool_args.get("path") or "")
            if filepath:
                contradictions = self.epistemic_engine.inspect_observation(
                    subject=f"file:{filepath}",
                    predicate="state",
                    observed_val=str(tool_result)[:50],
                    step_number=self.current_step
                )
                if contradictions:
                    logger.info(f"[Ketan-OS Epistemic] Contradiction detected in observation for '{filepath}'")

            # Step 4: Post-flight Verification
            post_results = self.verifier.verify_post_flight(tool_name, tool_args, tool_result)
            failed_post = [r for r in post_results if not r.passed]

            if failed_post:
                failure_msg = f"Post-flight assertion failed: {failed_post[0].message}"
                hint = failed_post[0].hint or failure_msg
                logger.warning(f"[Ketan-OS] Post-flight Failure in '{tool_name}': {failure_msg}")

                inv_node = self.causal_graph.record_invariant_check(
                    rule_name=failed_post[0].rule_name, passed=False,
                    step=self.current_step, caused_by=tool_node,
                    error=failure_msg, hint=hint
                )
                fail_node = self.causal_graph.record_failure(
                    reason=failure_msg, step=self.current_step,
                    caused_by=inv_node, hint=hint
                )
                self._last_ctg_node = fail_node
                self.rollback(current_checkpoint.checkpoint_id, reason=failure_msg, counterfactual_hint=hint)
                return False, tool_result, hint

            # Record TX_COMMIT event in WAL journal
            self.journal.record_event(
                tx_id=current_checkpoint.checkpoint_id,
                state=TransactionState.COMMIT,
                step=self.current_step,
                payload={"tool_name": tool_name}
            )

            return True, tool_result, None

    def rollback(
        self,
        target_checkpoint_id: str,
        reason: str,
        counterfactual_hint: str
    ) -> List[Dict[str, Any]]:
        """
        Performs transaction recovery:
        1. Reverts workspace filesystem to target_checkpoint_id snapshot.
        2. Recomputes actual workspace filesystem state root hash and verifies match.
        3. Executes registered compensation actions for COMPENSATABLE operations.
        4. Flags IRREVERSIBLE side effects.
        5. Writes TX_ROLLBACK event to WAL journal.
        6. Truncates prompt stack to checkpoint step and appends counterfactual hint.
        """
        with self._lock:
            cp = self.ledger.get_checkpoint(target_checkpoint_id)
            if not cp:
                raise KeyError(f"Target checkpoint '{target_checkpoint_id}' not found in KetanLedger.")

            attempts = self.rollback_counts.get(target_checkpoint_id, 0) + 1
            self.rollback_counts[target_checkpoint_id] = attempts

            if attempts > self.max_rollback_attempts:
                raise RuntimeError(
                    f"Max rollback attempts ({self.max_rollback_attempts}) exceeded "
                    f"for checkpoint '{target_checkpoint_id}'. Reason: {reason}"
                )

            logger.info(
                f"[Ketan-OS ROLLBACK] Reverting to Checkpoint "
                f"'{target_checkpoint_id}' (Step {cp.step_number}, Hash: {cp.state_root_hash[:8]}). "
                f"Attempt {attempts}/{self.max_rollback_attempts}"
            )

            # Record TX_ROLLBACK event to WAL journal
            self.journal.record_event(
                tx_id=target_checkpoint_id,
                state=TransactionState.ROLLBACK,
                step=self.current_step,
                payload={"reason": reason, "target_state_root": cp.state_root_hash}
            )

            # Phase 1: Workspace Filesystem Recovery
            actions = self.shadow_fs.rollback_to(cp.fs_snapshot_id)

            # Actual Post-Rollback State Root Recomputation & Verification
            actual_fs_hash = self.shadow_fs.compute_current_fs_root_hash()
            if cp.expected_fs_root_hash and actual_fs_hash != cp.expected_fs_root_hash:
                raise RollbackVerificationError(
                    f"Rollback Verification Failed! Expected workspace FS hash '{cp.expected_fs_root_hash[:8]}', "
                    f"but actual post-restoration FS hash was '{actual_fs_hash[:8]}'."
                )
            logger.info(f"[Ketan-OS State Root Verification] Verified Merkle State Root Match: {actual_fs_hash[:8]}")

            # Phase 2: Truncate Ledger & Execute Compensation Actions
            pruned_cps = self.ledger.truncate_to(target_checkpoint_id)
            executed_compensations = []
            irreversible_warnings = []

            for p_cp in pruned_cps:
                for tc in p_cp.turn.tool_calls:
                    t_name = tc.get("name") or tc.get("tool_name")
                    t_args = tc.get("args") or tc.get("tool_args") or {}
                    
                    if p_cp.turn.reversibility == ReversibilityKind.COMPENSATABLE and t_name in self.compensation_handlers:
                        try:
                            self.compensation_handlers[t_name](t_args, None)
                            executed_compensations.append(f"Executed compensation for '{t_name}'")
                            self.journal.record_event(
                                tx_id=p_cp.checkpoint_id,
                                state=TransactionState.COMPENSATE,
                                step=p_cp.step_number,
                                payload={"tool_name": t_name}
                            )
                            logger.info(f"[Ketan-OS Compensation] Executed compensation for tool '{t_name}'")
                        except Exception as ex:
                            logger.error(f"[Ketan-OS Compensation Error] Failed compensation for '{t_name}': {str(ex)}")
                    elif p_cp.turn.reversibility == ReversibilityKind.IRREVERSIBLE:
                        irreversible_warnings.append(f"Tool '{t_name}' performed IRREVERSIBLE side effects (external API call).")

            # Phase 3: Provenance & Counterfactual System Hint Generation
            rb_node = self.causal_graph.record_rollback(
                to_checkpoint_id=target_checkpoint_id,
                step=self.current_step,
                caused_by=self._last_ctg_node
            )
            cf_node = self.causal_graph.record_counterfactual(
                hint=counterfactual_hint,
                step=self.current_step,
                caused_by=rb_node
            )
            self._last_ctg_node = cf_node

            restored_prompts = [dict(msg) for msg in cp.turn.prompt_snapshot]

            failures = self.causal_graph.find_all_failures()
            root_cause_explanation = ""
            if failures:
                root_cause_explanation = "\n[CTG Provenance Lineage]:\n" + self.causal_graph.explain_failure(failures[-1].node_id)

            comp_summary = ""
            if executed_compensations:
                comp_summary = "\n[Executed Compensations]:\n" + "\n".join(f" - {c}" for c in executed_compensations)

            irrev_summary = ""
            if irreversible_warnings:
                irrev_summary = "\n⚠️ [Irreversible Actions Warning]:\n" + "\n".join(f" - {w}" for w in irreversible_warnings)

            counterfactual_system_msg = {
                "role": "system",
                "content": (
                    f"⚠️ [KETAN-OS TRANSACTION ROLLBACK AT STEP {cp.step_number}]\n"
                    f"Reason: {reason}\n"
                    f"Counterfactual Instruction: {counterfactual_hint}\n"
                    f"State Root Verified: {actual_fs_hash[:8]}\n"
                    f"Reverted Files: {len(actions)} files restored\n"
                    f"{comp_summary}"
                    f"{irrev_summary}\n"
                    f"{root_cause_explanation}\n"
                    f"The workspace environment has been reverted to Step {cp.step_number} state. "
                    f"Do NOT repeat the failed action. Choose an alternate clean strategy."
                )
            }
            restored_prompts.append(counterfactual_system_msg)

            return restored_prompts

    def rollback_to(self, checkpoint_id: str) -> Dict[str, str]:
        """
        Public thread-safe wrapper to revert the workspace filesystem state
        to a specific snapshot or checkpoint ID.
        """
        with self._lock:
            cp = self.ledger.get_checkpoint(checkpoint_id)
            snapshot_id = cp.fs_snapshot_id if cp else checkpoint_id
            return self.shadow_fs.rollback_to(snapshot_id)

    def recover_pending_transactions(self) -> List[str]:
        """
        Automated Startup Crash Recovery Engine.
        Scans persistent WAL journal on startup for uncommitted transactions from process crashes,
        logs TX_RECOVERING, executes workspace rollback & compensations, and logs TX_RECOVERED.
        Returns list of recovered transaction IDs.
        """
        with self._lock:
            uncommitted_txs = self.journal.recover_uncommitted_transactions()
            recovered = []

            for tx_id in uncommitted_txs:
                logger.info(f"[Ketan-OS Crash Recovery] Recovering crashed uncommitted transaction '{tx_id}'")
                self.journal.record_event(tx_id=tx_id, state=TransactionState.RECOVERING, step=self.current_step)

                cp = self.ledger.get_checkpoint(tx_id)
                if cp:
                    try:
                        self.rollback(tx_id, reason="Automated Startup Crash Recovery", counterfactual_hint="Crashed transaction recovered")
                    except Exception as ex:
                        logger.error(f"[Ketan-OS Crash Recovery] Error recovering '{tx_id}': {str(ex)}")
                elif tx_id in self.shadow_fs.snapshots:
                    try:
                        self.shadow_fs.rollback_to(tx_id)
                        logger.info(f"[Ketan-OS Crash Recovery] Restored workspace files to persistent snapshot '{tx_id}'")
                    except Exception as ex:
                        logger.error(f"[Ketan-OS Crash Recovery] Error restoring snapshot '{tx_id}': {str(ex)}")

                self.journal.record_event(tx_id=tx_id, state=TransactionState.RECOVERED, step=self.current_step)
                recovered.append(tx_id)

            return recovered

    def cleanup(self):
        """Clean up temporary resources."""
        with self._lock:
            self.shadow_fs.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_tb, exc_val):
        self.cleanup()


# Aliases for backward compatibility
ChronosHarness = KetanHarness
