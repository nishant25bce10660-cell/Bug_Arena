# BugArena MCP

**Autonomous Bug Lifecycle & Multi-Agent Repair Arena**

BugArena MCP is a Model Context Protocol (MCP) server that elevates autonomous software repair from single-shot LLM prompts into a **verifiable, multi-agent competitive tournament**.

Rather than trusting a single LLM patch proposal, BugArena executes a rigorous 5-stage repair lifecycle:
1. **Bug Discovery & Triage**: Analyzes runtime error logs and stack traces, maps frames to AST scopes, and pinpoints suspect locations.
2. **Deterministic Reproduction Synthesis**: Synthesizes a minimal reproduction test script and executes it inside an isolated ephemeral sandbox to verify the **Red** baseline (fails on the unpatched codebase).
3. **Multi-Agent Repair Tournament**: Dispatches parallel, heterogeneous bug-fixing personas (*Surgical Minimalist*, *Defensive Guardian*, *Deep Architectural Fixer*, *Contract Enforcer*) to generate competing candidate patches.
4. **Sandboxed Verification & Multi-Dimensional Scoring**: Evaluates each patch in an ephemeral sandbox against reproduction tests, regression suites, cyclomatic complexity deltas, and code churn.
5. **Champion Selection & Report Generation**: Automatically crowns the patch with the highest verified accuracy and generates an actionable diagnostic report with git-compatible diffs.

---

## Architecture & Subsystems

```
                                  +----------------------------+
                                  |     MCP Client Layer       |
                                  |  (Cursor / Claude Desktop) |
                                  +--------------+-------------+
                                                 |
                                                 v
                                  +----------------------------+
                                  |   BugArena MCP Server      |
                                  |   (MCPServer Python SDK)   |
                                  +--------------+-------------+
                                                 |
         +--------------------+------------------+------------------+--------------------+
         |                    |                                     |                    |
         v                    v                                     v                    v
+------------------+ +------------------+                 +------------------+ +------------------+
|   Bug Discovery  | |  Repro Test      |                 | Multi-Agent Fix  | | Verification &   |
|   & AST Analysis | |  Synthesizer     |                 | Arena Tournament | | Scoring Engine   |
+------------------+ +------------------+                 +------------------+ +------------------+
         |                    |                                     |                    |
         +--------------------+------------------+------------------+--------------------+
                                                 |
                                                 v
                                  +--------------------------------------------+
                                  |         Ephemeral Sandbox Manager          |
                                  | (Temp-dir host copy + env/arg allowlist;   |
                                  |  optional docker/podman --network=none)    |
                                  +--------------------------------------------+
```

> **Security Note:** By default on hosts without container mode active (`BUGARENA_SANDBOX_MODE=container`), sandboxes copy files into an ephemeral temp directory and execute tests on the host with sanitized env/args rather than OS container jails. Configure Docker/Podman (`isolation_mode="container"`) for `--network=none --read-only --cap-drop=ALL` enforcement.

---

## MCP Tools

| Tool | Description | Inputs |
| :--- | :--- | :--- |
| `bug_detect` | Locates suspect lines & AST scopes from stack traces | `repo_path`, `error_log`, `hint` |
| `bug_reproduce` | Synthesizes and asserts a failing reproduction test | `repo_path`, `suspect_file`, `bug_description`, `call_expr`, `expected_behavior` |
| `agent_fix_tournament` | Registers and validates competing agent candidate patches | `repo_path`, `repro_test_file`, `candidate_patches_raw` |
| `evaluate_patches` | Executes sandbox verification, regression checks, and scores patches | `repo_path`, `tournament_id`, `repro_test_file`, `repro_code` |
| `generate_fix_report` | Formats tournament leaderboard, markdown report, or git unified diff | `tournament_id`, `format` (`markdown`, `json`, `diff`) |
| `bugarena_autonomous_repair` | Composite end-to-end autonomous repair workflow | `repo_path`, `error_log`, `bug_description`, `candidate_patches_raw` |

---

## Scoring & Gating Formula

Candidate patches undergo **Hard Disqualification Gating**:
1. **Red-to-Green Gate**: Reproduction test must pass.
2. **Zero Regression Gate**: Regressions count in existing test suites must be 0.
3. **Syntax & AST Gate**: Patch must produce valid, parsable syntax.

For non-disqualified patches, composite accuracy score $S(p) \in [0, 100]$ is computed as:
$$S(p) = 40 \cdot R(p) + 30 \cdot (1 - \text{regressions}/\text{total}) + 15 \cdot Q_{\text{churn}}(p) + 10 \cdot Q_{\text{complexity}}(p) + 5 \cdot Q_{\text{mutation}}(p)$$

Where:
- $Q_{\text{churn}} = \max(0, 1 - \text{lines\_changed}/50)$ (rewards surgical fixes)
- $Q_{\text{complexity}} = \max(0, 1 - \max(0, \Delta CC)/10)$ (rewards algorithmic simplicity)

---

## Installation & Quickstart

### Prerequisites
- Python 3.11+
- Git

### Setup
```bash
# Clone and create virtual environment
python -m venv .venv
.\.venv\Scripts\activate      # Windows
# source .venv/bin/activate   # Linux/macOS

# Install dependencies
pip install -e .
```

### Run Tests
```bash
pytest -v
```

### Run MCP Server
```bash
python -m bugarena.server
```

### Claude Desktop / Cursor MCP Configuration
Add the server to your `claude_desktop_config.json` or Cursor MCP settings:
```json
{
  "mcpServers": {
    "bugarena": {
      "command": "D:/MCP server/.venv/Scripts/python.exe",
      "args": ["-m", "bugarena.server"]
    }
  }
}
```

---

## License
MIT License.
