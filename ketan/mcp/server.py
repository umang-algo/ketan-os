"""
Ketan-OS MCP Server for Claude Code Integration.

Exposes all Ketan-OS capabilities as Model Context Protocol (MCP) tools
so Claude Code (and any MCP-compatible client) gets:
  - Atomic workspace snapshotting & time-travel rollback
  - Pre-flight invariant guards before every tool call
  - Live Causal Trace Graph (CTG) DAG with failure explanations
  - Epistemic belief contradiction detection & memory pruning
  - Scope-locked RBAC policy engine
  - eBPF-style symbolic micro-patch kernel

Usage (stdio transport — Claude Code compatible):
  uv run python -m ketan.mcp.server --workspace /path/to/project

Configure in Claude Code's ~/.claude/claude.json:
  {
    "mcpServers": {
      "ketan-os": {
        "command": "uv",
        "args": [
          "run",
          "--directory", "/absolute/path/to/ketan-OS",
          "python", "-m", "ketan.mcp.server",
          "--workspace", "/absolute/path/to/your/project"
        ]
      }
    }
  }
"""

import sys
import os
import json
import logging
import argparse
import atexit
import subprocess
from pathlib import Path
from typing import Optional
import asyncio

# NOTE: Never use print() in MCP stdio servers — it corrupts the JSON-RPC stream.
# All debug output goes to stderr.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Ketan-MCP] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("ketan-mcp")

# Add project root to path for local development
_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent
if (_ROOT / "ketan").exists():
    sys.path.insert(0, str(_ROOT))

# Robust dual-compatibility for mcp 1.x (FastMCP) and mcp 2.x (MCPServer)
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:
        log.error(
            "MCP SDK not installed. Run: uv add mcp\n"
            "Or: pip install mcp"
        )
        sys.exit(1)

from ketan import (
    KetanHarness,
    KetanAgentWrapper,
    EpistemicBeliefEngine,
)


# ---------------------------------------------------------------------------
# Global Harness State
# ---------------------------------------------------------------------------

_harness: Optional[KetanHarness] = None
_prompt_stack = [{"role": "system", "content": "Ketan-OS MCP session started."}]



def _cleanup_global_harness():
    global _harness
    if _harness is not None:
        try:
            _harness.cleanup()
        except Exception:
            pass


atexit.register(_cleanup_global_harness)


def _get_harness() -> KetanHarness:
    global _harness
    if _harness is None:
        raise RuntimeError(
            "Ketan-OS harness not initialized. "
            "Call ketan_init_workspace first."
        )
    return _harness


# ---------------------------------------------------------------------------
# MCP Server Instantiation (Compatible with v1 and v2 SDKs)
# ---------------------------------------------------------------------------

_instructions = (
    "You are now connected to Ketan-OS 🪔 (केतन — Beacon of Ground Truth). "
    "IMPORTANT: Before making file writes or shell commands that mutate state, "
    "call ketan_snapshot to capture a safe restore point, OR use "
    "ketan_write_file_safe and ketan_run_bash_safe which include automatic "
    "snapshotting and rollback on failure. "
    "Call ketan_get_status anytime to inspect the current ground-truth state."
)

try:
    mcp = FastMCP(
        name="ketan-os",
        title="Ketan-OS 🪔",
        description="Transactional Intelligence Substrate for Claude Code — atomic rollback, pre-flight guards, causal tracing.",
        instructions=_instructions,
    )
except TypeError:
    try:
        mcp = FastMCP(
            "ketan-os",
            instructions=_instructions,
        )
    except Exception:
        mcp = FastMCP("ketan-os")

server = mcp  # Alias for backward compatibility


