from typing import Callable, Dict, Any, List
from ketan.core import KetanHarness

class KetanLangGraphMiddleware:
    """
    Middleware adapter for integrating Ketan-OS Time-Travel Rollback with LangGraph state nodes.
    """
    def __init__(self, harness: KetanHarness):
        self.harness = harness

    def wrap_node(self, node_name: str, node_fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """Wraps a LangGraph node function with transactional Ketan-OS rollback protection."""
        def transactional_node_executor(state: Dict[str, Any]) -> Dict[str, Any]:
            messages = state.get("messages", [])
            prompt_stack = []
            for msg in messages:
                if isinstance(msg, dict):
                    prompt_stack.append(msg)
                elif hasattr(msg, "content"):
                    prompt_stack.append({"role": getattr(msg, "type", "user"), "content": msg.content})

            cp = self.harness.create_checkpoint(prompt_stack=prompt_stack)

            try:
                new_state = node_fn(state)
                return new_state
            except Exception as ex:
                failure_reason = f"LangGraph node '{node_name}' crashed: {str(ex)}"
                counterfactual_hint = f"Node '{node_name}' failed with error: {str(ex)}. Choose an alternate branch."
                
                restored_prompts = self.harness.rollback(
                    target_checkpoint_id=cp.checkpoint_id,
                    reason=failure_reason,
                    counterfactual_hint=counterfactual_hint
                )
                
                state_copy = dict(state)
                state_copy["messages"] = restored_prompts
                state_copy["ketan_rollback_occurred"] = True
                state_copy["ketan_hint"] = counterfactual_hint
                state_copy["chronos_rollback_occurred"] = True
                state_copy["chronos_hint"] = counterfactual_hint
                return state_copy

        return transactional_node_executor


# Alias for backward compatibility
ChronosLangGraphMiddleware = KetanLangGraphMiddleware
