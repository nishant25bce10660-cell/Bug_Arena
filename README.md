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
| `agent_fix_tournament` | Registers and validates competing agent candidate patches (with optional LLM dispatch) | `repo_path`, `repro_test_file`, `candidate_patches_raw`, `auto_generate` |
| `evaluate_patches` | Executes sandbox verification, regression checks, AST delta, and scores patches | `repo_path`, `tournament_id`, `repro_test_file`, `repro_code` |
| `generate_fix_report` | Formats tournament leaderboard, markdown report, or git unified diff | `tournament_id`, `format` (`markdown`, `json`, `diff`) |
| `generate_bug_report` | Generates and saves a standalone bug diagnostic markdown report | `repo_path`, `error_log`, `hint`, `output_file` |
| `bugarena_autonomous_repair` | Composite end-to-end autonomous repair workflow | `repo_path`, `error_log`, `bug_description`, `candidate_patches_raw` |
| `audit_start` | Initializes a read-only multi-agent audit run and module coverage matrix | `repo_path`, `mode`, `max_rounds` |
| `audit_round` | Executes one parallel specialist detection, deduplication, and probe round | `run_id`, `auto_generate` |
| `audit_status` | Returns round ledger counts, module coverage %, and stop-condition status | `run_id` |
| `finding_verify` | Runs independent adversarial verification on an audit finding | `run_id`, `finding_id` |
| `audit_report` | Renders evidence-graded audit report markdown with root-cause clusters and appendices | `run_id`, `format`, `output_file` |
| `fix_loop_start` | Executes test-first remediation across confirmed findings in an audit ledger | `run_id`, `dry_run`, `auto_generate` |

---

## Scoring & Gating Formula

Candidate patches undergo **Hard Disqualification Gating**:
1. **Red-to-Green Gate**: Reproduction test must fail on baseline (`exit_code == 1`) and pass after patch.
2. **Zero Regression Gate**: Regressions count in existing test suites must be 0.
3. **Syntax & AST Gate**: Modified Python files must produce valid, parsable AST syntax without path traversal.

For non-disqualified patches, composite accuracy score $S(p) \in [0, 100]$ is computed as:
$$S(p) = 40 \cdot R(p) + 30 \cdot Q_{\text{reg}}(p) + 15 \cdot Q_{\text{churn}}(p) + 10 \cdot Q_{\text{complexity}}(p) + 5 \cdot Q_{\text{mutation}}(p)$$

Where:
- $Q_{\text{reg}} = 1 - \text{regressions}/\text{total}$ when $\text{total\_regressions\_checked} > 0$, else $0$
- $Q_{\text{churn}} = \max(0, 1 - \text{lines\_changed}/50)$ (rewards surgical fixes)
- $Q_{\text{complexity}} = \max(0, 1 - \max(0, \Delta CC)/10)$ (rewards algorithmic simplicity)
- $Q_{\text{mutation}} = \text{mutation\_kill\_ratio}$ when measured, else $0$

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
      "command": "<path-to-repo>/.venv/Scripts/python.exe",
      "args": ["-m", "bugarena.server"]
    }
  }
}
```

---

## License
MIT License.
