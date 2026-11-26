# Tooling & Skills Available (Phase 0.3 Inventory)

Verified against local installation on `d:\MCP server` (`upgrade/bugarena-agents`):

## 1. Installed Agent Plugins & Skills

| Ecosystem | Status | Installed Components Used |
| :--- | :--- | :--- |
| **ECC (`ecc`)** | Available (`71` agents, extensive skills) | `loop-operator`, `architect`, `code-architect`, `security-reviewer`, `silent-failure-hunter`, `python-reviewer`, `code-reviewer`, `pr-test-analyzer`, `type-design-analyzer`, `comment-analyzer`, `performance-optimizer`, `agent-evaluator`, `planner`, `tdd-guide`, `code-explorer`, `spec-miner` |
| **Superpowers (`superpowers`)** | Available (`15` skills) | `brainstorming`, `writing-plans`, `executing-plans`, `test-driven-development`, `subagent-driven-development`, `dispatching-parallel-agents`, `systematic-debugging`, `using-git-worktrees`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch` |
| **Ponytail (`ponytail`)** | Available (`6` skills) | `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help` (minimal-diff discipline, debt comments, risk/skip reporting) |
| **Context Mode (`context-mode`)** | Available (`4` skills + MCP tools) | `ctx_execute`, `ctx_batch`, `ctx_search`, `ctx_index`, `ctx_resume`, `ctx_stats` |
| **Chrome DevTools Plugin** | Available (`chrome-devtools-plugin`) | Reference skills (`a11y-debugging`, `memory-leak-debugging`, `troubleshooting`) |

## 2. Host Browsers Detected (Phase 0 Probe)

| Browser | Status | Path |
| :--- | :--- | :--- |
| **Google Chrome** | Detected | `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| **Brave Browser** | Detected | `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe` |
| **Helium** | Not auto-detected | Not found in `%LOCALAPPDATA%\imput\Helium`, `%LOCALAPPDATA%\Helium`, `C:\Program Files\Helium`, or `PATH` (ask user for explicit path when Helium is requested) |

## 3. Environment Keys Present (Names Only — Values Never Read/Printed)

| Variable | Present in `.env` | Provider Route |
| :--- | :---: | :--- |
| `GEMINI_API_KEY` | Yes | Google Gemini (`generativelanguage.googleapis.com`) |
| `GROQ_API_KEY` | Yes | Groq (`api.groq.com`) |
| `XAI_API_KEY` | No | xAI Grok (`api.x.ai/v1/chat/completions`) — wired with graceful error/missing-key notice |
| `OPENAI_API_KEY` | No | OpenAI (`api.openai.com`) |
| `DEEPSEEK_API_KEY` | No | DeepSeek (`api.deepseek.com`) |

## 4. Python Environment (`.venv`)
- Python 3.14.0 (`mcp 2.3.0`, `pydantic 2.14.3`, `httpx 0.28.1`, `radon 6.0.1`, `ruff 0.17.5`, `pytest 9.2.0`, `pytest-asyncio 1.5.0`, `jsonschema 4.26.0`, `cryptography 50.0.2`).
- Note: `playwright`, `websockets`, `pillow`, and `weasyprint` are not installed; browser CDP WebSocket, Chromium `Page.printToPDF` PDF export, and Chromium screenshot annotation use stdlib RFC 6455 WebSocket + Chromium DevTools Protocol directly without adding unrequested third-party runtime dependencies.
