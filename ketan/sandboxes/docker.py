"""
Docker Container Sandbox Engine for Ketan-OS (केतन).

Executes tool commands inside an isolated Docker container runtime with workspace volume mounting.
Fails CLOSED if Docker daemon is not available.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from ketan.sandboxes.base import BaseSandboxEngine
from ketan.sandboxes.local import LocalExecutionBackend


class DockerContainerSandbox(BaseSandboxEngine):
    """
    Isolated container sandbox engine running commands inside a Docker container.
    Fails CLOSED if Docker daemon is not available to prevent security downgrade attacks.
    """
    def __init__(self, workspace_root: str, image_name: str = "python:3.11-slim", allow_network: bool = False):
        super().__init__(workspace_root)
        self.image_name = image_name
        self.allow_network = allow_network
        self.local_backend = LocalExecutionBackend(workspace_root)
        self.docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        if not shutil.which("docker"):
            return False
        try:
            res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return res.returncode == 0
        except Exception:
            return False

    def execute_bash(self, command: str, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        if not self.docker_available:
            raise RuntimeError(
                "Fail-Closed Security Guard: DockerContainerSandbox was explicitly requested, "
                "but Docker daemon is not available or running. Refusing silent host execution fallback."
            )

        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.workspace_root}:/workspace",
            "-w", "/workspace",
            "--security-opt", "no-new-privileges",
        ]

        if not self.allow_network:
            docker_cmd.extend(["--network", "none"])

        docker_cmd.extend([self.image_name, "sh", "-c", command])
        
        proc = subprocess.run(docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def write_file(self, rel_path: str, content: str) -> None:
        self.local_backend.write_file(rel_path, content)

    def read_file(self, rel_path: str) -> str:
        return self.local_backend.read_file(rel_path)
