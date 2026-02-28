# PR Packet Summary

Run ID: smoke-2026-02-28-writecheck
Overall state: BLOCKED

## Evidence
- artifacts/pr-packets/smoke-2026-02-28-writecheck/diff.patch
- artifacts/pr-packets/smoke-2026-02-28-writecheck/test-logs.txt
- artifacts/pr-packets/smoke-2026-02-28-writecheck/contract-check.json
- artifacts/pr-packets/smoke-2026-02-28-writecheck/contract-check.diff.txt
- artifacts/pr-packets/smoke-2026-02-28-writecheck/impact-report.json
- artifacts/pr-packets/smoke-2026-02-28-writecheck/summary.md

Status: BLOCKED
- No agent produced any file changes.
- agent-ui-shell BLOCKED: No file changes were produced; execution was blocked or task was not executed.
- Evidence: artifacts/coordination/smoke-2026-02-28-writecheck/agent-ui-shell/blocker.json
- agent-task-components BLOCKED: No file changes were produced; execution was blocked or task was not executed.
- Evidence: artifacts/coordination/smoke-2026-02-28-writecheck/agent-task-components/blocker.json
- agent-styling BLOCKED: No file changes were produced; execution was blocked or task was not executed.
- Evidence: artifacts/coordination/smoke-2026-02-28-writecheck/agent-styling/blocker.json
- agent-state-data BLOCKED: No file changes were produced; execution was blocked or task was not executed.
- Evidence: artifacts/coordination/smoke-2026-02-28-writecheck/agent-state-data/blocker.json
- contract check failed
- Contract details: artifacts/pr-packets/smoke-2026-02-28-writecheck/contract-check.json
- expected hash: 7676abc91b268e97c20529182c4fa8b85a39124b70380b671137db8bb588274f
- generated hash: 22aa225404e67ef7bc8fa5afa9fc30768b3bf5e79053844d2cc73084f4cc6f94
- command: cargo run -p codex-app-server-protocol --bin write_schema_fixtures -- --schema-root artifacts/pr-packets/smoke-2026-02-28-writecheck/generated-schema
- contract exitCode: 1
