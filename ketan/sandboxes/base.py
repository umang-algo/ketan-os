"""
Abstract Base Sandbox Engine for Ketan-OS (केतन).

Defines the plug-and-play interface for executing tool commands and file operations
inside isolated execution environments (Local workspace, Docker containers, MicroVMs).
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
from pathlib import Path


class BaseSandboxEngine(ABC):
    """Abstract interface for Ketan-OS tool execution sandbox environments."""
    
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()

    @abstractmethod
    def execute_bash(self, command: str, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        """
        Executes a shell command inside the sandbox.
        Returns: Tuple[exit_code, stdout, stderr]
        """
        pass

    @abstractmethod
    def write_file(self, rel_path: str, content: str) -> None:
        """Writes content to a file relative to the sandbox workspace root."""
        pass

    @abstractmethod
    def read_file(self, rel_path: str) -> str:
        """Reads content from a file relative to the sandbox workspace root."""
        pass