# ---------------------------------------------------------------------------
# Tool: Initialize Workspace
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_init_workspace(workspace_path: str) -> str:
    """
    Initialize Ketan-OS for a workspace directory.
    This MUST be called before any other Ketan-OS tools if you are switching workspaces.
    Creates a KetanHarness that manages transactional snapshotting, invariant
    enforcement, and causal tracing for the given workspace.

    Args:
        workspace_path: Absolute path to the project/workspace directory to protect.
    """
    global _harness, _prompt_stack
    ws = Path(workspace_path).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    if _harness is not None:
        _harness.cleanup()

    _harness = KetanHarness(str(ws))
    _prompt_stack = [{"role": "system", "content": f"Ketan-OS protecting workspace: {ws}"}]


    log.info(f"Ketan-OS initialized for workspace: {ws}")
    return (
        f"✅ Ketan-OS initialized.\n"
        f"📁 Workspace: {ws}\n"
        f"🛡️  Pre-flight guards: Python AST syntax, dangerous command detection\n"
        f"🕰️  Time-travel rollback: READY\n"
        f"📊 Causal Trace Graph: ACTIVE\n"
        f"🧠 Epistemic Belief Engine: ACTIVE"
    )


# ---------------------------------------------------------------------------
# Tool: Get Status
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_get_status() -> str:
    """
    Get the current Ketan-OS ground-truth state report.
    Returns step count, checkpoint count, CTG node/edge counts,
    failure count, and workspace directory.
    """
    h = _get_harness()
    failures = h.causal_graph.find_all_failures()
    status = {
        "current_step": h.current_step,
        "checkpoints_count": len(h.ledger.checkpoints),
        "ctg_nodes": len(h.causal_graph.nodes),
        "ctg_edges": len(h.causal_graph.edges),
        "failures_count": len(failures),
        "workspace_dir": h.workspace_dir,
        "epistemic_beliefs": len(h.epistemic_engine.beliefs),
        "prompt_stack_depth": len(_prompt_stack),
    }
    return json.dumps(status, indent=2)


# ---------------------------------------------------------------------------
# Tool: Snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_snapshot() -> str:
    """
    Take an atomic filesystem snapshot of the entire workspace.
    Creates a checkpoint you can roll back to if anything goes wrong.
    Always call this before a risky sequence of operations.

    Returns the checkpoint ID you can use with ketan_rollback.
    """
    h = _get_harness()
    cp = h.create_checkpoint(prompt_stack=_prompt_stack)
    return (
        f"✅ Snapshot created.\n"
        f"🆔 Checkpoint ID: {cp.checkpoint_id}\n"
        f"📍 Step: {cp.step_number}\n"
        f"📁 Tracked workspace state snapshot recorded.\n"
        f"💡 To revert: ketan_rollback('{cp.checkpoint_id}')"
    )


# ---------------------------------------------------------------------------
# Tool: Rollback
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_rollback(checkpoint_id: str) -> str:
    """
    Roll back the workspace to a previous checkpoint.
    Reverts tracked filesystem changes (file writes, deletions, renames) that
    occurred after that checkpoint was taken.

    Args:
        checkpoint_id: The checkpoint ID to roll back to (from ketan_get_checkpoints or ketan_snapshot).
    """
    h = _get_harness()
    cp = h.ledger.checkpoints.get(checkpoint_id)
    if not cp:
        available = list(h.ledger.checkpoints.keys())[-5:]
        return (
            f"❌ Checkpoint '{checkpoint_id}' not found.\n"
            f"Available recent checkpoints: {available}"
        )
    try:
        h.rollback_to(checkpoint_id)
        return (
            f"✅ Rolled back to checkpoint '{checkpoint_id}' (step {cp.step_number}).\n"
            f"🕰️  Tracked workspace files restored to checkpoint state."
        )

    except Exception as e:
        return f"❌ Rollback failed: {e}"


# ---------------------------------------------------------------------------
# Tool: List Checkpoints
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_get_checkpoints() -> str:
    """
    List all available checkpoints in the Ketan dual-ledger (newest first).
    Each checkpoint captures the full workspace filesystem state and
    conversation prompt stack, enabling atomic rollback to any point.
    """
    h = _get_harness()
    checkpoints = []
    for cp in sorted(h.ledger.checkpoints.values(), key=lambda c: c.step_number, reverse=True):
        checkpoints.append({
            "checkpoint_id": cp.checkpoint_id,
            "step_number": cp.step_number,
            "created_at": cp.created_at,
            "tool_calls_count": len(cp.turn.tool_calls),
        })
    return json.dumps({"checkpoints": checkpoints, "total": len(checkpoints)}, indent=2)


