import ast
import inspect
import os
import re
from pathlib import Path
from typing import Callable, List, Dict, Any, Tuple, Optional


class InvariantResult:
    """Result of an invariant verification check in Ketan-OS."""
    def __init__(self, passed: bool, rule_name: str, message: str, hint: Optional[str] = None):
        self.passed = passed
        self.rule_name = rule_name
        self.message = message
        self.hint = hint or ""

    def __repr__(self):
        status = "PASSED" if self.passed else "FAILED"
        return f"<InvariantResult [{status}] rule='{self.rule_name}': {self.message}>"


class InvariantVerifier:
    """
    Engine for checking pre-flight and post-flight invariant assertions
    on tool inputs, environment mutations, and generated code artifacts.
    """
    def __init__(self):
        self.pre_flight_rules: List[Tuple[str, Callable]] = []
        self.post_flight_rules: List[Tuple[str, Callable]] = []
        self._register_default_rules()

    def register_pre_flight_rule(self, name: str, fn: Callable[[Dict[str, Any]], Tuple[bool, str, Optional[str]]]):
        """Registers a pre-flight verification function."""
        self.pre_flight_rules.append((name, fn))

    def register_post_flight_rule(self, name: str, fn: Callable[[Dict[str, Any]], Tuple[bool, str, Optional[str]]]):
        """Registers a post-flight verification function."""
        self.post_flight_rules.append((name, fn))

    def _register_default_rules(self):
        """Registers essential built-in safety and correctness rules."""
        
        # Rule 1: Strict Canonical Workspace Path Isolation Guard
        def check_path_isolation(payload: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
            workspace_root_str = payload.get("workspace_root") or payload.get("workspace_dir")
            if not workspace_root_str:
                return True, "Path isolation check skipped (no workspace_root payload).", None

            ws_root = Path(workspace_root_str).resolve()
            path_keys = ["filepath", "path", "dest", "source", "target", "file"]

            for key in path_keys:
                raw_path_val = payload.get(key)
                if not raw_path_val or not isinstance(raw_path_val, str):
                    continue

                raw_path_str = raw_path_val.strip()
                if not raw_path_str:
                    continue

                # Check path traversal markers
                try:
                    p = Path(raw_path_str)
                    target_abs = (ws_root / p).resolve() if not p.is_absolute() else p.resolve()

                    if not target_abs.is_relative_to(ws_root):
                        return (
                            False,
                            f"Security path traversal violation in parameter '{key}': '{raw_path_str}' targets path '{target_abs}' outside workspace root '{ws_root}'.",
                            f"Path confinement violation: File operations must target paths within workspace root '{ws_root}'."
                        )

                    # Symlink target inspection
                    if target_abs.is_symlink():
                        symlink_target = target_abs.readlink().resolve()
                        if not symlink_target.is_relative_to(ws_root):
                            return (
                                False,
                                f"Security symlink traversal violation in parameter '{key}': Symlink '{target_abs}' points to external path '{symlink_target}'.",
                                f"Symlink safety violation: Symlinks pointing outside workspace root '{ws_root}' are forbidden."
                            )
                except Exception as ex:
                    return (
                        False,
                        f"Malformed path argument in parameter '{key}': '{raw_path_str}' ({str(ex)})",
                        "Provide a valid workspace-confined relative or absolute path."
                    )

            return True, "Path isolation check passed.", None

        # Rule 2: Python Syntax Validity (Pre-flight for file writes)
        def check_python_syntax(payload: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
            filepath = payload.get("filepath", "")
            content = payload.get("content", "")
            if filepath.endswith(".py") and content:
                try:
                    ast.parse(content)
                except SyntaxError as e:
                    return (
                        False, 
                        f"Python SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}",
                        f"Python SyntaxError: Fix syntax error on line {e.lineno}: '{e.text.strip() if e.text else ''}' before committing the file."
                    )
            return True, "Syntax check passed.", None

        # Rule 3: Dangerous Shell Command Guard (Guardrail)
        def check_dangerous_bash(payload: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
            raw_cmd = payload.get("command", "").strip()
            if not raw_cmd:
                return True, "Bash safety check passed.", None

            # Normalize whitespace and lowercase for token checking
            normalized = " ".join(raw_cmd.split())
            norm_lower = normalized.lower()

            # 1. Destructive deletion patterns (rm -rf /, rm -rf ~, rm -rf $HOME, rm -rf /*, etc.)
            destructive_rm_regex = re.compile(
                r'\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(/|\/\*|~|~\/\*|\$home|\$home\/\*|\.|\.\.|\.\/\*|--no-preserve-root)(\s+|$)',
                re.IGNORECASE
            )
            if destructive_rm_regex.search(normalized) or "--no-preserve-root" in norm_lower:
                return (
                    False,
                    f"Dangerous destructive filesystem command detected in '{raw_cmd}'.",
                    "Avoid destructive commands targeting root, home, or workspace boundaries."
                )

            # 2. Raw device formatting & disk overwrite
            disk_wipe_regex = re.compile(
                r'\b(dd\s+if=/dev/(zero|urandom|null)|mkfs(\.[a-z0-9]+)?|fdisk|parted|shred|sfdisk)\b',
                re.IGNORECASE
            )
            if disk_wipe_regex.search(normalized) or "/dev/sd" in norm_lower or "/dev/hd" in norm_lower or "/dev/nvme" in norm_lower:
                return (
                    False,
                    f"Dangerous raw disk/device operation detected in '{raw_cmd}'.",
                    "Direct disk partition/wipe operations are blocked for security."
                )

            # 3. System state alteration, shutdown, and fork bombs
            system_kill_tokens = [":(){ :|:& };:", "shutdown", "reboot", "poweroff", "init 0", "halt"]
            for token in system_kill_tokens:
                if token in normalized:
                    return (
                        False,
                        f"Dangerous system shutdown/forkbomb command detected containing '{token}'.",
                        "System state alteration commands are strictly forbidden."
                    )

            # 4. Obfuscated shell execution and remote execution piping (base64 -d | sh, curl | bash)
            obfuscated_exec_regex = re.compile(
                r'\b(base64\s+(-d|--decode)|curl|wget)\b.*\|\s*(sh|bash|zsh|python)\b',
                re.IGNORECASE
            )
            if obfuscated_exec_regex.search(normalized):
                return (
                    False,
                    f"Dangerous obfuscated execution or remote piping detected in '{raw_cmd}'.",
                    "Do not pipe untrusted remote scripts or encoded payloads into shell execution."
                )

            return True, "Bash safety check passed.", None

        self.register_pre_flight_rule("path_isolation_guard", check_path_isolation)
        self.register_pre_flight_rule("python_syntax_guard", check_python_syntax)
        self.register_pre_flight_rule("dangerous_command_guard", check_dangerous_bash)

    def verify_pre_flight(self, tool_name: str, tool_args: Dict[str, Any]) -> List[InvariantResult]:
        """Runs all applicable pre-flight verification rules."""
        results = []
        payload = {"tool_name": tool_name, **tool_args}
        
        for rule_name, rule_fn in self.pre_flight_rules:
            try:
                passed, msg, hint = rule_fn(payload)
                results.append(InvariantResult(passed, rule_name, msg, hint))
            except Exception as ex:
                results.append(InvariantResult(False, rule_name, f"Rule execution error: {str(ex)}"))
                
        return results

    def verify_post_flight(self, tool_name: str, tool_args: Dict[str, Any], execution_result: Any) -> List[InvariantResult]:
        """Runs all applicable post-flight verification rules."""
        results = []
        payload = {"tool_name": tool_name, "result": execution_result, **tool_args}
        
        for rule_name, rule_fn in self.post_flight_rules:
            try:
                passed, msg, hint = rule_fn(payload)
                results.append(InvariantResult(passed, rule_name, msg, hint))
            except Exception as ex:
                results.append(InvariantResult(False, rule_name, f"Rule execution error: {str(ex)}"))
                
        return results
