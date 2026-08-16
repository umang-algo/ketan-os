"""
Durable Write-Ahead Transaction Journal (WAL) for Ketan-OS (केतन).

Persists transaction events (TX_BEGIN, TX_EFFECT, TX_VERIFY, TX_COMMIT, TX_ROLLBACK, TX_COMPENSATE)
to disk synchronously (.ketan/journal.jsonl) so that transactions survive process termination,
SIGKILL, or machine crashes.
"""

import os
import json
import time
import threading
from pathlib import Path
from enum import Enum
from typing import Dict, List, Any, Optional


class TransactionState(str, Enum):
    BEGIN       = "TX_BEGIN"
    EFFECT      = "TX_EFFECT"
    VERIFY      = "TX_VERIFY"
    COMMIT      = "TX_COMMIT"
    ROLLBACK    = "TX_ROLLBACK"
    COMPENSATE  = "TX_COMPENSATE"


class JournalRecord:
    """A single persistent transaction record in Ketan-OS WAL."""
    def __init__(
        self,
        tx_id: str,
        state: TransactionState,
        step: int,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None
    ):
        self.tx_id = tx_id
        self.state = state
        self.step = step
        self.payload = payload or {}
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "state": self.state.value,
            "step": self.step,
            "payload": self.payload,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "JournalRecord":
        return cls(
            tx_id=d["tx_id"],
            state=TransactionState(d["state"]),
            step=d.get("step", 0),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", time.time())
        )


class TransactionJournal:
    """
    Synchronous Write-Ahead Journal (WAL) for Ketan-OS transactions.

    Appends JSONL records to workspace_root/.ketan/journal.jsonl.
    Flushes and fsyncs every event to guarantee durability against process crashes.
    Thread-safe protected by RLock.
    """
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.ketan_dir = self.workspace_root / ".ketan"
        self.ketan_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.ketan_dir / "journal.jsonl"
        self._lock = threading.RLock()

    def record_event(
        self,
        tx_id: str,
        state: TransactionState,
        step: int,
        payload: Optional[Dict[str, Any]] = None
    ) -> JournalRecord:
        """Appends a transaction event to disk synchronously."""
        with self._lock:
            rec = JournalRecord(tx_id=tx_id, state=state, step=step, payload=payload)
            line = json.dumps(rec.to_dict()) + "\n"
            
            with open(self.journal_file, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
                
            return rec

    def read_all_records(self) -> List[JournalRecord]:
        """Reads all historical WAL records from disk."""
        with self._lock:
            if not self.journal_file.exists():
                return []
            
            records = []
            with open(self.journal_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                        records.append(JournalRecord.from_dict(data))
                    except Exception:
                        continue
            return records

    def recover_uncommitted_transactions(self) -> List[str]:
        """
        Scans journal records on startup to find transactions that were begun
        but neither committed nor rolled back (indicating a process crash).
        Returns list of uncommitted transaction IDs.
        """
        with self._lock:
            records = self.read_all_records()
            tx_states: Dict[str, str] = {}
            
            for rec in records:
                if rec.state == TransactionState.BEGIN:
                    tx_states[rec.tx_id] = "PENDING"
                elif rec.state in (TransactionState.COMMIT, TransactionState.ROLLBACK):
                    tx_states[rec.tx_id] = rec.state.value
                    
            uncommitted = [tx_id for tx_id, status in tx_states.items() if status == "PENDING"]
            return uncommitted