# ---------------------------------------------------------------------------
# Tool: Safe File Write
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_write_file_safe(filepath: str, content: str) -> str:
    """
    Write a file to the workspace with FULL Ketan-OS protection:
      1. Pre-flight invariant guard: Python AST syntax check for .py files,
         dangerous pattern detection.
      2. Atomic snapshot of current workspace state before writing.
      3. Write the file.
      4. On any failure → automatic rollback to pre-write state.

    Always prefer this over direct file writes for safe, reversible mutations.

    Args:
        filepath: Path relative to workspace root (e.g., "src/main.py")
        content: Full file content to write
    """
    h = _get_harness()
    abs_path = Path(h.workspace_dir) / filepath

    # Pre-flight check
    pre_results = h.verifier.verify_pre_flight("write_file", {
        "filepath": str(abs_path),
        "content": content,
    })
    failures = [r for r in pre_results if not r.passed]
    if failures:
        f = failures[0]
        return (
            f"🚫 Pre-flight REJECTED — file NOT written.\n"
            f"Rule: {f.rule_name}\n"
            f"Reason: {f.message}\n"
            f"💡 Fix: {f.hint}"
        )

    # Snapshot before write
    cp = h.create_checkpoint(prompt_stack=_prompt_stack)

    try:
        h.sandbox.write_file(filepath, content)
        return (
            f"✅ File written safely.\n"
            f"📄 Path: {filepath}\n"
            f"📦 Size: {len(content.encode())} bytes\n"
            f"🆔 Pre-write checkpoint: {cp.checkpoint_id}\n"
            f"💡 Rollback: ketan_rollback('{cp.checkpoint_id}')"
        )
    except Exception as e:
        h.rollback_to(cp.checkpoint_id)
        return f"❌ Write failed — workspace auto-rolled back.\nError: {e}"


# ---------------------------------------------------------------------------
# Tool: Safe Bash Execution
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_run_bash_safe(command: str, timeout_seconds: int = 30) -> str:
    """
    Execute a shell command with FULL Ketan-OS protection:
      1. Pre-flight dangerous command guard (blocks rm -rf /, fork bombs, disk wipes, etc.).
      2. Atomic snapshot before execution.
      3. Run the command in the sandbox environment.
      4. On non-zero exit or exception → automatic rollback to pre-command state.

    Always prefer this over raw bash for state-changing commands.

    Args:
        command: Shell command to run (executed in workspace directory)
        timeout_seconds: Maximum execution time before timeout (default: 30s)
    """
    h = _get_harness()

    pre_results = h.verifier.verify_pre_flight("bash", {"command": command})
    failures = [r for r in pre_results if not r.passed]
    if failures:
        f = failures[0]
        return (
            f"🚫 Pre-flight REJECTED — command NOT executed.\n"
            f"Rule: {f.rule_name}\n"
            f"Reason: {f.message}\n"
            f"💡 Fix: {f.hint}"
        )

    cp = h.create_checkpoint(prompt_stack=_prompt_stack)

    try:
        exit_code, stdout, stderr = h.sandbox.execute_bash(command)
        stdout = stdout.strip()
        stderr = stderr.strip()


        if exit_code != 0:
            h.causal_graph.record_failure(
                reason=stderr or stdout or f"Command exited with code {exit_code}",
                step=h.current_step,
                hint=f"Bash command failed (exit {exit_code}): {command}",
            )
            h.rollback_to(cp.checkpoint_id)
            return (
                f"❌ Command failed (exit {exit_code}) — workspace auto-rolled back.\n"
                f"Command: {command}\n"
                f"stdout:\n{stdout[:2000] or '(empty)'}\n"
                f"stderr:\n{stderr[:2000] or '(empty)'}\n"
                f"🕰️  Rolled back to: {cp.checkpoint_id}"
            )

        return (
            f"✅ Command executed safely.\n"
            f"Command: {command}\n"
            f"Exit code: {exit_code}\n"
            f"stdout:\n{stdout[:4000] or '(empty)'}\n"
            f"🆔 Pre-command checkpoint: {cp.checkpoint_id}\n"
            f"💡 Rollback: ketan_rollback('{cp.checkpoint_id}')"
        )

    except subprocess.TimeoutExpired:
        h.rollback_to(cp.checkpoint_id)
        return (
            f"❌ Command timed out after {timeout_seconds}s — workspace auto-rolled back.\n"
            f"Command: {command}"
        )
    except Exception as e:
        h.rollback_to(cp.checkpoint_id)
        return f"❌ Command crashed — workspace auto-rolled back.\nError: {e}"


