"""
Ketan-OS (केतन — The Beacon of Ground Truth).

The Transactional Intelligence Substrate & Time-Travel Harness for AI Agents.
Brings transactional state snapshotting, causal failure tracing,
pre-flight assertion verification, scope-locked policy enforcement,
epistemic belief contradiction pruning, eBPF-style symbolic invariant micro-patching,
predictive speculative task execution, JIT skill compilation, and sub-second time-travel rollback.
"""

from ketan.core import KetanHarness, Checkpoint, RollbackException, ChronosHarness
from ketan.shadow_fs import KetanShadowFS, ShadowFS, FileState, ShadowSnapshot
from ketan.dual_ledger import KetanLedger, DualLedger, ExecutionTurn
from ketan.verifier import InvariantVerifier, InvariantResult
from ketan.causal_graph import KetanTraceGraph, CausalTraceGraph, CausalNode, CausalEdge, NodeKind, NodeStatus
from ketan.policy import PolicyEngine, Policy, PolicyViolation
from ketan.speculative import SpeculativeExecutor, BranchStrategy, BranchOutcome, SpeculativeResult
from ketan.speculative_kernel import PredictiveSpeculativeKernel, OutcomePredictor
from ketan.symbolic_kernel import SymbolicInvariantKernel, SymbolicRule, MicroPatch
from ketan.epistemic import EpistemicBeliefEngine, BeliefNode, ContradictionEvent
from ketan.jit_compiler import JITCompiler, CompiledSkill, TrajectoryStep
from ketan.persona import PersonaManager, PersonaVault, FrozenPersona, PersonaDiff
from ketan.adapters.generic_llm import KetanAgentWrapper, ChronosAgentWrapper
from ketan.adapters.langgraph import KetanLangGraphMiddleware, ChronosLangGraphMiddleware

__version__ = "2.0.0"
__all__ = [
    # Core Substrate
    "KetanHarness",
    "ChronosHarness",
    "Checkpoint",
    "RollbackException",
    "KetanShadowFS",
    "ShadowFS",
    "KetanLedger",
    "DualLedger",
    "ExecutionTurn",
    "InvariantVerifier",
    "InvariantResult",
    # Causal Execution Trace Graph
    "KetanTraceGraph",
    "CausalTraceGraph",
    "CausalNode",
    "CausalEdge",
    "NodeKind",
    "NodeStatus",
    # Policy Engine
    "PolicyEngine",
    "Policy",
    "PolicyViolation",
    # Predictive Speculative Kernel
    "SpeculativeExecutor",
    "BranchStrategy",
    "BranchOutcome",
    "SpeculativeResult",
    "PredictiveSpeculativeKernel",
    "OutcomePredictor",
    # Symbolic Invariant Kernel
    "SymbolicInvariantKernel",
    "SymbolicRule",
    "MicroPatch",
    # Epistemic Belief Engine
    "EpistemicBeliefEngine",
    "BeliefNode",
    "ContradictionEvent",
    # JIT Compiler
    "JITCompiler",
    "CompiledSkill",
    "TrajectoryStep",
    # Persona Freeze & Fork
    "PersonaManager",
    "PersonaVault",
    "FrozenPersona",
    "PersonaDiff",
    # Adapters
    "KetanAgentWrapper",
    "ChronosAgentWrapper",
    "KetanLangGraphMiddleware",
    "ChronosLangGraphMiddleware",
]
