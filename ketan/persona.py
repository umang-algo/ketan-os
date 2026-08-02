"""
Agent Persona Freeze & State Fork for Ketan-OS (केतन).

Serializes the complete cognitive state of a running agent
(prompt stack + workspace + custom state + skill memory) to disk as a
portable snapshot.
"""

import json
import os
import shutil
import tempfile
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FrozenPersona:
    """
    A complete, portable snapshot of an agent's cognitive + environment state in Ketan-OS.
    """
    persona_id:     str
    label:          str
    prompt_stack:   List[Dict[str, Any]]
    custom_state:   Dict[str, Any]
    workspace_hash: str
    step_number:    int
    ctg_snapshot:   Optional[Dict[str, Any]]
    created_at:     float
    workspace_dir:  str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "label": self.label,
            "prompt_stack": self.prompt_stack,
            "custom_state": self.custom_state,
            "workspace_hash": self.workspace_hash,
            "step_number": self.step_number,
            "ctg_snapshot": self.ctg_snapshot,
            "created_at": self.created_at,
        }

    def summary(self) -> str:
        return (
            f"FrozenPersona '{self.label}' "
            f"(id={self.persona_id[:8]}, step={self.step_number}, "
            f"messages={len(self.prompt_stack)}, "
            f"created={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.created_at))})"
        )


@dataclass
class PersonaDiff:
    """Difference between two frozen personas."""
    persona_a_id:  str
    persona_b_id:  str
    step_delta:    int
    added_messages: List[Dict[str, Any]]
    removed_messages: List[Dict[str, Any]]
    state_changes: Dict[str, Tuple[Any, Any]]
    files_added:   List[str]
    files_removed: List[str]
    files_changed: List[str]

    def summary(self) -> str:
        lines = [
            f"Diff: '{self.persona_a_id[:8]}' → '{self.persona_b_id[:8]}'",
            f"  Step delta: {self.step_delta:+d}",
            f"  Messages added: {len(self.added_messages)} | removed: {len(self.removed_messages)}",
            f"  State keys changed: {list(self.state_changes.keys())}",
            f"  Files added: {self.files_added}",
            f"  Files removed: {self.files_removed}",
            f"  Files changed: {self.files_changed}",
        ]
        return "\n".join(lines)


