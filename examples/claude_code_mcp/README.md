# Ketan-OS × Claude Code Integration Guide 🪔

This guide shows you how to connect **Ketan-OS** to **Claude Code** via the
Model Context Protocol (MCP) so Claude gets full transactional protection,
time-travel rollback, and invariant guards on every file/command action.

---

## What Claude Code Gets

| Without Ketan-OS | With Ketan-OS MCP |
|---|---|
| File writes are permanent — one mistake corrupts workspace | Atomic rollback in < 1s to any prior checkpoint |
| No insight into why a multi-step task failed | Full CTG DAG with failure root cause explanation |
| Claude can write broken Python to disk | Pre-flight AST guard blocks bad syntax before disk write |
| Repeated workflows cost full tokens every time | JIT trajectory caching for zero-token re-runs |
| No memory contradiction detection | Epistemic engine detects and prunes stale beliefs |

---

## Step 1: Install Ketan-OS with MCP Support

```bash
# After cloning/installing from GitHub — no absolute paths needed
pip install "ketan-os[mcp]"

# Or with uv:
uv pip install "ketan-os[mcp]"
```

This installs the `ketan-mcp` command onto your PATH. That's all you need.

---

## Step 2: Configure Claude Code

Edit (or create) `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "ketan-os": {
      "command": "ketan-mcp",
      "args": ["--workspace", "/absolute/path/to/your/project"]
    }
  }
}
```

Only replace `/absolute/path/to/your/project` with your actual project directory.
**No `--directory` flag. No hardcoded repo paths.** It works the same for everyone who installs from GitHub.

---

## Step 3: Start Claude Code

```bash
claude
```

Claude Code will auto-discover and start the Ketan-OS MCP server.
You'll see `ketan-os` listed in the available tools.

---

## Available MCP Tools (15 Total)

| Tool | Description |
|---|---|
| `ketan_init_workspace` | Switch Ketan-OS to a different workspace directory |
| `ketan_get_status` | Get current ground-truth state: steps, checkpoints, failures |
| `ketan_snapshot` | Take a manual atomic snapshot → get a rollback point |
| `ketan_rollback` | Time-travel revert workspace to any previous checkpoint |
| `ketan_get_checkpoints` | List all available checkpoints |
| `ketan_write_file_safe` | Write a file with pre-flight guards + auto snapshot/rollback |
| `ketan_run_bash_safe` | Run a shell command with snapshot + auto rollback on failure |
| `ketan_check_invariant` | Pre-validate a planned action WITHOUT executing it |
| `ketan_get_ctg` | Get Causal Trace Graph as a Mermaid diagram |
| `ketan_explain_failure` | Get root-cause explanation of the most recent failure |
| `ketan_observe_belief` | Register a factual observation into the Epistemic Engine |
| `ketan_list_beliefs` | List all tracked beliefs about the workspace |
| `ketan_read_file` | Read a file and record it as a belief |
| `ketan_list_files` | List all workspace files |
| `ketan_session_summary` | Full markdown session report |

---

## Example Claude Code Session

```
You: "Refactor src/payment.py and add tests, but make sure nothing breaks"

Claude Code:
  [ketan_snapshot]          ✅ Checkpoint cp_step_1_... created
  [ketan_write_file_safe]   ✅ src/payment.py written (pre-flight passed)
  [ketan_run_bash_safe]     ✅ pytest tests/ → 47 passed
  [ketan_snapshot]          ✅ Final checkpoint created

You: "Actually, revert to before the refactor"
  [ketan_rollback cp_step_1_...] ✅ Workspace rolled back in 8ms
```

---

## Testing the MCP Server Manually

```bash
# Run directly to test (also starts on stdio)
ketan-mcp --workspace /tmp/test_workspace
```

---

## Architecture

```
Claude Code Agent
       │
       │  MCP JSON-RPC (stdio)
       ▼
ketan-mcp  (= python -m ketan.mcp.server)
       │
       ├── ketan_write_file_safe  ──→ InvariantVerifier → KetanShadowFS → disk
       ├── ketan_run_bash_safe    ──→ InvariantVerifier → subprocess → KetanShadowFS
       ├── ketan_snapshot         ──→ KetanShadowFS.create_snapshot()
       ├── ketan_rollback         ──→ KetanShadowFS.restore_snapshot()
       ├── ketan_get_ctg          ──→ KetanTraceGraph.to_mermaid()
       ├── ketan_observe_belief   ──→ EpistemicBeliefEngine.observe_raw()
       └── ketan_session_summary  ──→ full aggregated report
```
