"""
Git System Compensation Driver for Ketan-OS (केतन).

Generates automated compensation handlers for Git operations (git commit, git branch, working tree mutations).
"""

import subprocess
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("GitCompensationDriver")


class GitCompensationDriver:
    """Out-of-the-box compensation driver for Git repository mutations."""
    
    @staticmethod
    def compensate_commit(tool_args: Dict[str, Any], tool_result: Any, workspace_root: str) -> None:
        """Compensation handler for git commit: executes git revert HEAD --no-edit."""
        try:
            res = subprocess.run(
                ["git", "revert", "HEAD", "--no-edit"],
                cwd=workspace_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode == 0:
                logger.info("[GitCompensationDriver] Successfully reverted last Git commit.")
            else:
                logger.warning(f"[GitCompensationDriver] Git revert warning: {res.stderr}")
        except Exception as ex:
            logger.error(f"[GitCompensationDriver] Git revert failed: {str(ex)}")

    @staticmethod
    def compensate_checkout(tool_args: Dict[str, Any], tool_result: Any, workspace_root: str) -> None:
        """Compensation handler for checkout: restores working tree state."""
        try:
            subprocess.run(["git", "restore", "."], cwd=workspace_root, check=False)
            logger.info("[GitCompensationDriver] Restored Git working tree.")
        except Exception as ex:
            logger.error(f"[GitCompensationDriver] Git restore failed: {str(ex)}")
