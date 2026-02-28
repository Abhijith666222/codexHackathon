# PR Packet Summary

Run ID: smoke-2026-02-28-bypass-simple
Overall state: BLOCKED

## Evidence
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/diff.patch
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/test-logs.txt
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/contract-check.json
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/contract-check.diff.txt
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/impact-report.json
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple/summary.md

Status: BLOCKED
- agent-implementation BLOCKED: Agent exited with non-zero status.
- Evidence: artifacts/coordination/smoke-2026-02-28-bypass-simple/agent-implementation/blocker.json
- contract check failed
- Contract details: artifacts/pr-packets/smoke-2026-02-28-bypass-simple/contract-check.json
- expected hash: 7676abc91b268e97c20529182c4fa8b85a39124b70380b671137db8bb588274f
- generated hash: 22aa225404e67ef7bc8fa5afa9fc30768b3bf5e79053844d2cc73084f4cc6f94
- command: cargo run -p codex-app-server-protocol --bin write_schema_fixtures -- --schema-root artifacts/pr-packets/smoke-2026-02-28-bypass-simple/generated-schema
- contract exitCode: 1
