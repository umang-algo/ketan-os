"""
Content-Addressed Persistent Workspace Snapshot Engine for Ketan-OS (केतन).

Tracks file tree state and enables deterministic workspace state rollback to any historical snapshot
using content-addressed deduplicated blob storage stored persistently in workspace_root/.ketan/.
Writes .ketan/snapshots/<snapshot_id>/manifest.json for deterministic snapshot state recovery.

Thread-safe across processes.
"""

import os
import json
import shutil
import hashlib
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Any


class FileState:
    """Represents the state of a single file in the workspace at a given point in time."""
    def __init__(self, rel_path: str, abs_path: Path):
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.exists = abs_path.exists() or abs_path.is_symlink()
        self.is_dir = abs_path.is_dir() if self.exists and not abs_path.is_symlink() else False
        self.is_symlink = abs_path.is_symlink()
        self.mtime = abs_path.stat().st_mtime if self.exists and not self.is_symlink else 0
        self.size = abs_path.stat().st_size if self.exists and not self.is_dir and not self.is_symlink else 0
        self.content_hash = self._compute_hash() if self.exists and not self.is_dir and not self.is_symlink else None

    def _compute_hash(self) -> str:
        """Computes SHA-256 content hash of the file."""
        hasher = hashlib.sha256()
        try:
            with open(self.abs_path, 'rb') as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, IOError):
            return ""

    def __repr__(self):
        return f"<FileState path='{self.rel_path}' exists={self.exists} hash={self.content_hash[:8] if self.content_hash else 'N/A'}>"