# ---------------------------------------------------------------------------
# Tool: Check Invariant (Dry Run)
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_check_invariant(tool_name: str, tool_args_json: str) -> str:
    """
    Run a pre-flight invariant check WITHOUT executing anything.
    Validate a planned action before committing to it.

    Args:
        tool_name: Name of the tool you plan to call (e.g., "write_file", "bash")
        tool_args_json: JSON string of the arguments you plan to pass
    """
    h = _get_harness()
    try:
        tool_args = json.loads(tool_args_json)
    except json.JSONDecodeError as e:
        return f"❌ Invalid JSON in tool_args_json: {e}"

    results = h.verifier.verify_pre_flight(tool_name, tool_args)
    report = []
    all_passed = True
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        line = f"{status} [{r.rule_name}]: {r.message}"
        if not r.passed and r.hint:
            line += f"\n  💡 Fix: {r.hint}"
            all_passed = False
        report.append(line)

    summary = "✅ All invariants passed — safe to proceed." if all_passed else "🚫 Violations detected — do NOT proceed."
    return summary + "\n\n" + "\n".join(report)


# ---------------------------------------------------------------------------
# Tool: Get CTG
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_get_ctg() -> str:
    """
    Get the Causal Trace Graph (CTG) as a Mermaid diagram.
    The CTG is a live DAG showing every tool call, checkpoint, failure,
    and rollback in the session with causal edges between them.
    Paste the output into mermaid.live to visualize it.
    """
    h = _get_harness()
    if not h.causal_graph.nodes:
        return "📊 CTG is empty — no tool executions recorded yet."
    mermaid = h.causal_graph.to_mermaid()
    return f"```mermaid\n{mermaid}\n```"


# ---------------------------------------------------------------------------
# Tool: Explain Failure
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_explain_failure() -> str:
    """
    Get a root-cause explanation of the most recent failure in the CTG.
    Traces the exact execution chain that led to the failure.
    Returns a clean message if no failures exist.
    """
    h = _get_harness()
    failures = h.causal_graph.find_all_failures()
    if not failures:
        return "✅ No failures recorded in this session — all good."
    latest = failures[-1]
    explanation = h.causal_graph.explain_failure(latest.node_id)
    return f"🔍 Latest Failure Root Cause:\n\n{explanation}"


# ---------------------------------------------------------------------------
# Tool: Observe Belief
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_observe_belief(subject: str, predicate: str, value: str, confidence: float = 1.0) -> str:
    """
    Record a factual observation into the Epistemic Belief Engine.
    The engine tracks beliefs about the workspace and detects contradictions
    (e.g., "tests pass" followed by "tests fail") to prevent hallucination loops.

    Args:
        subject: What the belief is about (e.g., "tests/test_main.py")
        predicate: The relationship (e.g., "exists", "passes", "contains_bug")
        value: The observed value (e.g., "true", "false", "syntax_error")
        confidence: Confidence level 0.0–1.0 (default 1.0)
    """
    h = _get_harness()
    event = h.epistemic_engine.observe_raw(
        subject=subject,
        predicate=predicate,
        value=value,
        confidence=confidence,
    )
    if event:
        return (
            f"⚠️  Contradiction Detected!\n"
            f"Prior belief: {event.expected_value!r}\n"
            f"New belief:   {event.observed_value!r} (confidence {confidence})\n"
            f"Subject: {subject} → {predicate}\n"
            f"💡 Epistemic Engine updated to the newer observation."
        )
    return f"✅ Belief recorded: {subject} → {predicate} = {value!r} (confidence {confidence})"


