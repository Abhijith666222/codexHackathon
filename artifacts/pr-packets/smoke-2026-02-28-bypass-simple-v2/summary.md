# PR Packet Summary

Run ID: smoke-2026-02-28-bypass-simple-v2
Overall state: BLOCKED

## Evidence
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/diff.patch
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/test-logs.txt
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/contract-check.json
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/contract-check.diff.txt
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/impact-report.json
- artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/summary.md

Status: BLOCKED
- agent-validator BLOCKED: Scope violation: edited codex-rs/SMOKE_WRITE.md
- Evidence: artifacts/coordination/smoke-2026-02-28-bypass-simple-v2/agent-validator/blocker.json
- mergeability check failed
- merge check stderr (agent-validator): error: codex-rs/SMOKE_WRITE.md: already exists in working directory
- merge check code (agent-validator): 1
- contract check failed
- Contract details: artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/contract-check.json
- expected hash: 7676abc91b268e97c20529182c4fa8b85a39124b70380b671137db8bb588274f
- generated hash: 22aa225404e67ef7bc8fa5afa9fc30768b3bf5e79053844d2cc73084f4cc6f94
- command: cargo run -p codex-app-server-protocol --bin write_schema_fixtures -- --schema-root artifacts/pr-packets/smoke-2026-02-28-bypass-simple-v2/generated-schema
- contract exitCode: 1
