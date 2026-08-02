"""
Epistemic Belief Engine & Contradiction Pruner for Ketan-OS (केतन).

Prevents epistemic drift and hallucination loops by tracking explicit factual/structural
beliefs. When new tool execution results or file mutations contradict prior beliefs,
the Epistemic Engine automatically prunes invalid prompt lines and triggers counterfactual
state rewinds to verified ground truth.
"""

import time
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple, Any


@dataclass
class BeliefNode:
    """A single factual assertion, code state assumption, or API constraint."""
    belief_id:   str
    subject:     str       # e.g., "file:app.py", "api:v1_auth", "schema:user"
    predicate:   str       # e.g., "contains_function", "valid_syntax", "uses_oauth2"
    object_val:  Any       # e.g., "calculate_tax", True, "bearer"
    confidence:  float = 1.0
    source_step: int = 0
    created_at:  float = field(default_factory=time.time)
    is_valid:    bool = True

    def __repr__(self):
        status = "VALID" if self.is_valid else "PRUNED"
        return f"<BeliefNode [{status}] {self.subject} {self.predicate} {self.object_val}>"


@dataclass
class ContradictionEvent:
    """Occurs when an observation directly refutes a active BeliefNode."""
    belief_id:        str
    subject:          str
    expected_value:   Any
    observed_value:   Any
    refuting_source:  str
    step_number:      int
    timestamp:        float = field(default_factory=time.time)


class EpistemicBeliefEngine:
    """
    Ketan-OS Epistemic Belief Engine (केतन).

    Monitors incoming LLM prompts and tool results for structural/logical assumptions.
    Maintains a temporal belief graph, detects contradictions, and prunes stale memory.
    """

    def __init__(self):
        self.beliefs: Dict[str, BeliefNode] = {}
        self.contradictions: List[ContradictionEvent] = []
        self._belief_counter = 0

    def assert_belief(
        self,
        subject: str,
        predicate: str,
        object_val: Any,
        source_step: int = 0,
        confidence: float = 1.0
    ) -> BeliefNode:
        """Explicitly registers a belief node in the epistemic graph."""
        self._belief_counter += 1
        belief_id = f"b_{self._belief_counter}_{int(time.time()*1000)}"
        node = BeliefNode(
            belief_id=belief_id,
            subject=subject,
            predicate=predicate,
            object_val=object_val,
            confidence=confidence,
            source_step=source_step,
            is_valid=True
        )
        self.beliefs[belief_id] = node
        return node

    def inspect_observation(
        self,
        subject: str,
        predicate: str,
        observed_val: Any,
        step_number: int = 0,
        refuting_source: str = "tool_execution"
    ) -> List[ContradictionEvent]:
        """
        Compares an empirical observation against active beliefs.
        If a contradiction is detected, the belief is marked invalid and a ContradictionEvent is emitted.
        """
        detected_contradictions: List[ContradictionEvent] = []

        for node in list(self.beliefs.values()):
            if not node.is_valid:
                continue

            if node.subject == subject and node.predicate == predicate:
                if node.object_val != observed_val:
                    # Contradiction detected!
                    node.is_valid = False
                    event = ContradictionEvent(
                        belief_id=node.belief_id,
                        subject=subject,
                        expected_value=node.object_val,
                        observed_value=observed_val,
                        refuting_source=refuting_source,
                        step_number=step_number
                    )
                    self.contradictions.append(event)
                    detected_contradictions.append(event)

        return detected_contradictions

    def prune_prompt_stack(
        self,
        prompt_stack: List[Dict[str, Any]],
        contradictions: List[ContradictionEvent]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Scans a prompt stack and prunes/revises messages that contain invalid belief statements.
        Returns (pruned_prompt_stack, list_of_pruned_reasons).
        """
        if not contradictions:
            return prompt_stack, []

        pruned_stack = []
        reasons = []

        for msg in prompt_stack:
            content = str(msg.get("content", ""))
            should_prune = False
            prune_reason = ""

            for c in contradictions:
                # Search for mentions of the contradicted subject in prompt text
                if c.subject in content and str(c.expected_value) in content:
                    should_prune = True
                    prune_reason = f"Pruned stale belief regarding '{c.subject}': expected '{c.expected_value}', but observed '{c.observed_value}'"
                    break

            if should_prune:
                reasons.append(prune_reason)
                # Replace with an explicit epistemic correction hint
                corrected_msg = dict(msg)
                corrected_msg["content"] = f"[EPISTEMIC CORRECTION] {prune_reason}. DO NOT use outdated assumption."
                pruned_stack.append(corrected_msg)
            else:
                pruned_stack.append(msg)

        return pruned_stack, reasons

    def active_beliefs(self) -> List[BeliefNode]:
        return [b for b in self.beliefs.values() if b.is_valid]

    def invalid_beliefs(self) -> List[BeliefNode]:
        return [b for b in self.beliefs.values() if not b.is_valid]

    # ------------------------------------------------------------------
    # MCP / External Adapter Convenience Methods
    # ------------------------------------------------------------------

    def observe(self, node: BeliefNode) -> Optional[ContradictionEvent]:
        """
        Convenience method for MCP adapter: observes a new BeliefNode.
        If the observation contradicts an existing belief, returns the
        ContradictionEvent and marks the prior belief invalid.
        If no contradiction, asserts the new belief.
        """
        events = self.inspect_observation(
            subject=node.subject,
            predicate=node.predicate,
            observed_val=node.object_val,
        )
        if events:
            return events[0]
        # No contradiction — register as a new belief
        self.assert_belief(
            subject=node.subject,
            predicate=node.predicate,
            object_val=node.object_val,
            confidence=node.confidence,
        )
        return None

    def observe_raw(
        self,
        subject: str,
        predicate: str,
        value: Any,
        confidence: float = 1.0,
    ) -> Optional[ContradictionEvent]:
        """
        Shorthand for observe() using plain arguments instead of a BeliefNode.
        """
        node = BeliefNode(
            belief_id="",
            subject=subject,
            predicate=predicate,
            object_val=value,
            confidence=confidence,
        )
        return self.observe(node)
