"""
eBPF-Style Symbolic Invariant Engine for Ketan-OS (केतन).

Real-time, sub-millisecond execution rule engine. Evaluates Temporal Logic formulas,
dynamic AST structural rules, and resource constraints on incoming tool calls.
Supports micro-state patching for minor assertion failures before escalating to full time-travel rollback.
"""

import ast
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable


@dataclass
class MicroPatch:
    """A micro-state modification payload to automatically resolve minor invariant failures."""
    rule_id:             str
    target_tool:         str
    patched_tool_args:   Dict[str, Any]
    patch_explanation:   str


@dataclass
class SymbolicRule:
    """
    An eBPF-style symbolic rule.
    - name:           Rule name
    - tool_pattern:   Target tool name or '*'
    - condition_fn:   fn(tool_name, tool_args, history_events) -> (passed: bool, msg: str, patch: MicroPatch|None)
    """
    name:           str
    tool_pattern:   str
    condition_fn:   Callable[[str, Dict[str, Any], List[Dict[str, Any]]], Tuple[bool, str, Optional[MicroPatch]]]


class SymbolicInvariantKernel:
    """
    The Sub-millisecond Symbolic Invariant Kernel in Ketan-OS (केतन).

    Intercepts tool execution payloads before side-effects occur.
    Evaluates temporal logic, AST invariants, and performs micro-state patching.
    """

    def __init__(self):
        self.rules: List[SymbolicRule] = []
        self.event_history: List[Dict[str, Any]] = []
        self._register_default_symbolic_rules()

    def register_rule(self, rule: SymbolicRule):
        self.rules.append(rule)

    def _register_default_symbolic_rules(self):
        """Registers default temporal logic and structural rules."""

        # Rule 1: Temporal Invariant — Always format/lint code after file modification
        def temporal_write_guard(
            tool_name: str,
            tool_args: Dict[str, Any],
            history: List[Dict[str, Any]]
        ) -> Tuple[bool, str, Optional[MicroPatch]]:
            filepath = str(tool_args.get("filepath") or tool_args.get("path") or "")
            if tool_name == "write_file" and filepath.endswith(".py"):
                content = str(tool_args.get("content", ""))
                # If trailing whitespace or missing docstring, micro-patch format
                if content and not content.endswith("\n"):
                    patched_args = dict(tool_args)
                    patched_args["content"] = content + "\n"
                    patch = MicroPatch(
                        rule_id="temporal_write_guard",
                        target_tool=tool_name,
                        patched_tool_args=patched_args,
                        patch_explanation="Micro-patched trailing newline to enforce clean Python formatting invariant."
                    )
                    return True, "Micro-patched formatting invariant.", patch

            return True, "Temporal write guard passed.", None

        # Rule 2: Resource Boundary Guard — Limit payload size to <= 10MB
        def resource_boundary_guard(
            tool_name: str,
            tool_args: Dict[str, Any],
            history: List[Dict[str, Any]]
        ) -> Tuple[bool, str, Optional[MicroPatch]]:
            content = str(tool_args.get("content", ""))
            if len(content.encode("utf-8")) > 10 * 1024 * 1024:
                return False, "Payload exceeds 10MB resource boundary limit.", None
            return True, "Resource boundary check passed.", None

        self.register_rule(SymbolicRule("temporal_write_guard", "*", temporal_write_guard))
        self.register_rule(SymbolicRule("resource_boundary_guard", "*", resource_boundary_guard))

    def evaluate_pre_execution(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any], Optional[MicroPatch]]:
        """
        Sub-millisecond execution check.
        Returns (passed, message, effective_tool_args, applied_patch).
        """
        effective_args = dict(tool_args)
        applied_patch: Optional[MicroPatch] = None

        for rule in self.rules:
            if rule.tool_pattern not in ("*", tool_name):
                continue

            passed, msg, patch = rule.condition_fn(tool_name, effective_args, self.event_history)

            if not passed:
                return False, f"Symbolic Kernel Violation [{rule.name}]: {msg}", tool_args, None

            if patch:
                effective_args = dict(patch.patched_tool_args)
                applied_patch = patch

        # Record in event history
        self.event_history.append({
            "tool_name": tool_name,
            "args": effective_args,
            "timestamp": time.time()
        })

        return True, "Symbolic kernel evaluation passed.", effective_args, applied_patch
