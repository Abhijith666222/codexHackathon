# Codex Multi-Agent Dashboard (`codex-multi`)

`codex-multi` is a lightweight orchestration wrapper that runs Codex in a planner + worker flow and shows a live terminal view of agent state.

By default, it now prefers your system `codex` binary first so existing model/provider defaults (including Claude-based setups) are preserved.

## Command

- Run the orchestrator:
  - POSIX shells: `./codex-multi run "<task>"`
  - Windows cmd/PowerShell: `.\codex-multi.bat run "<task>"`
  - Optional run id: `./codex-multi run "<task>" --run-id my-run-001`
  - Optional sandbox mode: `--agent-sandbox workspace-write` (default: `workspace-write`)
  - Optional task mode: `--task-mode auto|code|advisory` (default: `auto`)
  - Optional model override: `--model <model-name>`
  - Optional model provider override: `--model-provider <provider-key>`
  - Local dashboard UI (recommended for live interaction): `--ui web`
    - Local dashboard port: `--port 8765`
  - Optional default sandbox env:
    - Windows: `set CODEX_MULTI_SANDBOX_MODE=workspace-write`
    - macOS/Linux/WSL: `export CODEX_MULTI_SANDBOX_MODE=workspace-write`
  - Optional model envs:
    - Windows: `set CODEX_MULTI_MODEL=...` and `set CODEX_MULTI_MODEL_PROVIDER=...`
    - macOS/Linux/WSL: `export CODEX_MULTI_MODEL=...` and `export CODEX_MULTI_MODEL_PROVIDER=...`
  - Optional explicit codex command:
    - Windows: `set CODEX_MULTI_CODEX_COMMAND=codex`
    - macOS/Linux/WSL: `export CODEX_MULTI_CODEX_COMMAND=\"codex\"`

- Built-in quick demo:
  - POSIX shells: `./codex-multi demo`
  - Windows cmd/PowerShell: `.\codex-multi.bat demo`

- Inspect a completed run:
  - POSIX shells: `./codex-multi inspect run-2026-02-28-080012`
  - Windows cmd/PowerShell: `.\codex-multi.bat inspect run-2026-02-28-080012`

- Portable fallback:
  - `python .\codexHackathon\codex-multi run "<task>"`
  - `python .\codexHackathon\tools\codex-multi\inspect_run.py <run-id>`

## What it creates

For each run:

- `artifacts/coordination/<run-id>/`
  - `<agent>/intent.json`
  - `<agent>/status.json`
  - `<agent>/impact-report.json`
  - `<agent>/blocker.json` (if blocked)

- `artifacts/pr-packets/<run-id>/`
  - `diff.patch`
  - `test-logs.txt`
  - `contract-check.json`
  - `contract-check.diff.txt`
  - `impact-report.json`
  - `summary.md`

## Run examples

- Original request style:
  - `./codex-multi run "Implement feature X with tests" --agent-sandbox workspace-write`
  - `./codex-multi run "Implement feature X with tests" --run-id demo-123`
  - `./codex-multi run "Implement feature X with tests" --model claude-3-7-sonnet`
  - `./codex-multi run "Implement feature X with tests" --ui web --port 8765`
- Browser-started request style:
  - `./codex-multi run --ui web --port 8765`
  - Open the provided URL and submit your task from the dashboard composer form.
- Advisory request style (checklists/plans, no file changes required):
  - `./codex-multi run "Give me a list of steps to plan this feature" --task-mode advisory`

- Deterministic demo:
  - `./codex-multi demo`

## Runtime behavior

The run does four things:

1) Planner step
- Runs one planner Codex pass to split the task into named subtasks with scopes.

2) Worker steps
- Creates one git worktree per sub-agent:
  - `codex-worktrees/<run-id>/<agent>`
- Runs one Codex exec process per agent with `--json` and `--sandbox workspace-write|read-only|danger-full-access`.
- Tracks state as QUEUED/RUNNING/BLOCKED/DONE.
- In `advisory` mode, agents default to read-only execution and focus on guidance output instead of file edits.

3) Gate checks
- Verifies required artifacts exist.
- Validates planner non-overlapping scope rules.
- Normalizes overlapping planner scopes to deterministic disjoint paths if needed.
- Adds a planner recovery pass if planner output is malformed, retriable, or falls back to a single broad agent.
- Performs dry-run mergeability check by applying per-agent patches into a temporary worktree.

4) Packet generation
- Always generates `artifacts/pr-packets/<run-id>/summary.md` and evidence files.
- Exits non-zero when any gate fails (blocked).

### Web dashboard mode

- Run command:
  - `./codex-multi run "<task>" --ui web`
  - Optionally pin port with `--port <port>`
- Open:
  - `http://127.0.0.1:8765` (or your specified port).
- Web mode shows planner decomposition, active assignments, per-agent status, and latest messages in one page while still writing artifacts for TUI output.
- The web prompt composer supports both implementation and advisory prompts.
- The dashboard UI template is `web_dashboard.html`; edit this file to match your preferred look-and-feel.

## Troubleshooting parallelism and expected one-agent runs

- If you see only one agent for a task that should decompose into many subtasks:
  - Check `artifacts/coordination/<run-id>/planner/intent.json`.
  - If `plannerParseAttempts` is `1` and `fallbackUsed` is `true`, retry the same run command once; planner output was not parseable in strict shape.
  - If `plannerParseAttempts > 1` and `fallbackUsed` stays `true`, inspect `planner/last-message.txt` and re-run with a stronger task phrasing.

- If an agent gets blocked with a reconnect/stream disconnect message:
  - the orchestrator now retries that agent up to 3 times automatically.
  - check `agent-*/status.json` `blockerReason` values for final decision if retries are exhausted.

- When a run is blocked, the blocker reason is available in these exact files:
  - `artifacts/coordination/<run-id>/impact-report.json` (`agents[].blockerReason`).
  - `artifacts/coordination/<run-id>/<agent>/blocker.json` (canonical message for each blocked agent).
  - `artifacts/pr-packets/<run-id>/summary.md` includes a `Status: BLOCKED` section with explicit reasons.
  - `artifacts/pr-packets/<run-id>/contract-check.json` for contract errors/hashes.
  - For `code` mode only: no-op agent runs are treated as blocked with `No file changes were produced; execution was blocked or task was not executed.`

- Parallelism is enabled by default:
  - every worker is launched as a separate thread immediately after workspace setup.
  - if one worker is delayed, others continue independently; dashboard refresh remains live while all workers execute.

- One-command blocker inspect:
  - `./codex-multi inspect <run-id>`

## Requirements

- Python 3.10+
- Git
- Either:
  - built local `codex` binary, or
  - `cargo` + repo built target access, or
  - `codex` on PATH.
- Node.js for contract check step (optional but preferred).

To run the local repo CLI directly:
- `cd codex-rs`
- `cargo build -p codex-cli`
- `./codex-multi` will then pick up `codex-rs/target/debug/codex` automatically.
