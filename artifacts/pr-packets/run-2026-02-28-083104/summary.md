# PR Packet Summary

Run ID: run-2026-02-28-083104
Overall state: BLOCKED

## Evidence
- artifacts/pr-packets/run-2026-02-28-083104/diff.patch
- artifacts/pr-packets/run-2026-02-28-083104/test-logs.txt
- artifacts/pr-packets/run-2026-02-28-083104/contract-check.json
- artifacts/pr-packets/run-2026-02-28-083104/contract-check.diff.txt
- artifacts/pr-packets/run-2026-02-28-083104/impact-report.json
- artifacts/pr-packets/run-2026-02-28-083104/summary.md

Status: BLOCKED
- No agent produced any file changes.
- No explicit agent blocker reason captured.
- mergeability check failed
- merge check stderr (agent-ui-shell): error: No valid patches in input (allow with "--allow-empty")
- merge check code (agent-ui-shell): 128
- contract check failed
- Contract details: artifacts/pr-packets/run-2026-02-28-083104/contract-check.json
- expected hash: 7676abc91b268e97c20529182c4fa8b85a39124b70380b671137db8bb588274f
- generated hash: 22aa225404e67ef7bc8fa5afa9fc30768b3bf5e79053844d2cc73084f4cc6f94
- command: cargo run -p codex-app-server-protocol --bin write_schema_fixtures -- --schema-root artifacts/pr-packets/run-2026-02-28-083104/generated-schema
- contract exitCode: 1