# ---------------------------------------------------------------------------
# Tool: List Beliefs
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_list_beliefs() -> str:
    """
    List all active beliefs tracked by the Epistemic Belief Engine.
    These are facts observed about the workspace during this session.
    """
    h = _get_harness()
    beliefs = [
        {
            "subject": b.subject,
            "predicate": b.predicate,
            "value": b.object_val,
            "confidence": b.confidence,
            "valid": b.is_valid,
        }
        for b in h.epistemic_engine.beliefs.values()
    ]
    return json.dumps({"beliefs": beliefs, "total": len(beliefs)}, indent=2)


# ---------------------------------------------------------------------------
# Tool: Read File
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_read_file(filepath: str) -> str:
    """
    Read a file from the workspace via Ketan Sandbox Engine.
    Also records its existence as a belief in the Epistemic Belief Engine.

    Args:
        filepath: Path relative to workspace root (e.g., "src/main.py")
    """
    h = _get_harness()
    try:
        content = h.sandbox.read_file(filepath)
        h.epistemic_engine.observe_raw(subject=filepath, predicate="exists", value="true")
        return content
    except Exception as e:
        return f"❌ Failed to read file: {e}"


# ---------------------------------------------------------------------------
# Tool: List Files
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_list_files(subdirectory: str = "") -> str:
    """
    List all tracked workspace files via Ketan ShadowFS Engine.

    Args:
        subdirectory: Optional subdirectory relative to workspace root (default: root)
    """
    h = _get_harness()
    states = h.shadow_fs.scan_state()
    files = []
    prefix = subdirectory.strip("/") + "/" if subdirectory.strip("/") else ""
    
    for rel_p, st in states.items():
        if not prefix or rel_p.startswith(prefix):
            files.append({"path": rel_p, "size_bytes": st.size})
            
    return json.dumps({"files": sorted(files, key=lambda x: x["path"]), "total": len(files)}, indent=2)



# ---------------------------------------------------------------------------
# Tool: Session Summary
# ---------------------------------------------------------------------------

@mcp.tool()
def ketan_session_summary() -> str:
    """
    Get a complete markdown summary of the Ketan-OS session:
    steps taken, checkpoints created, failures recorded, beliefs tracked.
    """
    h = _get_harness()
    failures = h.causal_graph.find_all_failures()
    beliefs = list(h.epistemic_engine.beliefs.values())

    lines = [
        "# Ketan-OS 🪔 Session Summary",
        "",
        f"**Workspace**: `{h.workspace_dir}`",
        f"**Steps Executed**: {h.current_step}",
        f"**Checkpoints Created**: {len(h.ledger.checkpoints)}",
        "",
        "## Causal Trace Graph",
        f"- Total Nodes: {len(h.causal_graph.nodes)}",
        f"- Total Edges: {len(h.causal_graph.edges)}",
        f"- Failures Recorded: {len(failures)}",
    ]

    if failures:
        lines.append("\n### Failures:")
        for f in failures[-5:]:
            lines.append(f"  - `{f.node_id}`: {f.label} [{f.status.value}]")

    lines += [
        "",
        "## Epistemic Beliefs",
        f"- Active Beliefs: {len([b for b in beliefs if b.is_valid])}",
        f"- Pruned Beliefs: {len([b for b in beliefs if not b.is_valid])}",
    ]

    if beliefs:
        lines.append("\n### Active Beliefs (sample):")
        for b in [b for b in beliefs if b.is_valid][:10]:
            lines.append(f"  - `{b.subject}` → `{b.predicate}` = `{b.object_val}` (conf {b.confidence})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ketan-OS MCP Server for Claude Code")
    parser.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="Workspace directory to protect (default: current working directory)",
    )
    args, _ = parser.parse_known_args()

    ws_path = Path(args.workspace).resolve()
    log.info(f"Starting Ketan-OS MCP Server | workspace: {ws_path}")

    ws_path.mkdir(parents=True, exist_ok=True)
    global _harness
    if _harness is not None:
        _harness.cleanup()
    _harness = KetanHarness(str(ws_path))
    log.info("Ketan-OS harness ready. Listening on stdio for MCP connections.")


    if hasattr(mcp, "run"):
        mcp.run(transport="stdio")
    elif hasattr(mcp, "run_stdio_async"):
        asyncio.run(mcp.run_stdio_async())
    else:
        mcp.run()


if __name__ == "__main__":
    main()
