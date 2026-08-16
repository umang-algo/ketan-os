"""
Local Process Execution Backend for Ketan-OS (केतन).

Executes commands and file operations locally inside the workspace root
with strict canonical path isolation enforcement.
"""

import subprocess
import os
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from ketan.sandboxes.base import BaseSandboxEngine


class LocalExecutionBackend(BaseSandboxEngine):
    """Local workspace execution backend with canonical path confinement."""
    
    def _resolve_safe(self, rel_path: str) -> Path:
        p = Path(rel_path)
        abs_p = (self.workspace_root / p).resolve() if not p.is_absolute() else p.resolve()
        if not abs_p.is_relative_to(self.workspace_root):
            raise PermissionError(
                f"Path confinement violation: '{rel_path}' resolves to '{abs_p}' outside workspace root '{self.workspace_root}'."
            )
        return abs_p

    def execute_bash(self, command: str, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        target_cwd = self._resolve_safe(cwd) if cwd else self.workspace_root
        
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(target_cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged_env
        )
        return proc.returncode, proc.stdout, proc.stderr

    def write_file(self, rel_path: str, content: str) -> None:
        target_file = self._resolve_safe(rel_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.is_symlink():
            target_file.unlink()
        target_file.write_text(content, encoding="utf-8")

    def read_file(self, rel_path: str) -> str:
        target_file = self._resolve_safe(rel_path)
        return target_file.read_text(encoding="utf-8")


# Alias for backward compatibility
LocalProcessSandbox = LocalExecutionBackend
