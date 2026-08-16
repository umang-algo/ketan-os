import os
import shutil
import hashlib
import tempfile
import time
import atexit
import threading
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
    Tracks file tree state and allows instant rollback to any historical snapshot
    using content-addressed deduplicated blob storage.
    
    Thread-safe and automatically cleans up temporary directories on termination.
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
        self.blob_dir = self.storage_dir / "blobs"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        
        self.snapshots: Dict[str, ShadowSnapshot] = {}
        self._lock = threading.RLock()
        self._cleaned = False
        
        # Register atexit handler for automatic resource cleanup
        atexit.register(self.cleanup)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    def _should_ignore(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(self.target_dir):
                return True
        except Exception:
            return True

        for part in path.parts:
            if part in self.ignore_patterns or part.startswith(".ketan") or part.startswith(".chronos"):
                return True
        return False

    def scan_state(self) -> Dict[str, FileState]:
        """Scans the target directory and returns a map of relative paths to FileStates."""
        with self._lock:
            states = {}
            for root, dirs, files in os.walk(self.target_dir):
                root_path = Path(root)
                
                # Filter directories in-place to avoid traversing ignored folders
                dirs[:] = [d for d in dirs if not self._should_ignore(root_path / d)]
                
                for file_name in files:
                    abs_path = root_path / file_name
                    if self._should_ignore(abs_path):
                        continue
                    try:
                        rel_path = str(abs_path.relative_to(self.target_dir))
                        states[rel_path] = FileState(rel_path, abs_path)
                    except ValueError:
                        continue
                    
            return states

    def create_snapshot(self, snapshot_id: str) -> ShadowSnapshot:
        """
        Takes an incremental, content-addressed snapshot of the workspace.
        Only unique file contents (blobs) are stored once.
        """
        with self._lock:
            current_states = self.scan_state()
            snap_backup_dir = self.storage_dir / snapshot_id
            snap_backup_dir.mkdir(parents=True, exist_ok=True)
            
            for rel_path, st in current_states.items():
                if st.exists and not st.is_dir and st.content_hash:
                    blob_path = self.blob_dir / st.content_hash
                    if not blob_path.exists():
                        shutil.copy2(st.abs_path, blob_path)
                    
                    # Create symlink or copy to snap_backup_dir for backward compatibility
                    dest = snap_backup_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        try:
                            os.link(blob_path, dest)
                        except (OSError, AttributeError):
                            shutil.copy2(blob_path, dest)
                    
            snapshot = ShadowSnapshot(snapshot_id, snap_backup_dir, current_states)
            self.snapshots[snapshot_id] = snapshot
            
            # Enforce LRU eviction if snapshots exceed maximum allowed capacity
            if len(self.snapshots) > self.max_snapshots:
                oldest_id = min(self.snapshots.keys(), key=lambda k: self.snapshots[k].created_at)
                self.delete_snapshot(oldest_id)
                
            return snapshot

    def rollback_to(self, snapshot_id: str) -> Dict[str, str]:
        """
        Reverts the target workspace back to the physical state of snapshot_id.
        Phase 1: Validates diffs & path confinement.
        Phase 2: Performs clean restoration.
        """
        with self._lock:
            if snapshot_id not in self.snapshots:
                raise KeyError(f"Snapshot '{snapshot_id}' not found in KetanShadowFS ledger.")
                
            target_snap = self.snapshots[snapshot_id]
            current_states = self.scan_state()
            diff = target_snap.get_diff(current_states)
            
            # Phase 1: Pre-validation of path confinement
            validated_diff = {}
            for rel_path, status in diff.items():
                target_file = (self.target_dir / rel_path).resolve()
                if not target_file.is_relative_to(self.target_dir):
                    continue
                validated_diff[rel_path] = status

            # Phase 2: Restoration execution
            # 1. Remove files created after the snapshot was taken
            for rel_path, status in validated_diff.items():
                if status == "CREATED":
                    abs_p = self.target_dir / rel_path
                    if abs_p.exists() or abs_p.is_symlink():
                        if abs_p.is_dir() and not abs_p.is_symlink():
                            shutil.rmtree(abs_p)
                        else:
                            abs_p.unlink()
                            parent = abs_p.parent
                            while parent != self.target_dir and parent.exists() and not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent

            # 2. Restore modified or deleted files from blob store or backup dir
            for rel_path, status in validated_diff.items():
                if status in ("MODIFIED", "DELETED"):
                    target_file = self.target_dir / rel_path
                    old_st = target_snap.file_states.get(rel_path)
                    
                    if old_st and old_st.content_hash:
                        blob_path = self.blob_dir / old_st.content_hash
                        backup_file = target_snap.backup_dir / rel_path
                        source_file = blob_path if blob_path.exists() else backup_file
                        
                        if source_file.exists():
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            if target_file.is_symlink():
                                target_file.unlink()
                            shutil.copy2(source_file, target_file)
                        elif target_file.exists() or target_file.is_symlink():
                            target_file.unlink()
                    elif target_file.exists() or target_file.is_symlink():
                        target_file.unlink()

            return validated_diff


    def delete_snapshot(self, snapshot_id: str):
        """Purges snapshot metadata and backup directory from disk."""
        with self._lock:
            if snapshot_id in self.snapshots:
                snap = self.snapshots.pop(snapshot_id)
                if snap.backup_dir.exists():
                    shutil.rmtree(snap.backup_dir, ignore_errors=True)

    def cleanup(self):
        """Destroys the shadow storage overlay and temp directory."""
        with self._lock:
            if not self._cleaned:
                self._cleaned = True
                if self.storage_dir.exists():
                    shutil.rmtree(self.storage_dir, ignore_errors=True)


# Alias for backward compatibility
ShadowFS = KetanShadowFS
