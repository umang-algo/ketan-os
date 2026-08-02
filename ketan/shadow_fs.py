import os
import shutil
import hashlib
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

class FileState:
    """Represents the cryptographic state of a single file in Ketan-OS."""
    def __init__(self, rel_path: str, abs_path: Path):
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.exists = abs_path.exists()
        self.is_dir = abs_path.is_dir() if self.exists else False
        self.content_hash: Optional[str] = self._compute_hash() if (self.exists and not self.is_dir) else None
        self.mtime: Optional[float] = abs_path.stat().st_mtime if self.exists else None

    def _compute_hash(self) -> str:
        try:
            hasher = hashlib.sha256()
            with open(self.abs_path, 'rb') as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def __repr__(self):
        return f"<FileState rel='{self.rel_path}' exists={self.exists} hash={self.content_hash[:8] if self.content_hash else 'N/A'}>"


class ShadowSnapshot:
    """A point-in-time snapshot of the tracked directory in Ketan-OS."""
    def __init__(self, snapshot_id: str, backup_dir: Path, file_states: Dict[str, FileState]):
        self.snapshot_id = snapshot_id
        self.backup_dir = backup_dir
        self.file_states = file_states
        self.created_at = time.time()

    def get_diff(self, current_states: Dict[str, FileState]) -> Dict[str, str]:
        """Compares this snapshot with current state and categorizes changes."""
        diffs = {}
        all_paths = set(self.file_states.keys()) | set(current_states.keys())
        
        for path in all_paths:
            old_st = self.file_states.get(path)
            new_st = current_states.get(path)
            
            if old_st and not new_st:
                diffs[path] = "DELETED"
            elif not old_st and new_st:
                diffs[path] = "CREATED"
            elif old_st and new_st and old_st.content_hash != new_st.content_hash:
                diffs[path] = "MODIFIED"
                
        return diffs


class KetanShadowFS:
    """
    Sub-second Transactional Shadow Filesystem Overlay for Ketan-OS (केतन).
    Tracks file tree state and allows instant rollback to any historical snapshot.
    """
    def __init__(self, target_dir: str, ignore_patterns: Optional[List[str]] = None, max_snapshots: int = 50):
        self.target_dir = Path(target_dir).resolve()
        if not self.target_dir.exists():
            self.target_dir.mkdir(parents=True, exist_ok=True)
            
        self.ignore_patterns = set(ignore_patterns or [
            ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".DS_Store"
        ])
        
        self.max_snapshots = max_snapshots
        self.storage_dir = Path(tempfile.mkdtemp(prefix="ketan_shadow_"))
        self.snapshots: Dict[str, ShadowSnapshot] = {}

    def _should_ignore(self, path: Path) -> bool:
        for part in path.parts:
            if part in self.ignore_patterns or part.startswith(".ketan") or part.startswith(".chronos"):
                return True
        return False

    def scan_state(self) -> Dict[str, FileState]:
        """Scans the target directory and returns a map of relative paths to FileStates."""
        states = {}
        for root, dirs, files in os.walk(self.target_dir):
            root_path = Path(root)
            
            # Filter directories in-place to avoid traversing ignored folders
            dirs[:] = [d for d in dirs if not self._should_ignore(root_path / d)]
            
            for file_name in files:
                abs_path = root_path / file_name
                if self._should_ignore(abs_path):
                    continue
                rel_path = str(abs_path.relative_to(self.target_dir))
                states[rel_path] = FileState(rel_path, abs_path)
                
        return states

    def create_snapshot(self, snapshot_id: str) -> ShadowSnapshot:
        """Takes a full cryptographic snapshot of the workspace."""
        current_states = self.scan_state()
        snap_backup_dir = self.storage_dir / snapshot_id
        snap_backup_dir.mkdir(parents=True, exist_ok=True)
        
        for rel_path, st in current_states.items():
            if st.exists and not st.is_dir:
                dest = snap_backup_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(st.abs_path, dest)
                
        snapshot = ShadowSnapshot(snapshot_id, snap_backup_dir, current_states)
        self.snapshots[snapshot_id] = snapshot
        
        # Enforce LRU eviction if snapshots exceed maximum allowed capacity
        if len(self.snapshots) > self.max_snapshots:
            oldest_id = min(self.snapshots.keys(), key=lambda k: self.snapshots[k].created_at)
            self.delete_snapshot(oldest_id)
            
        return snapshot

    def rollback_to(self, snapshot_id: str) -> Dict[str, str]:
        """
        Reverts the target workspace back to the exact physical state of snapshot_id.
        Returns a dict summarizing modified, created, and restored files.
        """
        if snapshot_id not in self.snapshots:
            raise KeyError(f"Snapshot '{snapshot_id}' not found in KetanShadowFS ledger.")
            
        target_snap = self.snapshots[snapshot_id]
        current_states = self.scan_state()
        diff = target_snap.get_diff(current_states)
        
        # 1. Remove files created after the snapshot was taken
        for rel_path, status in diff.items():
            if status == "CREATED":
                abs_p = self.target_dir / rel_path
                if abs_p.exists():
                    if abs_p.is_dir():
                        shutil.rmtree(abs_p)
                    else:
                        abs_p.unlink()
                        parent = abs_p.parent
                        while parent != self.target_dir and parent.exists() and not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent

        # 2. Restore modified or deleted files from backup
        for rel_path, status in diff.items():
            if status in ("MODIFIED", "DELETED"):
                backup_file = target_snap.backup_dir / rel_path
                target_file = self.target_dir / rel_path
                
                if backup_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, target_file)
                elif target_file.exists():
                    target_file.unlink()

        return diff

    def delete_snapshot(self, snapshot_id: str):
        """Purges snapshot from disk and memory."""
        if snapshot_id in self.snapshots:
            snap = self.snapshots.pop(snapshot_id)
            if snap.backup_dir.exists():
                shutil.rmtree(snap.backup_dir, ignore_errors=True)

    def cleanup(self):
        """Destroys the shadow storage overlay."""
        if self.storage_dir.exists():
            shutil.rmtree(self.storage_dir, ignore_errors=True)


# Alias for backward compatibility
ShadowFS = KetanShadowFS
