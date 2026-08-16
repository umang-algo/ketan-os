"""
Ketan-OS (केतन — The Beacon of Ground Truth).

The Transactional Intelligence Substrate & Time-Travel Harness for AI Agents.
Brings sub-second content-addressed state snapshotting & atomic rollback,
multi-layer pre-flight assertion verification, live causal execution trace graph (CTG) lineage,
and epistemic belief contradiction prompt stack pruning.
"""

from ketan.core import KetanHarness, Checkpoint, RollbackException, ChronosHarness
from ketan.shadow_fs import KetanShadowFS, ShadowFS, FileState, ShadowSnapshot
from ketan.dual_ledger import KetanLedger, DualLedger, ExecutionTurn
from ketan.verifier import InvariantVerifier, InvariantResult
from ketan.causal_graph import KetanTraceGraph, CausalTraceGraph, CausalNode, CausalEdge, NodeKind, NodeStatus
from ketan.epistemic import EpistemicBeliefEngine, BeliefNode, ContradictionEvent
from ketan.adapters.generic_llm import KetanAgentWrapper, ChronosAgentWrapper
from ketan.adapters.langgraph import KetanLangGraphMiddleware, ChronosLangGraphMiddleware

__version__ = "2.0.0"
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
