# Configuration and execution

[Documentation index](README.md) · [Quickstart](../README.md#quickstart)

## Model access

Set credentials in the server process environment. The optional dotenv loader reads the package's project root and `~/.gemini/.env`. An explicitly supplied dotenv path loads only that file. Existing nonempty environment values take precedence.

| Backend | Configuration |
| --- | --- |
| Gemini | `GEMINI_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Ollama | Local endpoint and model routing in the [dispatcher](../src/bugarena/tournament/providers/dispatcher.py) |

The dispatcher chooses defaults from available keys. Python callers can configure explicit models; MCP tools do not expose every internal option. Provider tests use mocked transports, so they do not prove that any model name is available today.

Run `python scripts/check_api_keys.py --dry-run` to inspect configuration without provider calls. Live checks and `auto_generate=true` may call configured services. Keep credentials out of committed files.

## Execution boundaries

Default sandboxes are temporary directory copies and execute on the host with filtered environment variables and arguments. They are **not an OS security boundary** for hostile code. Audit probes also execute code; a read-only audit is not a promise of zero execution or zero audit-state writes.

`BUGARENA_SANDBOX_MODE=container` requests Docker or Podman for the sandbox command runner. The command disables networking, drops capabilities and makes the container root filesystem read-only, while mounting temporary `/work` writable. Missing runtimes cause an error. The image must contain the test dependencies; disabled networking prevents fetching them during execution.

Command construction is tested. This review did not validate a live container deployment, nor does this switch establish isolation for every subprocess used by every audit tool.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Server waits silently | Normal for stdio: connect an MCP client |
| Module cannot be imported | Install with the same environment's `python -m pip install -e .` |
| Client cannot start server | Use the absolute executable path |
| No generated candidates | Enable generation, inspect provider errors, or supply diffs |
| Unknown repair ID | Process-local IDs are lost on restart |
| Reproduction cannot be verified | Check supported call expressions, imports and expected result |
| Low score | Inspect disqualification, missing tests and unmeasured metrics |
| Container import failure | Prepare an image with project dependencies |