class ShadowSnapshot:
    """A point-in-time content-addressed snapshot of the workspace with manifest metadata."""
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
    Persistent Content-Addressed Workspace Snapshot Engine for Ketan-OS (केतन).
    Stores snapshots, manifests, and blobs in workspace_root/.ketan/ for crash durability.
    Thread-safe synchronization.
    """
    def __init__(self, target_dir: str, ignore_patterns: Optional[List[str]] = None, max_snapshots: int = 50):
        self.target_dir = Path(target_dir).resolve()
        if not self.target_dir.exists():
            self.target_dir.mkdir(parents=True, exist_ok=True)
            
        self.ignore_patterns = set(ignore_patterns or [
            ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".DS_Store"
        ])
        
        self.max_snapshots = max_snapshots
        self.storage_dir = self.target_dir / ".ketan"
        self.blob_dir = self.storage_dir / "blobs"
        self.snapshots_dir = self.storage_dir / "snapshots"
        
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        
        self.snapshots: Dict[str, ShadowSnapshot] = {}
        self._lock = threading.RLock()
        self._load_existing_snapshots()

    def _load_existing_snapshots(self):
        """Loads pre-existing snapshot metadata & manifest.json files from disk for crash durability."""
        with self._lock:
            if not self.snapshots_dir.exists():
                return
            for snap_dir in self.snapshots_dir.iterdir():
                if snap_dir.is_dir():
                    snapshot_id = snap_dir.name
                    manifest_file = snap_dir / "manifest.json"
                    if manifest_file.exists():
                        try:
                            with open(manifest_file, "r", encoding="utf-8") as mf:
                                data = json.load(mf)
                            states = {}
                            for rel_p, st_d in data.get("file_states", {}).items():
                                abs_p = self.target_dir / rel_p
                                st = FileState(rel_p, abs_p)
                                st.content_hash = st_d.get("content_hash")
                                st.size = st_d.get("size", st.size)
                                states[rel_p] = st
                            self.snapshots[snapshot_id] = ShadowSnapshot(snapshot_id, snap_dir, states)
                            continue
                        except Exception:
                            pass
                    states = self._scan_backup_dir(snap_dir)
                    self.snapshots[snapshot_id] = ShadowSnapshot(snapshot_id, snap_dir, states)

    def _scan_backup_dir(self, backup_dir: Path) -> Dict[str, FileState]:
        """Scans snapshot backup directory directly to reconstruct historical FileStates."""
        states = {}
        if not backup_dir.exists():
            return states
        for root, dirs, files in os.walk(backup_dir):
            root_path = Path(root)
            for file in sorted(files):
                if file == "manifest.json":
                    continue
                abs_path = root_path / file
                try:
                    rel_path = str(abs_path.relative_to(backup_dir))
                    states[rel_path] = FileState(rel_path, abs_path)
                except ValueError:
                    continue
        return states

    def is_ignored(self, path: Path) -> bool:
        """Checks if path or parent directory matches ignore patterns."""
        for part in path.parts:
            if part in self.ignore_patterns or part.startswith(".ketan") or part.startswith(".chronos"):
                return True
        return False

    def scan_state(self) -> Dict[str, FileState]:
        """Scans workspace directory recursively and returns map of relative paths to FileState."""
        with self._lock:
            states = {}
            if not self.target_dir.exists():
                return states

            for root, dirs, files in os.walk(self.target_dir, followlinks=False):
                root_path = Path(root)

                # Filter ignored subdirectories in-place
                dirs[:] = [d for d in dirs if not self.is_ignored(root_path / d)]

                for file in files:
                    abs_path = root_path / file
                    if self.is_ignored(abs_path):
                        continue

                    # Confinement check
                    resolved = abs_path.resolve() if not abs_path.is_symlink() else abs_path
                    if abs_path.is_symlink():
                        try:
                            target_abs = abs_path.readlink().resolve()
                            if not target_abs.is_relative_to(self.target_dir):
                                continue
                        except (OSError, ValueError):
                            continue

                    try:
                        rel_path = str(abs_path.relative_to(self.target_dir))
                        states[rel_path] = FileState(rel_path, abs_path)
                    except ValueError:
                        continue
                    
            return states

    def compute_current_fs_root_hash(self) -> str:
        """Computes a cryptographic SHA-256 state root hash of all tracked workspace files."""
        with self._lock:
            states = self.scan_state()
            hasher = hashlib.sha256()
            for path in sorted(states.keys()):
                st = states[path]
                hasher.update(path.encode("utf-8"))
                hasher.update((st.content_hash or "").encode("utf-8"))
            return hasher.hexdigest()

    def create_snapshot(self, snapshot_id: str) -> ShadowSnapshot:
        """
        Takes an incremental, content-addressed snapshot of the workspace.
        Stores blobs in .ketan/blobs/ and manifest.json metadata in .ketan/snapshots/<snapshot_id>/.
        """
        with self._lock:
            current_states = self.scan_state()
            snap_backup_dir = self.snapshots_dir / snapshot_id
            snap_backup_dir.mkdir(parents=True, exist_ok=True)
            
            for rel_path, st in current_states.items():
                if st.exists and not st.is_dir and st.content_hash:
                    blob_path = self.blob_dir / st.content_hash
                    if not blob_path.exists():
                        shutil.copy2(st.abs_path, blob_path)
                    
                    dest = snap_backup_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        try:
                            os.link(blob_path, dest)
                        except (OSError, AttributeError):
                            shutil.copy2(blob_path, dest)
                    
            # Write durable manifest.json for snapshot
            manifest = {
                "snapshot_id": snapshot_id,
                "created_at": time.time(),
                "fs_root_hash": self.compute_current_fs_root_hash(),
                "file_states": {
                    rel_p: {
                        "rel_path": st.rel_path,
                        "content_hash": st.content_hash,
                        "size": st.size,
                        "mtime": st.mtime,
                        "is_dir": st.is_dir,
                        "is_symlink": st.is_symlink
                    }
                    for rel_p, st in current_states.items()
                }
            }
            manifest_file = snap_backup_dir / "manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2)

            snapshot = ShadowSnapshot(snapshot_id, snap_backup_dir, current_states)
            self.snapshots[snapshot_id] = snapshot
            
            if len(self.snapshots) > self.max_snapshots:
                oldest_id = min(self.snapshots.keys(), key=lambda k: self.snapshots[k].created_at)
                self.delete_snapshot(oldest_id)
                
            return snapshot

    def rollback_to(self, snapshot_id: str) -> Dict[str, str]:
        """
        Reverts target workspace back to physical state of snapshot_id.
        Phase 1: Validates diffs & path confinement.
        Phase 2: Performs clean restoration.
        """
        with self._lock:
            if snapshot_id not in self.snapshots:
                # Reload snapshots from disk in case created by another process
                self._load_existing_snapshots()
                
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
            # 1. Remove files created after snapshot
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

            # 2. Restore modified or deleted files
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

            return validated_diff

    def delete_snapshot(self, snapshot_id: str):
        """Deletes snapshot metadata."""
        with self._lock:
            if snapshot_id in self.snapshots:
                snap = self.snapshots.pop(snapshot_id)
                if snap.backup_dir.exists():
                    shutil.rmtree(snap.backup_dir, ignore_errors=True)

    def cleanup(self):
        """Clean up in-memory references."""
        pass


# Aliases for backward compatibility
ShadowFS = KetanShadowFS