class PersonaVault:
    """
    Manages on-disk storage of frozen personas in Ketan-OS.
    """

    def __init__(self, vault_dir: str):
        self.vault_dir = os.path.abspath(vault_dir)
        os.makedirs(self.vault_dir, exist_ok=True)

    def save(self, persona: FrozenPersona) -> str:
        persona_dir = os.path.join(self.vault_dir, persona.persona_id)
        os.makedirs(persona_dir, exist_ok=True)

        meta_path = os.path.join(persona_dir, "meta.json")
        with open(meta_path, "w") as f:
            json.dump(persona.to_dict(), f, indent=2)

        vault_ws = os.path.join(persona_dir, "workspace")
        if os.path.isdir(persona.workspace_dir) and persona.workspace_dir != vault_ws:
            if os.path.isdir(vault_ws):
                shutil.rmtree(vault_ws)
            shutil.copytree(
                persona.workspace_dir,
                vault_ws,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ketan_*", ".chronos_*")
            )

        return persona_dir

    def load(self, persona_id: str) -> FrozenPersona:
        persona_dir = os.path.join(self.vault_dir, persona_id)
        meta_path = os.path.join(persona_dir, "meta.json")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Persona '{persona_id}' not found in vault.")

        with open(meta_path) as f:
            data = json.load(f)

        return FrozenPersona(
            persona_id=data["persona_id"],
            label=data["label"],
            prompt_stack=data["prompt_stack"],
            custom_state=data["custom_state"],
            workspace_hash=data["workspace_hash"],
            step_number=data["step_number"],
            ctg_snapshot=data.get("ctg_snapshot"),
            created_at=data["created_at"],
            workspace_dir=os.path.join(persona_dir, "workspace"),
        )

    def list_personas(self) -> List[Dict[str, Any]]:
        entries = []
        for name in os.listdir(self.vault_dir):
            meta_path = os.path.join(self.vault_dir, name, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    data = json.load(f)
                entries.append({
                    "persona_id": data["persona_id"],
                    "label": data["label"],
                    "step_number": data["step_number"],
                    "created_at": data["created_at"],
                })
        return sorted(entries, key=lambda x: x["created_at"])

    def delete(self, persona_id: str) -> None:
        persona_dir = os.path.join(self.vault_dir, persona_id)
        if os.path.isdir(persona_dir):
            shutil.rmtree(persona_dir)


class PersonaManager:
    """
    High-level API for freezing, forking, replaying, and diffing agent states.
    """

    def __init__(self, vault: PersonaVault):
        self.vault = vault

    def freeze(
        self,
        label: str,
        workspace_dir: str,
        prompt_stack: List[Dict[str, Any]],
        step_number: int = 0,
        custom_state: Optional[Dict[str, Any]] = None,
        ctg_snapshot: Optional[Dict[str, Any]] = None,
    ) -> FrozenPersona:
        persona_id = self._generate_id(label, step_number)
        ws_hash = self._hash_workspace(workspace_dir)

        temp_ws = tempfile.mkdtemp(prefix=f"ketan_persona_{persona_id[:8]}_")
        if os.path.isdir(workspace_dir):
            shutil.copytree(
                workspace_dir,
                os.path.join(temp_ws, "ws"),
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ketan_*", ".chronos_*")
            )

        persona = FrozenPersona(
            persona_id=persona_id,
            label=label,
            prompt_stack=[dict(m) for m in prompt_stack],
            custom_state=dict(custom_state or {}),
            workspace_hash=ws_hash,
            step_number=step_number,
            ctg_snapshot=ctg_snapshot,
            created_at=time.time(),
            workspace_dir=os.path.join(temp_ws, "ws"),
        )

        self.vault.save(persona)

        try:
            shutil.rmtree(temp_ws, ignore_errors=True)
        except Exception:
            pass

        vault_ws = os.path.join(self.vault.vault_dir, persona_id, "workspace")
        persona.workspace_dir = vault_ws
        return persona

    def fork(self, persona: FrozenPersona, n: int = 2) -> List[Dict[str, Any]]:
        forks = []
        for i in range(n):
            fork_dir = tempfile.mkdtemp(prefix=f"ketan_fork_{i}_{persona.persona_id[:8]}_")
            fork_ws = os.path.join(fork_dir, "workspace")

            if os.path.isdir(persona.workspace_dir):
                shutil.copytree(
                    persona.workspace_dir,
                    fork_ws,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ketan_*", ".chronos_*")
                )
            else:
                os.makedirs(fork_ws, exist_ok=True)

            forks.append({
                "fork_index": i,
                "fork_id": f"{persona.persona_id[:8]}_fork_{i}",
                "workspace_dir": fork_ws,
                "prompt_stack": [dict(m) for m in persona.prompt_stack],
                "custom_state": dict(persona.custom_state),
                "step_number": persona.step_number,
                "source_persona_id": persona.persona_id,
                "_temp_root": fork_dir,
            })

        return forks

    def cleanup_fork(self, fork: Dict[str, Any]) -> None:
        temp_root = fork.get("_temp_root")
        if temp_root and os.path.isdir(temp_root):
            shutil.rmtree(temp_root, ignore_errors=True)

    def cleanup_all_forks(self, forks: List[Dict[str, Any]]) -> None:
        for fork in forks:
            self.cleanup_fork(fork)

    def replay(self, persona: FrozenPersona) -> Dict[str, Any]:
        replay_dir = tempfile.mkdtemp(prefix=f"ketan_replay_{persona.persona_id[:8]}_")
        replay_ws = os.path.join(replay_dir, "workspace")

        if os.path.isdir(persona.workspace_dir):
            shutil.copytree(
                persona.workspace_dir,
                replay_ws,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ketan_*", ".chronos_*")
            )
        else:
            os.makedirs(replay_ws, exist_ok=True)

        return {
            "mode": "replay",
            "persona_id": persona.persona_id,
            "label": persona.label,
            "workspace_dir": replay_ws,
            "prompt_stack": [dict(m) for m in persona.prompt_stack],
            "custom_state": dict(persona.custom_state),
            "step_number": persona.step_number,
            "ctg_snapshot": persona.ctg_snapshot,
            "_temp_root": replay_dir,
        }

    def diff(self, persona_a: FrozenPersona, persona_b: FrozenPersona) -> PersonaDiff:
        msgs_a = {json.dumps(m, sort_keys=True) for m in persona_a.prompt_stack}
        msgs_b = {json.dumps(m, sort_keys=True) for m in persona_b.prompt_stack}
        added_msgs   = [json.loads(m) for m in (msgs_b - msgs_a)]
        removed_msgs = [json.loads(m) for m in (msgs_a - msgs_b)]

        state_changes: Dict[str, Tuple[Any, Any]] = {}
        all_keys = set(persona_a.custom_state) | set(persona_b.custom_state)
        for k in all_keys:
            va = persona_a.custom_state.get(k, "__MISSING__")
            vb = persona_b.custom_state.get(k, "__MISSING__")
            if va != vb:
                state_changes[k] = (va, vb)

        files_a = self._list_files(persona_a.workspace_dir)
        files_b = self._list_files(persona_b.workspace_dir)

        added   = sorted(set(files_b) - set(files_a))
        removed = sorted(set(files_a) - set(files_b))
        common  = set(files_a) & set(files_b)
        changed = []
        for rel_path in sorted(common):
            path_a = os.path.join(persona_a.workspace_dir, rel_path)
            path_b = os.path.join(persona_b.workspace_dir, rel_path)
            if self._file_hash(path_a) != self._file_hash(path_b):
                changed.append(rel_path)

        return PersonaDiff(
            persona_a_id=persona_a.persona_id,
            persona_b_id=persona_b.persona_id,
            step_delta=persona_b.step_number - persona_a.step_number,
            added_messages=added_msgs,
            removed_messages=removed_msgs,
            state_changes=state_changes,
            files_added=added,
            files_removed=removed,
            files_changed=changed,
        )

    def load(self, persona_id: str) -> FrozenPersona:
        return self.vault.load(persona_id)

    def _generate_id(self, label: str, step: int) -> str:
        raw = f"{label}:{step}:{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _hash_workspace(self, workspace_dir: str) -> str:
        if not os.path.isdir(workspace_dir):
            return "empty"
        h = hashlib.sha256()
        for root, dirs, files in sorted(os.walk(workspace_dir)):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
            for fname in sorted(files):
                if fname.endswith(".pyc"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "rb") as f:
                        h.update(f.read())
                except Exception:
                    pass
        return h.hexdigest()[:16]

    def _list_files(self, workspace_dir: str) -> List[str]:
        if not os.path.isdir(workspace_dir):
            return []
        result = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".pyc"):
                    rel = os.path.relpath(os.path.join(root, fname), workspace_dir)
                    result.append(rel)
        return result

    def _file_hash(self, path: str) -> str:
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""
