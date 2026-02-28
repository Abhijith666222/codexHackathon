# PR Packet Summary

Run ID: run-2026-02-28-083804
Overall state: BLOCKED

## Evidence
- artifacts/pr-packets/run-2026-02-28-083804/diff.patch
- artifacts/pr-packets/run-2026-02-28-083804/test-logs.txt
- artifacts/pr-packets/run-2026-02-28-083804/contract-check.json
- artifacts/pr-packets/run-2026-02-28-083804/contract-check.diff.txt
- artifacts/pr-packets/run-2026-02-28-083804/impact-report.json
- artifacts/pr-packets/run-2026-02-28-083804/summary.md

Status: BLOCKED
- No agent produced any file changes.
- agent-bootstrap BLOCKED: Platform write restriction detected from agent output.
- Evidence: artifacts/coordination/run-2026-02-28-083804/agent-bootstrap/blocker.json
- agent-components BLOCKED: Platform write restriction detected from agent output.
- Evidence: artifacts/coordination/run-2026-02-28-083804/agent-components/blocker.json
- mergeability check failed
- merge check stderr (agent-discovery): error: No valid patches in input (allow with "--allow-empty")
- merge check code (agent-discovery): 128
- contract check failed
- Contract details: artifacts/pr-packets/run-2026-02-28-083804/contract-check.json
- command: node scripts/multiagent/contract-check.mjs
- contract exitCode: 3221225786
