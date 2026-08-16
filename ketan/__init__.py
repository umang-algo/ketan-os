"""
Ketan-OS (केतन — The Beacon of Ground Truth).

The Transactional Runtime for AI Agents.
Brings content-addressed workspace state snapshotting & rollback,
durable WAL journal persistence, sandbox isolation,
multi-layer pre-flight assertion verification, live causal execution trace graph (CTG) lineage,
and epistemic belief contradiction prompt stack pruning.
"""

from ketan.core import KetanHarness, Checkpoint, RollbackException, ChronosHarness
from ketan.shadow_fs import KetanShadowFS, ShadowFS, FileState, ShadowSnapshot
from ketan.dual_ledger import KetanLedger, DualLedger, ExecutionTurn, ReversibilityKind
from ketan.verifier import InvariantVerifier, InvariantResult
from ketan.causal_graph import KetanTraceGraph, CausalTraceGraph, CausalNode, CausalEdge, NodeKind, NodeStatus
from ketan.epistemic import EpistemicBeliefEngine, BeliefNode, ContradictionEvent
from ketan.journal import TransactionJournal, JournalRecord, TransactionState
from ketan.sandboxes import BaseSandboxEngine, LocalProcessSandbox, DockerContainerSandbox
from ketan.compensation import GitCompensationDriver, SQLCompensationDriver
from ketan.adapters.generic_llm import KetanAgentWrapper, ChronosAgentWrapper
from ketan.adapters.langgraph import KetanLangGraphMiddleware, ChronosLangGraphMiddleware

__version__ = "3.0.0"
__all__ = [
    # Core Transactional Substrate
    "KetanHarness",
    "ChronosHarness",
    "Checkpoint",
    "RollbackException",
    "KetanShadowFS",
    "ShadowFS",
    "KetanLedger",
    "DualLedger",
    "ExecutionTurn",
    "ReversibilityKind",

    # Durable WAL Journal
    "TransactionJournal",
    "JournalRecord",
    "TransactionState",

    # Execution Sandboxes
    "BaseSandboxEngine",
    "LocalProcessSandbox",
    "DockerContainerSandbox",

    # System Compensation Drivers
    "GitCompensationDriver",
    "SQLCompensationDriver",

    # Pre-Flight Invariant Verifier
    "InvariantVerifier",
    "InvariantResult",

    # Causal Execution Trace Graph (CTG)
    "KetanTraceGraph",
    "CausalTraceGraph",
    "CausalNode",
    "CausalEdge",
    "NodeKind",
    "NodeStatus",

    # Epistemic Belief Engine
    "EpistemicBeliefEngine",
    "BeliefNode",
    "ContradictionEvent",

    # Framework Adapters & Wrappers
    "KetanAgentWrapper",
    "ChronosAgentWrapper",
    "KetanLangGraphMiddleware",
    "ChronosLangGraphMiddleware",
]
