import os
import json
import time
import hashlib
import threading
from pathlib import Path
from enum import Enum
from typing import List, Dict, Any, Optional


class LedgerCorruptionError(Exception):
    """Raised when malformed or corrupted records are detected in the persistent ledger log."""
    pass


class LedgerIntegrityError(Exception):
    """Raised when stored state root hash does not match recomputed state root hash."""
    pass


class ReversibilityKind(str, Enum):
    """Classification of tool side-effect reversibility in Ketan-OS transactions."""
    REVERSIBLE    = "REVERSIBLE"     # Local workspace edits, tracked regular files
    COMPENSATABLE = "COMPENSATABLE"  # DB writes or Git commits with explicit undo actions
    IRREVERSIBLE  = "IRREVERSIBLE"   # External network API calls, emails, remote webhooks


class Effect:
    """Represents an explicit side-effect caused by a tool execution in Ketan-OS."""
    def __init__(
        self,
        effect_id: str,
        system: str,          # "filesystem", "git", "database", "github", "network"
        target: str,          # "src/main.py", "orders_table", "user@test.com"
        reversibility: ReversibilityKind = ReversibilityKind.REVERSIBLE,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.effect_id = effect_id
        self.system = system
        self.target = target
        self.reversibility = reversibility
        self.metadata = metadata or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "system": self.system,
            "target": self.target,
            "reversibility": self.reversibility.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Effect":
        eff = cls(
            effect_id=d["effect_id"],
            system=d["system"],
            target=d["target"],
            reversibility=ReversibilityKind(d.get("reversibility", "REVERSIBLE")),
            metadata=d.get("metadata", {})
        )
        if "timestamp" in d:
            eff.timestamp = d["timestamp"]
        return eff


class ExecutionTurn:
    """Represents a single execution step/turn in Ketan-OS."""
    def __init__(
        self,
        turn_id: str,
        step_number: int,
        prompt_snapshot: List[Dict[str, Any]],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        effects: Optional[List[Effect]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reversibility: ReversibilityKind = ReversibilityKind.REVERSIBLE
    ):
        self.turn_id = turn_id
        self.step_number = step_number
        self.prompt_snapshot = [dict(msg) for msg in prompt_snapshot]  # Deep copy
        self.tool_calls = tool_calls or []
        self.effects = effects or []
        self.metadata = metadata or {}
        self.reversibility = reversibility
        self.timestamp = time.time()

    def add_effect(self, effect: Effect):
        self.effects.append(effect)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "step_number": self.step_number,
            "messages_count": len(self.prompt_snapshot),
            "prompt_snapshot": self.prompt_snapshot,
            "tool_calls": self.tool_calls,
            "effects": [e.to_dict() for e in self.effects],
            "reversibility": self.reversibility.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionTurn":
        effects = [Effect.from_dict(e) for e in d.get("effects", [])]
        turn = cls(
            turn_id=d["turn_id"],
            step_number=d["step_number"],
            prompt_snapshot=d.get("prompt_snapshot", []),
            tool_calls=d.get("tool_calls", []),
            effects=effects,
            metadata=d.get("metadata", {}),
            reversibility=ReversibilityKind(d.get("reversibility", "REVERSIBLE"))
        )
        if "timestamp" in d:
            turn.timestamp = d["timestamp"]
        return turn



class Checkpoint:
    """Combines an Environment Snapshot with a Reasoning Prompt Turn in Ketan-OS."""
    def __init__(
        self,
        checkpoint_id: str,
        step_number: int,
        turn: ExecutionTurn,
        fs_snapshot_id: str,
        parent_root_hash: str = "GENESIS",
        state_data: Optional[Dict[str, Any]] = None,
        expected_fs_root_hash: Optional[str] = None
    ):
        self.checkpoint_id = checkpoint_id
        self.step_number = step_number
        self.turn = turn
        self.fs_snapshot_id = fs_snapshot_id
        self.parent_root_hash = parent_root_hash
        self.expected_fs_root_hash = expected_fs_root_hash or ""
        self.state_data = state_data or {}
        self.created_at = time.time()
        self.state_root_hash = self.compute_state_root_hash(parent_root_hash)

    def compute_state_root_hash(self, parent_hash: str = "GENESIS") -> str:
        """Computes a Hash-Chained State Commitment for this checkpoint."""
        hasher = hashlib.sha256()
        hasher.update(parent_hash.encode("utf-8"))
        hasher.update(self.checkpoint_id.encode("utf-8"))
        hasher.update(self.fs_snapshot_id.encode("utf-8"))
        hasher.update(str(self.step_number).encode("utf-8"))
        hasher.update(self.expected_fs_root_hash.encode("utf-8"))
        
        prompt_content = json.dumps(self.turn.prompt_snapshot, sort_keys=True)
        hasher.update(prompt_content.encode("utf-8"))

        effects_content = json.dumps([e.to_dict() for e in self.turn.effects], sort_keys=True)
        hasher.update(effects_content.encode("utf-8"))
        
        return hasher.hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "step_number": self.step_number,
            "turn": self.turn.to_dict(),
            "fs_snapshot_id": self.fs_snapshot_id,
            "parent_root_hash": self.parent_root_hash,
            "expected_fs_root_hash": self.expected_fs_root_hash,
            "state_root_hash": self.state_root_hash,
            "state_data": self.state_data,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Checkpoint":
        turn = ExecutionTurn.from_dict(d["turn"])
        parent_root = d.get("parent_root_hash", "GENESIS")
        cp = cls(
            checkpoint_id=d["checkpoint_id"],
            step_number=d["step_number"],
            turn=turn,
            fs_snapshot_id=d["fs_snapshot_id"],
            parent_root_hash=parent_root,
            state_data=d.get("state_data", {}),
            expected_fs_root_hash=d.get("expected_fs_root_hash", "")
        )
        stored_hash = d.get("state_root_hash", "")
        calculated_hash = cp.compute_state_root_hash(parent_root)
        if stored_hash and stored_hash != calculated_hash:
            raise LedgerIntegrityError(
                f"Ledger Integrity Failure! Checkpoint '{cp.checkpoint_id}' stored hash '{stored_hash[:8]}' "
                f"does not match calculated hash '{calculated_hash[:8]}'."
            )
        cp.created_at = d.get("created_at", cp.created_at)
        return cp

    def __repr__(self):
        return f"<Checkpoint id='{self.checkpoint_id}' step={self.step_number} hash={self.state_root_hash[:8]}>"


class KetanLedger:
    """
    Manages dual-ledger state synchronization in Ketan-OS:
    - Ledger A: Environment state & filesystem snapshots
    - Ledger B: LLM conversation prompt stack & turn records
    
    Persists checkpoints to workspace_root/.ketan/ledger.jsonl via O(1) append-only writes for process restart durability.
    Thread-safe synchronization using internal RLock.
    """
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.checkpoints: Dict[str, Checkpoint] = {}
        self.history: List[Checkpoint] = []
        self._lock = threading.RLock()

        if self.workspace_root:
            self.ketan_dir = self.workspace_root / ".ketan"
            self.ketan_dir.mkdir(parents=True, exist_ok=True)
            self.ledger_file = self.ketan_dir / "ledger.jsonl"
            self._load_from_disk()

    def _load_from_disk(self):
        """Reloads checkpoint history from .ketan/ledger.jsonl on process startup with integrity verification."""
        with self._lock:
            if not hasattr(self, "ledger_file") or not self.ledger_file.exists():
                return
            line_idx = 0
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_idx += 1
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                        cp = Checkpoint.from_dict(data)
                        self.checkpoints[cp.checkpoint_id] = cp
                        self.history.append(cp)
                    except (json.JSONDecodeError, KeyError, LedgerIntegrityError) as ex:
                        raise LedgerCorruptionError(
                            f"Corrupted ledger entry on line {line_idx} in '{self.ledger_file}': {str(ex)}"
                        ) from ex

    def _append_to_disk(self, cp: Checkpoint):
        """Appends a single checkpoint line to ledger.jsonl in O(1) with synchronous fsync."""
        with self._lock:
            if not hasattr(self, "ledger_file"):
                return
            with open(self.ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(cp.to_dict()) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _rewrite_file_after_truncation(self):
        """Rewrites ledger.jsonl only during rollback truncation events."""
        with self._lock:
            if not hasattr(self, "ledger_file"):
                return
            lines = [json.dumps(cp.to_dict()) + "\n" for cp in self.history]
            with open(self.ledger_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
                f.flush()
                os.fsync(f.fileno())

    def record_checkpoint(
        self,
        checkpoint_id: str,
        step_number: int,
        prompt_stack: List[Dict[str, Any]],
        fs_snapshot_id: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        custom_state: Optional[Dict[str, Any]] = None,
        expected_fs_root_hash: Optional[str] = None,
        reversibility: ReversibilityKind = ReversibilityKind.REVERSIBLE,
        effects: Optional[List[Effect]] = None
    ) -> Checkpoint:
        """Records a synchronized checkpoint across both ledgers with hash-chained state root."""
        with self._lock:
            parent_hash = self.history[-1].state_root_hash if self.history else "GENESIS"
            turn = ExecutionTurn(
                turn_id=f"turn_{checkpoint_id}",
                step_number=step_number,
                prompt_snapshot=prompt_stack,
                tool_calls=tool_calls,
                effects=effects or [],
                reversibility=reversibility
            )
            
            cp = Checkpoint(
                checkpoint_id=checkpoint_id,
                step_number=step_number,
                turn=turn,
                fs_snapshot_id=fs_snapshot_id,
                parent_root_hash=parent_hash,
                state_data=custom_state,
                expected_fs_root_hash=expected_fs_root_hash
            )
            
            self.checkpoints[checkpoint_id] = cp
            self.history.append(cp)
            self._append_to_disk(cp)
            return cp


    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        with self._lock:
            if checkpoint_id not in self.checkpoints:
                self._load_from_disk()
            return self.checkpoints.get(checkpoint_id)

    def truncate_to(self, checkpoint_id: str) -> List[Checkpoint]:
        """
        Truncates history to a target checkpoint (pruning invalid future steps).
        Returns the list of pruned checkpoints.
        """
        with self._lock:
            if checkpoint_id not in self.checkpoints:
                self._load_from_disk()
                
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
                
            self._rewrite_file_after_truncation()
            return pruned

    def latest_checkpoint(self) -> Optional[Checkpoint]:
        with self._lock:
            return self.history[-1] if self.history else None


# Alias for backward compatibility
DualLedger = KetanLedger
