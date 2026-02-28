#!/usr/bin/env python3
"""Print concise root-cause diagnostics for a codex-multi run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"


def read_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_lines(path: Path, limit: int = 20) -> List[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()[:limit]
    except OSError:
        return []


def print_blocker_block(block: Dict[str, Any], run_id: str) -> None:
    name = block.get("name") or "unknown"
    print(f"- {name}: {block.get('state', 'BLOCKED')}")
    reason = block.get("blockerReason") or block.get("reason") or block.get("error")
    if reason:
        print(f"  reason: {reason}")
    blocker_path = ARTIFACTS / "coordination" / run_id / str(name) / "blocker.json"
    if blocker_path.exists():
        blocker_doc = read_json(blocker_path)
        if blocker_doc:
            last_message = blocker_doc.get("lastMessage")
            if isinstance(last_message, str) and last_message.strip():
                print("  lastMessage:")
                for line in last_message.splitlines()[:12]:
                    print(f"    {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a codex-multi run for blocked reasons")
    parser.add_argument("run_id", help="run-id folder under artifacts/<coordination|pr-packets>")
    args = parser.parse_args()

    run_id = args.run_id
    print(f"Run: {run_id}")

    impact = read_json(ARTIFACTS / "pr-packets" / run_id / "impact-report.json")
    if not impact:
        print("Could not load artifacts/pr-packets/{run_id}/impact-report.json")
        return 1

    print(f"Overall state: {impact.get('state')}")
    print(f"Task: {impact.get('task')}")

    artifact_errors = impact.get("artifactErrors", [])
    if artifact_errors:
        print("artifactErrors:")
        for item in artifact_errors:
            print(f"- {item}")

    agents = impact.get("agents", [])
    if agents:
        print("agents:")
        for agent in agents:
            if agent.get("state") == "BLOCKED":
                print_blocker_block(agent, run_id)

    contract = read_json(ARTIFACTS / "pr-packets" / run_id / "contract-check.json")
    if contract:
        print("contract check:")
        status = contract.get("status", "UNKNOWN")
        print(f"- status: {status}")
        if "expectedHash" in contract:
            print(f"- expectedHash: {contract.get('expectedHash')}")
        if "generatedHash" in contract:
            print(f"- generatedHash: {contract.get('generatedHash')}")
        if "command" in contract:
            print(f"- command: {contract.get('command')}")
        if "exitCode" in contract:
            print(f"- exitCode: {contract.get('exitCode')}")
        diff_path = contract.get("diffPath")
        if diff_path:
            lines = read_lines(Path(ARTIFACTS, diff_path))
            if lines:
                print(f"- diff preview ({diff_path}):")
                for line in lines:
                    print(f"  {line}")

    merge = impact.get("mergeability") or {}
    if isinstance(merge, dict):
        if merge.get("passed") is False:
            print("mergeability: FAILED")
            details = merge.get("details", [])
            for detail in details:
                if isinstance(detail, dict):
                    agent_name = detail.get("agent", "unknown")
                    print(f"- agent {agent_name} checkCode={detail.get('checkCode')}")
                    stderr = detail.get("checkStderr", "").strip()
                    if stderr:
                        print(f"  stderr: {stderr}")

    print("planner:")
    planner_intent = read_json(ARTIFACTS / "coordination" / run_id / "planner" / "intent.json")
    if planner_intent:
        print(f"- parseAttempts: {planner_intent.get('plannerParseAttempts', 'n/a')}")
        print(f"- fallbackUsed: {planner_intent.get('fallbackUsed', False)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#
