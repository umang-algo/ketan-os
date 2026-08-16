# Ketan-OS 🪔 (केतन)
### The Transactional Runtime for AI Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-21%20passed-brightgreen.svg)](tests/)
[![MCP](https://img.shields.io/badge/Claude%20Code-FastMCP%20Ready-blueviolet.svg)](ketan/mcp/server.py)
[![ketan-os MCP server](https://glama.ai/mcp/servers/umang-algo/ketan-os/badges/score.svg)](https://glama.ai/mcp/servers/umang-algo/ketan-os)
[![M8ven Score](https://m8ven.ai/badge/mcp/umang-algo-ketan-os-1k4rg0)](https://m8ven.ai/mcp/umang-algo-ketan-os-1k4rg0)

---

## 🔱 Origin & Philosophy

> *"Aham ātmā guḍākeśa sarva-bhūtāśaya-sthitaḥ"*  
> — **Bhagavad Gita, Chapter 10, Verse 20**  
>  
> *"I am the Self, O Gudakesha, seated in the hearts of all beings.  
> I am the beginning, the middle, and the end of all beings."*  

**Ketan (केतन)** literally means *Banner, Beacon, or Dwelling* in Sanskrit — the fixed, unmovable point of reference from which all navigation begins.

AI agents perform complex, multi-step actions across files, commands, and external tools — but they lack **transaction semantics**. When an agent writes a malformed file, executes a destructive shell command, or acts on stale assumptions, standard agent frameworks have no rollback mechanism.

**Ketan-OS provides the transactional substrate for AI agents**:
```text
BEGIN  →  CHECKPOINT  →  VERIFY  →  COMMIT / ROLLBACK / COMPENSATE
```

By wrapping tool execution in content-addressed state snapshotting, canonical path isolation, pre-flight assertion guards, causal execution provenance, and prompt contradiction pruning, Ketan-OS makes agent tool execution safe, reversible, and debuggable.

---

## 🌟 4 Core Architectural Subsystems

| Subsystem | Component | What Ketan-OS Does |
|:---|:---|:---|
| **1. Transactional Workspace Recovery** | `KetanShadowFS` | Takes incremental, content-addressed workspace snapshots using SHA-256 blob deduplication (`blobs/<sha256>`). Reverts tracked regular workspace files to clean checkpoints. |
| **2. Multi-Layer Pre-Flight Guards** | `InvariantVerifier` | Enforces strict workspace canonical path isolation (`is_relative_to(workspace_root)`), blocks symlink traversal escapes, checks Python AST syntax, and filters destructive shell patterns. |
| **3. Causal Execution Provenance DAG** | `KetanTraceGraph` | Records tool calls, checkpoints, failures, and rollbacks into a directed acyclic graph (DAG). On failure, automatically traverses the DAG backwards to explain the execution lineage. |
| **4. State Belief & Fact Store** | `EpistemicBeliefEngine` | Tracks factual assertions about workspace state. Uses type coercion (`_values_are_equivalent`) to prevent false positives and auto-prunes contradicted prompt assumptions. |

---

## 🛡️ Side-Effect Reversibility Matrix

Ketan-OS tracks tool operations across three distinct transaction recovery tiers:

| System / Target | Reversibility Tier | Recovery Strategy |
|:---|:---:|:---|
| **Local Workspace Files** | `REVERSIBLE` | Automatic content-addressed state rollback via `KetanShadowFS` |
| **Git Repositories** | `REVERSIBLE` | Automated workspace restore / branch checkpoint reversion |
| **PostgreSQL / SQL Databases** | `COMPENSATABLE` | Inverse transaction query or registered compensation handler |
| **S3 / Blob Storage** | `COMPENSATABLE` | Object versioning rollback or compensation handler |
| **GitHub / AWS / Infrastructure** | `COMPENSATABLE` | Registered API inverse call (e.g. close issue, delete resource) |
| **External Network APIs / Email** | `IRREVERSIBLE` | Pre-execution policy check & counterfactual failure hint |

---


## 🏗️ System Architecture

```mermaid
graph TD
    subgraph AgentLayer [" 🤖 Agent Execution Layer "]
        LLM["LLM Agent Loop
        OpenAI • Claude • LangGraph • AutoGen"]
        MCP["🔌 FastMCP Server
        Claude Code Integration"]
        Wrapper["🛡️ KetanAgentWrapper
        Tool Call Interceptor"]
        LLM -->|Tool Call| Wrapper
        MCP -->|Safe Tool Execution| Wrapper
    end

    subgraph CoreEngine [" 🪔 Ketan-OS Transactional Substrate "]
        Harness["🪔 KetanHarness
        Thread-Safe Coordinator"]

        subgraph PreFlight [" Pre-Flight Guard Layer "]
            Verifier["🛡️ InvariantVerifier
            Canonical Path Confinement
            Symlink Guard + AST & Safety Rules"]
        end

        subgraph StorageLedger [" Dual-Ledger Substrate "]
            Ledger["📋 KetanLedger
            Checkpoint & Reversibility Registry"]
            ShadowFS["💾 KetanShadowFS
            Content-Addressed Workspace Recovery"]
            Ledger --> ShadowFS
        end

        subgraph Cognition [" State Belief Layer "]
            Epistemic["🧠 EpistemicBeliefEngine
            Runtime Fact Store &
            Prompt Contradiction Pruning"]
        end

        subgraph CTGSubsystem [" Causal Provenance Engine "]
            CTG["🧬 KetanTraceGraph
            Causal Execution Provenance DAG"]
            RCA["🔍 Provenance Analyzer
            Execution Lineage Explanation"]
            CTG --> RCA
        end

        subgraph TimeTravel [" Transaction Recovery "]
            Rollback["⏱️ Rollback Controller
            Workspace State Reversion"]
            Counterfactual["💡 Counterfactual Engine
            Diagnostic Hint Injector"]
            Rollback --> Counterfactual
        end
    end

    Wrapper -->|"① Intercept"| Harness
    Harness -->|"② Pre-flight"| Verifier
    Verifier -->|"③ Pre-Flight Pass"| Epistemic
    Epistemic -->|"④ Checkpoint"| ShadowFS
    ShadowFS -->|"⑤ Execute"| Execution["⚙️ Tool Execution"]

    Verifier -.->|Path / Syntax / Safety Fail| Rollback
    Execution -->|Crash / Exception| Rollback

    Execution -->|Success| Commit["🟢 Commit & Record"]
    Commit --> CTG
    Commit --> Ledger

    Rollback -->|"⑥ Revert Workspace"| ShadowFS
    Rollback -->|"⑦ Record Failure Node"| CTG
    Counterfactual -->|"⑧ Inject Hint"| LLM

    classDef agent    fill:#f3e8ff,stroke:#7c3aed,stroke-width:2px,color:#1e1b4b
    classDef core     fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0c4a6e
    classDef storage  fill:#d1fae5,stroke:#059669,stroke-width:2px,color:#064e3b
    classDef rollback fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
    classDef ctg      fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
    classDef exec     fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d

    class LLM,Wrapper,MCP agent
    class Harness,Verifier,Epistemic core
    class Ledger,ShadowFS storage
    class Rollback,Counterfactual rollback
    class CTG,RCA ctg
    class Execution,Commit exec
```

---

## ⚡ Quickstart

```python
from ketan import KetanHarness, KetanAgentWrapper

# 1. Initialize Ketan-OS for your project workspace
harness = KetanHarness(workspace_dir="./my_project")
wrapper = KetanAgentWrapper(harness)

# 2. Wrap any tool with transactional protection
def write_code(args):
    with open(args["filepath"], "w") as f:
        f.write(args["content"])
    return "File written"

safe_write = wrapper.wrap_tool("write_file", write_code)

# 3. Execute — Ketan-OS handles snapshot, pre-flight, rollback automatically
result = safe_write(
    tool_args={"filepath": "main.py", "content": "def run():\n    return 42\n"},
    prompt_stack=[{"role": "user", "content": "Create main function"}]
)
print(result)
# → {"success": True, "result": "File written", "hint": ""}
# If content had a syntax error → {"success": False, "hint": "Fix SyntaxError on line 1..."}
# → workspace auto-rolled back cleanly
```

---

## 🔌 Claude Code FastMCP Integration

Ketan-OS ships a ready-to-use **FastMCP server** that gives Claude Code native tools for safe, transactional, auditable agentic coding.

### 1. Install

```bash
git clone https://github.com/umang-algo/ketan-os.git
cd ketan-os
uv pip install -e .
```

### 2. Configure Claude Code

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "ketan-os": {
      "command": "python",
      "args": ["-m", "ketan.mcp.server", "--workspace", "/absolute/path/to/your/project"]
    }
  }
}
```

---

## 🧪 Running Tests & Benchmarks

```bash
# Run unit test suite
uv run pytest tests/

# Run performance benchmark suite
uv run python examples/benchmark_ketan_performance.py
```

---

## 📜 License

MIT License. Copyright (c) 2026 umang-algo.
