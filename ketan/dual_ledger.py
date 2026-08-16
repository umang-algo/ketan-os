import time
import threading
from typing import List, Dict, Any, Optional

class ExecutionTurn:
    """Represents a single execution step/turn in Ketan-OS."""
    def __init__(
        self,
        turn_id: str,
        step_number: int,
        prompt_snapshot: List[Dict[str, Any]],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.turn_id = turn_id
        self.step_number = step_number
        self.prompt_snapshot = [dict(msg) for msg in prompt_snapshot]  # Deep copy
        self.tool_calls = tool_calls or []
        self.metadata = metadata or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "step_number": self.step_number,
            "messages_count": len(self.prompt_snapshot),
            "tool_calls": self.tool_calls,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


class Checkpoint:
    """Combines an Environment Snapshot with a Reasoning Prompt Turn in Ketan-OS."""
    def __init__(
        self,
        checkpoint_id: str,
        step_number: int,
        turn: ExecutionTurn,
        fs_snapshot_id: str,
        state_data: Optional[Dict[str, Any]] = None
    ):
        self.checkpoint_id = checkpoint_id
        self.step_number = step_number
        self.turn = turn
        self.fs_snapshot_id = fs_snapshot_id
        self.state_data = state_data or {}
        self.created_at = time.time()

    def __repr__(self):
        return f"<Checkpoint id='{self.checkpoint_id}' step={self.step_number} msgs={len(self.turn.prompt_snapshot)}>"


class KetanLedger:
    """
    Manages dual-ledger state synchronization in Ketan-OS:
    - Ledger A: Environment state & filesystem snapshots
    - Ledger B: LLM conversation prompt stack & turn records
    
    Thread-safe synchronization using internal RLock.
    """
    def __init__(self):
        self.checkpoints: Dict[str, Checkpoint] = {}
        self.history: List[Checkpoint] = []
        self._lock = threading.RLock()

    def record_checkpoint(
        self,
        checkpoint_id: str,
        step_number: int,
        prompt_stack: List[Dict[str, Any]],
        fs_snapshot_id: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        custom_state: Optional[Dict[str, Any]] = None
    ) -> Checkpoint:
        """Records a synchronized checkpoint across both ledgers."""
        with self._lock:
            turn = ExecutionTurn(
                turn_id=f"turn_{checkpoint_id}",
                step_number=step_number,
                prompt_snapshot=prompt_stack,
                tool_calls=tool_calls
            )
            
            cp = Checkpoint(
                checkpoint_id=checkpoint_id,
                step_number=step_number,
                turn=turn,
                fs_snapshot_id=fs_snapshot_id,
                state_data=custom_state
            )
            
            self.checkpoints[checkpoint_id] = cp
            self.history.append(cp)
            return cp

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        with self._lock:
            return self.checkpoints.get(checkpoint_id)

    def truncate_to(self, checkpoint_id: str) -> List[Checkpoint]:
        """
        Truncates history to a target checkpoint (pruning invalid future steps).
        Returns the list of pruned checkpoints.
        """
        with self._lock:
            if checkpoint_id not in self.checkpoints:
                raise KeyError(f"Checkpoint '{checkpoint_id}' not found in KetanLedger.")
                
            target_index = -1
            for i, cp in enumerate(self.history):
                if cp.checkpoint_id == checkpoint_id:
                    target_index = i
                    break
                    
            if target_index == -1:
                return []

            pruned = self.history[target_index + 1:]
            self.history = self.history[:target_index + 1]
            
            for cp in pruned:
                self.checkpoints.pop(cp.checkpoint_id, None)
                
            return pruned

    def latest_checkpoint(self) -> Optional[Checkpoint]:
        with self._lock:
            return self.history[-1] if self.history else None


# Alias for backward compatibility
DualLedger = KetanLedger
