# Multi-Agent MVP Demo Runbook (2-minute)

## Goal
Demonstrate the complete Codex multi-agent contract-governance flow in one repeatable run:
- isolated role workspaces
- protocol drift introduced by Implementer-A
- watcher gate blocks integration on mismatch
- Implementer-B resolves drift
- gate passes and PR packet is emitted

## Scope constraints for this demo
- Single protocol component pair only:
  - `codex-rs/app-server-protocol`
  - `codex-rs/app-server`
- Single contract artifact:
  - `contracts/app-schema.expected.json`
- Contract gate is hard: no final merge-ready packet while status is `FAIL`
- Required packet artifacts under `artifacts/pr-packets/<run-id>/`:
  - `diff.patch`
  - `test-logs.txt`
  - `contract-check.json`
  - `contract-check.diff.txt`
  - `impact-report.json`
  - `summary.md`

## Fast run path (required, deterministic)
Use run id:

```text
run-2026-02-28-mvp
```

Recommended single command:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-mvp-demo.ps1
```

## Exact command sequence and expected outcomes

1) Planner publish (visibility only)
- `Get-Content artifacts\coordination\run-2026-02-28-mvp\intent.json`
- `Get-Content artifacts\coordination\run-2026-02-28-mvp\impact-planner.json`
- Expected: two files exist and include run metadata/scope/pass criteria.

2) Implementer-A run
- `Set-Location <worktree>/impl-a`
- `git status --short`
- `cargo test -p codex-app-server-protocol schema_fixtures_match_generated`
- `cargo run -p codex-app-server-protocol --bin write_schema_fixtures -- --schema-root artifacts/tmp-schema-run`
- `git diff --name-only -- codex-rs/app-server-protocol/src/protocol/v2.rs`
- Expected: only the scoped protocol file appears in scope diff and fixture test passes.

3) Implementer-B run
- `Set-Location <worktree>/impl-b`
- `git status --short`
- `git diff --name-only -- contracts/app-schema.expected.json`
- Expected: only the pinned contract file was touched in that scope.

4) Integrator merge + gate FAIL (drift induced)
- `Set-Location <worktree>/integrator`
- `git merge mvp/impl-a --no-edit`
- `node scripts/multiagent/contract-check.mjs --run-id run-2026-02-28-mvp`
- Expected: command exits `1`, and:
  - `artifacts/pr-packets/run-2026-02-28-mvp/contract-check.json` shows `status=FAIL`
  - `artifacts/pr-packets/run-2026-02-28-mvp/contract-check.diff.txt` contains a JSON diff
  - integration considered BLOCKED

5) Integrator merge + gate PASS (drift resolved)
- `git merge mvp/impl-b --no-edit`
- `node scripts/multiagent/contract-check.mjs --run-id run-2026-02-28-mvp`
- Expected: command exits `0`, and:
  - `contract-check.json` shows `status=PASS`
  - `contract-check.diff.txt` is empty or reduced to metadata-only diff
  - integration unblocked

6) Packet generation
- `node scripts/multiagent/generate-pr-packet.mjs --run-id run-2026-02-28-mvp`
- Expected: return code `0` and all six required PR packet files created.

7) Artifact verification
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\diff.patch`
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\test-logs.txt`
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\contract-check.json`
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\contract-check.diff.txt`
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\impact-report.json`
- `Test-Path artifacts\pr-packets\run-2026-02-28-mvp\summary.md`
- Expected: all six files exist.

## Deterministic acceptance checklist

- FAIL→PASS gate transitions
  - Contract check must first report `FAIL` after `impl-a` merge.
  - Contract check must report `PASS` after `impl-b` merge.
- Scoped file changes only
  - Before packet generation, confirm no unrelated file edits beyond allowed paths.
  - Planner run should touch only `artifacts/coordination` files.
  - Implementer-A run should only modify protocol source path.
  - Implementer-B run should only modify `contracts/app-schema.expected.json`.
- Required packet completeness
  - all six files listed above exist in `artifacts/pr-packets/run-2026-02-28-mvp/`.
- Blocker evidence present
  - `summary.md` must explicitly show why merge was blocked in FAIL phase and show unblocked READY state in PASS phase.
- End-to-end timing target
  - Command sequence must be replayable end-to-end in ~2 minutes by one operator.

## Scope and file boundaries
- Planner scope: `artifacts/coordination/*`
- Implementer-A scope: `codex-rs/app-server-protocol/src/protocol/v2.rs`
- Implementer-B scope: `contracts/app-schema.expected.json`
- Watcher/Integrator scope: `scripts/multiagent/*`, `artifacts/*`

## Script reference

- `scripts/run-mvp-demo.ps1`
  - Replays the full flow, validates each checkpoint, and errors if sequence cannot complete.
  - Fails early if any required worktree/artifact path is missing.
  - Performs the exact sequence above with pass/fail assertions.

## Optional manual fallback (if needed)

If you cannot run the automation script, execute the exact commands in section **Exact command sequence** directly in separate terminals for each role path:

- `C:\Users\User\Desktop\Codingyay\codex-worktrees\planner`
- `C:\Users\User\Desktop\Codingyay\codex-worktrees\impl-a`
- `C:\Users\User\Desktop\Codingyay\codex-worktrees\impl-b`
- `C:\Users\User\Desktop\Codingyay\codex-worktrees\integrator`

The same command order and expected outcomes above are the acceptance standard.
