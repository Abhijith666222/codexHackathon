#!/usr/bin/env python3
"""Minimal multi-agent dashboard + orchestrator for Codex."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKTREE_ROOT = PROJECT_ROOT / "codex-worktrees"
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
COORD_BASE = ARTIFACTS_ROOT / "coordination"
PACKET_BASE = ARTIFACTS_ROOT / "pr-packets"
DASH_REFRESH = 0.35
WEB_REFRESH = 0.6
DEFAULT_WEB_PORT = 8765
DEFAULT_SCOPE_ROOT = "codex-rs"
PLANNER_RETRY_LIMIT = 2
AGENT_RETRY_LIMIT = 3
AGENT_RETRY_DELAY_SECONDS = 1.0
_AGENT_RETRY_HINTS = (
    "reconnecting",
    "stream disconnected",
    "websocket closed",
    "response.completed",
    "connection reset",
    "connection closed",
    "socket closed",
)
_AGENT_WRITE_HINTS = (
    "all write attempts were rejected",
    "blocked from writing",
    "writing is disallowed",
    "write restriction",
    "write policy",
    "read-only",
    "permission denied",
    "cannot write",
    "write access",
    "outside of the project",
    "outside the project",
    "apply_patch",
    "not allowed",
    "policy blocked",
    "write access is not available",
)
_ALLOWED_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
_DEFAULT_AGENT_SANDBOX_MODE = "workspace-write"
_SANDBOX_ENV = "CODEX_MULTI_SANDBOX_MODE"
_ALLOWED_TASK_MODES = ("auto", "code", "advisory")
_DEFAULT_TASK_MODE = "auto"
_TASK_MODE_ENV = "CODEX_MULTI_TASK_MODE"
_MODEL_ENV = "CODEX_MULTI_MODEL"
_MODEL_PROVIDER_ENV = "CODEX_MULTI_MODEL_PROVIDER"
_CODEX_COMMAND_ENV = "CODEX_MULTI_CODEX_COMMAND"
_BYPASS_SANDBOX_ENV = "CODEX_MULTI_BYPASS_SANDBOX"


def get_web_dashboard_html() -> str:
    dashboard_file = Path(__file__).resolve().parent / "web_dashboard.html"
    if dashboard_file.exists():
        return dashboard_file.read_text(encoding="utf-8")

    return """<!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Codex Multi-Agent Dashboard</title>
        <style>
          :root {
            --bg: #0f172a;
            --text: #e2e8f0;
            --muted: #94a3b8;
            --line: rgba(255, 255, 255, 0.1);
            --accent: #4f6ef7;
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            background: var(--bg);
            color: var(--text);
            font-family: Inter, "Segoe UI", sans-serif;
          }
          .page {
            max-width: 1100px;
            margin: 0 auto;
            padding: 20px;
          }
          .panel {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
          }
        </style>
      </head>
      <body>
        <main class="page">
          <header class="panel">
            <h1>Codex Multi-Agent Dashboard</h1>
            <div id="meta" class="muted"></div>
            <div id="task" class=""></div>
          </header>
          <p id="error" style="color: #fda4af;"></p>
          <section class="panel">
            <form id="promptForm">
              <select id="promptPreset">
                <option value="">-- Choose a preset --</option>
                <option value="Give me a concise checklist to plan this project in phases.">Project planning checklist</option>
                <option value="Implement the requested feature with minimal file changes and clear diffs.">Minimal implementation</option>
                <option value="Review the current implementation and suggest prioritized improvements.">Improvement review</option>
              </select>
              <textarea id="taskPrompt" style="width: 100%; min-height: 120px;"></textarea>
              <button id="startButton" type="submit">Start</button>
            </form>
          </section>
          <section class="panel">
            <div id="planningSection"></div>
            <pre id="activity"></pre>
          </section>
        </main>
        <script>
          const promptPreset = document.getElementById('promptPreset');
          const taskPrompt = document.getElementById('taskPrompt');
          const startButton = document.getElementById('startButton');
          const errorBanner = document.getElementById('error');
          const promptForm = document.getElementById('promptForm');

          promptPreset.addEventListener('change', () => {
            if (promptPreset.value) {
              taskPrompt.value = promptPreset.value;
            }
          });
          promptForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const task = taskPrompt.value.trim();
            if (!task) {
              errorBanner.textContent = 'Please enter a task prompt.';
              return;
            }
            if (startButton.disabled) {
              return;
            }
            startButton.disabled = true;
            errorBanner.textContent = 'Submitting...';
            try {
              const response = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task }),
              });
              const payload = await response.json().catch(() => ({}));
              if (!response.ok) {
                errorBanner.textContent = payload.error || 'Failed to start run.';
                return;
              }
              errorBanner.textContent = 'Run started.';
            } finally {
              startButton.disabled = false;
            }
          });

          async function refresh() {
            try {
              const response = await fetch('/api/state', { cache: 'no-store' });
              if (!response.ok) {
                return;
              }
              const data = await response.json();
              const state = String(data.overallState || '').toUpperCase();
              document.getElementById('meta').textContent = `Run ${data.runId || ''} • State ${state || 'IDLE'} • tick ${data.tick || 0}`;
              document.getElementById('task').textContent = data.task ? `Task: ${data.task}` : 'No task started yet.';
              document.getElementById('planningSection').textContent = `Agents: ${(data.agents || []).length}, Plan items: ${(data.planning || []).length}`;
              const events = Array.isArray(data.activity) ? data.activity : [];
              document.getElementById('activity').textContent = events.length ? events.join('\\n') : 'No interactions yet';
            } catch (err) {
              console.error(err);
            }
          }
          refresh();
          setInterval(refresh, 600);
        </script>
      </body>
    </html>
    """


@dataclass
class AgentTask:
    name: str
    scope: str
    objective: str


@dataclass
class AgentState:
    name: str
    scope: str
    objective: str
    workspace: Path
    coord_dir: Path
    status_path: Path
    intent_path: Path
    impact_path: Path
    blocker_path: Path
    status: str = "QUEUED"
    thread_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    changed_files: List[str] = field(default_factory=list)
    blocker_reason: Optional[str] = None
    duration_ms: int = 0
    log: List[str] = field(default_factory=list)
    last_message: str = ""


@dataclass
class CodexRunResult:
    exit_code: int
    thread_id: Optional[str]
    last_message: str
    error: Optional[str]



def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    return f"run-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"


def normalize_task_mode(mode: str) -> str:
    if mode in _ALLOWED_TASK_MODES:
        return mode
    return _DEFAULT_TASK_MODE


def infer_task_mode(task: str, requested_mode: str = _DEFAULT_TASK_MODE) -> str:
    requested_mode = normalize_task_mode(requested_mode)
    if requested_mode != "auto":
        return requested_mode

    text = task.lower().strip()
    advisory_phrases = (
        "give me a list",
        "list of",
        "checklist",
        "steps to",
        "what do i need",
        "what i need",
        "how should i",
        "outline",
        "plan for",
        "recommendations",
    )
    if any(phrase in text for phrase in advisory_phrases):
        return "advisory"

    advisory_keywords = (
        "list",
        "steps",
        "plan",
        "advice",
        "recommend",
        "explain",
        "summary",
        "guide",
    )
    code_keywords = (
        "implement",
        "build",
        "scaffold",
        "create",
        "write code",
        "edit",
        "fix",
        "refactor",
        "patch",
        "frontend",
        "backend",
    )
    has_advisory = any(re.search(rf"\b{re.escape(word)}\b", text) for word in advisory_keywords)
    has_code = any(re.search(rf"\b{re.escape(word)}\b", text) for word in code_keywords)
    if has_advisory and not has_code:
        return "advisory"
    return "code"


def normalize_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9_-]", "-", value.strip().lower())
    name = re.sub(r"-+", "-", name).strip("-")
    if not name:
        name = "agent"
    if not re.match(r"[a-zA-Z]", name[0]):
        name = f"agent-{name}"
    return name[:48]


def normalize_scope(value: str) -> str:
    scope = (value or "").strip().replace("\\", "/").strip("/")
    if not scope:
        return ""
    m = re.search(r"[\\*\?\[]", scope)
    if m:
        scope = scope[: m.start()].rstrip("/")
    return scope


def detect_single_file_scope(task: str) -> Optional[str]:
    text = (task or "").strip()
    if not text:
        return None
    m = re.search(
        r"(?i)\b(?:create|add|write|update|edit|modify)\s+(?:exactly\s+)?(?:one|single)\s+file\s+[`\"']?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_+-]+)",
        text,
    )
    if not m:
        return None
    return normalize_scope(m.group(1))


def canonical_scope(scope: str) -> str:
    scope = normalize_scope(scope)
    if not scope:
        return ""
    if scope == "codex-rs":
        return ""
    if scope.startswith("codex-rs/"):
        return scope[len("codex-rs/") :]
    return scope


def in_scope(path: str, scope: str) -> bool:
    scope = canonical_scope(scope)
    scope_alt = f"codex-rs/{scope}" if scope else ""
    rel = path.replace("\\", "/")
    if not scope:
        return True
    rel = rel.strip("/")
    if rel == scope or rel.startswith(f"{scope}/"):
        return True
    if scope_alt and (rel == scope_alt or rel.startswith(f"{scope_alt}/")):
        return True
    if rel.startswith("codex-rs/"):
        rel = rel[len("codex-rs/") :]
        return rel == scope or rel.startswith(f"{scope}/")
    return False


def scopes_overlap(scope_a: str, scope_b: str) -> bool:
    a = canonical_scope(scope_a)
    b = canonical_scope(scope_b)
    if not a or not b:
        return a == "" or b == ""
    if a == b:
        return True
    return a.startswith(f"{b}/") or b.startswith(f"{a}/")


def dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)
        fp.write("\n")


def dump_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_simple(cmd: List[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (code {proc.returncode}): {' '.join(cmd)}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    return proc


def load_state_file(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def load_json_or_none(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def write_state_snapshot(path: Path, payload: Dict[str, object]) -> None:
    dump_json(path, payload)


def summarize_event_line(raw: str) -> Optional[str]:
    try:
        event = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(event, dict):
        return None

    event_type = event.get("type")
    if event_type == "thread.started":
        thread_id = event.get("thread_id")
        if thread_id:
            return f"thread started: {thread_id}"
        return "thread started"

    if event_type in {"turn.failed", "turn.blocked", "error"}:
        error = event.get("error") if isinstance(event.get("error"), dict) else None
        msg = ""
        if isinstance(error, dict):
            msg = str(error.get("message", ""))
        elif isinstance(event.get("message"), str):
            msg = str(event.get("message"))
        if msg:
            return f"{event_type}: {msg}"

    if event_type in {"item.started", "item.completed", "item.failed"}:
        item = event.get("item", {})
        if not isinstance(item, dict):
            return None

        item_type = str(item.get("type") or "")
        details = item.get("details")
        if isinstance(details, dict):
            item_type = str(details.get("type") or item_type)

        if item_type == "agent_message":
            text = item.get("text") or (details.get("text") if isinstance(details, dict) else "")
            if isinstance(text, str):
                clean = text.strip()
                if clean:
                    return clean

        if item_type == "command_execution":
            command = item.get("command") or (details.get("command") if isinstance(details, dict) else "")
            if isinstance(command, str):
                return f"command execution: {command}"

        if item_type:
            return f"{event_type}: {item_type}"

    return None


def build_dashboard_payload(
    run_id: str,
    task: str,
    plan: List[AgentTask],
    agents: List[AgentState],
    overall: str,
    tick: int,
) -> Dict[str, object]:
    snapshot = {
        "runId": run_id,
        "task": task,
        "overallState": overall,
        "tick": tick,
        "updatedAt": now_iso(),
        "planning": [
            {"name": item.name, "scope": item.scope, "objective": item.objective}
            for item in plan
        ],
        "agents": [],
    }
    for a in sorted(agents, key=lambda a: a.name):
        latest_message = a.log[-1] if a.log else ""
        latest_text = summarize_event_line(latest_message) or latest_message
        snapshot["agents"].append(
            {
                "name": a.name,
                "scope": a.scope,
                "objective": a.objective,
                "status": a.status,
                "threadId": a.thread_id,
                "exitCode": a.exit_code,
                "changedFiles": len(a.changed_files),
                "durationMs": a.duration_ms,
                "startedAt": a.started_at,
                "finishedAt": a.finished_at,
                "blockerReason": a.blocker_reason,
                "latestMessage": latest_text[:320],
            }
        )
        for line in a.log:
            summary = summarize_event_line(line)
            if summary:
                snapshot.setdefault("activity", []).append(f"{a.name}: {summary}")

    if "activity" in snapshot:
        snapshot["activity"] = snapshot["activity"][-20:]

    return snapshot


def is_transient_agent_error(error: Optional[str]) -> bool:
    if not error:
        return False
    lower = error.lower()
    return any(token in lower for token in _AGENT_RETRY_HINTS)


def is_write_restricted(message: Optional[str]) -> bool:
    if not message:
        return False
    lower = message.lower()
    return any(token in lower for token in _AGENT_WRITE_HINTS)


class _DashboardServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_web_dashboard_server(
    state_file: Path, port: int, on_start: Optional[Callable[[str], Optional[str]]] = None
) -> Tuple[http.server.HTTPServer, int]:
    html = get_web_dashboard_html()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: Dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Optional[Dict[str, object]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return None
            try:
                body = self.rfile.read(length).decode("utf-8", errors="replace")
            except OSError:
                return None
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return None
            return payload if isinstance(payload, dict) else None

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/state":
                payload = load_state_file(state_file)
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            if not on_start:
                self.send_response(404)
                self.end_headers()
                return

            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/start":
                self.send_response(404)
                self.end_headers()
                return

            payload = self._read_json()
            if not payload:
                self._send_json(400, {"error": "Invalid JSON payload."})
                return

            task = payload.get("task")
            if not isinstance(task, str):
                self._send_json(400, {"error": "Task must be a string."})
                return

            task = task.strip()
            if not task:
                self._send_json(400, {"error": "Task prompt cannot be empty."})
                return

            run_id = on_start(task)
            if not run_id:
                self._send_json(409, {"error": "A run is already in progress."})
                return
            self._send_json(202, {"runId": run_id, "status": "started"})

        def log_message(self, format: str, *args) -> None:  # pragma: no cover
            return

    try:
        server = _DashboardServer(("127.0.0.1", port), _Handler)
    except OSError as exc:  # pragma: no cover
        raise RuntimeError(f"failed to bind dashboard port {port}: {exc}") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def run_web_prompt_mode(
    run_id: str,
    web_port: int = DEFAULT_WEB_PORT,
    agent_sandbox_mode: str = _DEFAULT_AGENT_SANDBOX_MODE,
    task_mode: str = _DEFAULT_TASK_MODE,
    bypass_approvals_and_sandbox: bool = False,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> int:
    coord_run = COORD_BASE / run_id
    state_file = coord_run / "live-state.json"
    coord_run.mkdir(parents=True, exist_ok=True)

    write_state_snapshot(
        state_file,
        {
            "runId": run_id,
            "task": "",
            "taskMode": normalize_task_mode(task_mode),
            "overallState": "IDLE",
            "tick": 0,
            "updatedAt": now_iso(),
            "planning": [],
            "agents": [],
        },
    )

    launcher = {"started": False}
    completion_event = threading.Event()
    result = {"code": 1}

    run_lock = threading.Lock()

    def run_with_prompt(task: str) -> None:
        try:
            result["code"] = run_ticket(
                task,
                run_id,
                ui_mode="web",
                web_port=web_port,
                state_file=state_file,
                start_web_server=False,
                agent_sandbox_mode=agent_sandbox_mode,
                task_mode=task_mode,
                bypass_approvals_and_sandbox=bypass_approvals_and_sandbox,
                model=model,
                model_provider=model_provider,
            )
        except Exception as exc:  # pragma: no cover
            write_state_snapshot(
                state_file,
                {
                    "runId": run_id,
                    "task": task,
                    "overallState": "BLOCKED",
                    "tick": 0,
                    "updatedAt": now_iso(),
                    "planning": [],
                    "agents": [],
                    "activity": [f"bootstrap error: {exc}"],
                },
            )
            result["code"] = 1
        finally:
            completion_event.set()

    def on_start(task: str) -> Optional[str]:
        with run_lock:
            if launcher["started"]:
                return None
            launcher["started"] = True

        write_state_snapshot(
            state_file,
            {
                "runId": run_id,
                "task": task,
                "taskMode": infer_task_mode(task, task_mode),
                "overallState": "STARTING",
                "tick": 0,
                "updatedAt": now_iso(),
                "planning": [],
                "agents": [],
                "activity": ["Run starting from web dashboard..."],
            },
        )
        thread = threading.Thread(target=run_with_prompt, args=(task,), daemon=True)
        thread.start()
        return run_id

    try:
        server, web_port = start_web_dashboard_server(state_file, web_port, on_start=on_start)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Web dashboard: http://127.0.0.1:{web_port}/")
    print("Submit a task on the dashboard to start the run.")

    completion_event.wait()
    server.shutdown()
    server.server_close()
    return result["code"]


def find_codex_command() -> List[str]:
    configured = os.environ.get(_CODEX_COMMAND_ENV, "").strip()
    if configured:
        return shlex.split(configured)

    system = shutil.which("codex")
    # Prefer the user's existing installed Codex CLI first so model/provider
    # behavior (for example Claude profiles) matches non-orchestrated runs.
    if system:
        return [system]

    local_candidates = [
        PROJECT_ROOT / "codex-rs" / "target" / "debug" / "codex",
        PROJECT_ROOT / "codex-rs" / "target" / "debug" / "codex.exe",
        PROJECT_ROOT / "codex-rs" / "target" / "release" / "codex",
        PROJECT_ROOT / "codex-rs" / "target" / "release" / "codex.exe",
    ]
    cargo_target = os.environ.get("CARGO_TARGET_DIR")
    if cargo_target:
        cargo_target_path = Path(cargo_target)
        local_candidates.extend(
            [
                cargo_target_path / "debug" / "codex",
                cargo_target_path / "debug" / "codex.exe",
                cargo_target_path / "release" / "codex",
                cargo_target_path / "release" / "codex.exe",
            ]
        )
    for candidate in local_candidates:
        if candidate.exists():
            return [str(candidate)]
    if (PROJECT_ROOT / "codex-rs" / "Cargo.toml").exists() and shutil.which("cargo"):
        return [
            "cargo",
            "run",
            "--manifest-path",
            str(PROJECT_ROOT / "codex-rs" / "Cargo.toml"),
            "-p",
            "codex-cli",
            "--",
        ]
    return ["codex"]


def normalize_sandbox_mode(mode: str) -> str:
    if mode in _ALLOWED_SANDBOX_MODES:
        return mode
    return _DEFAULT_AGENT_SANDBOX_MODE


def env_flag_enabled(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def can_write_workspace(path: Path) -> Optional[str]:
    marker = path / ".codex-multi-write-test"
    try:
        marker.write_text("ping", encoding="utf-8")
        marker.unlink()
        return None
    except Exception as exc:
        return f"Workspace write probe failed: {exc}"


def parse_embedded_json(text: str) -> Optional[object]:
    s = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    decoder = json.JSONDecoder()
    for text_block in (s, text):
        for prefix in ("{", "["):
            idx = text_block.find(prefix)
            while 0 <= idx < len(text_block):
                try:
                    value, _ = decoder.raw_decode(text_block[idx:])
                    if isinstance(value, (dict, list)):
                        return value
                except json.JSONDecodeError:
                    pass
                idx = text_block.find(prefix, idx + 1)
                if idx == -1:
                    break
    return None


def append_log(state: AgentState, line: str, lock: threading.Lock, state_file_run_id: Optional[str] = None) -> None:
    with lock:
        clean = line.rstrip("\n")[:320]
        if clean:
            state.log.append(clean)
            if len(state.log) > 6:
                state.log.pop(0)
        if state_file_run_id:
            state.started_at = state.started_at or now_iso()
            write_status(state, state_file_run_id)


def write_status(state: AgentState, run_id: str) -> None:
    payload = {
        "agent": state.name,
        "runId": run_id,
        "scope": state.scope,
        "state": state.status,
        "threadId": state.thread_id,
        "startedAt": state.started_at,
        "finishedAt": state.finished_at,
        "durationMs": state.duration_ms,
        "exitCode": state.exit_code,
        "updatedAt": now_iso(),
    }
    if state.blocker_reason:
        payload["blockerReason"] = state.blocker_reason
    dump_json(state.status_path, payload)


def run_codex_stream(
    prompt: str,
    workspace: Path,
    last_message_path: Path,
    codex_cmd: List[str],
    on_line: Optional[Callable[[str], None]] = None,
    sandbox_mode: str = _DEFAULT_AGENT_SANDBOX_MODE,
    bypass_approvals_and_sandbox: bool = False,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> CodexRunResult:
    sandbox_mode = normalize_sandbox_mode(sandbox_mode)
    if bypass_approvals_and_sandbox:
        cmd = codex_cmd + ["--dangerously-bypass-approvals-and-sandbox"]
    else:
        cmd = codex_cmd + ["--ask-for-approval", "never"]
        cmd.extend(["--sandbox", sandbox_mode])
    if model:
        cmd.extend(["--model", model])
    if model_provider:
        cmd.extend(["--config", f"model_provider={model_provider}"])
    cmd.extend([
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--output-last-message",
        str(last_message_path),
        prompt,
    ])
    proc = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    thread_id = None
    last_message = ""
    error: Optional[str] = None
    if not proc.stdout:
        return CodexRunResult(1, None, "", "No stdout stream")

    for raw in proc.stdout:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if on_line:
            on_line(raw)
        line = raw.strip("\n")
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        elif event_type == "item.completed":
            item = event.get("item", {})
            details = item.get("details", {})
            if details.get("type") == "agent_message":
                msg = details.get("text", "")
                if msg:
                    last_message = msg
        elif event_type == "turn.failed":
            error = event.get("error", {}).get("message") if isinstance(event.get("error"), dict) else str(event)
        elif event_type == "error":
            err = event.get("message")
            if isinstance(err, str):
                error = err

    exit_code = proc.wait()

    if not last_message and last_message_path.exists():
        last_message = last_message_path.read_text(encoding="utf-8", errors="ignore")

    return CodexRunResult(
        exit_code=exit_code,
        thread_id=thread_id,
        last_message=last_message.strip(),
        error=error,
    )


def collect_changed_files(workspace: Path) -> List[str]:
    status = run_simple(["git", "status", "--short", "--untracked-files=all"], cwd=workspace)
    if status.returncode != 0:
        return []
    files = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    return sorted(set(files))


def collect_diff(workspace: Path) -> str:
    tracked = run_simple(["git", "diff", "--binary"], cwd=workspace).stdout.strip()
    if not tracked:
        tracked = ""

    status = run_simple(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=workspace,
    ).stdout.splitlines()

    untracked_diffs = []
    for line in status:
        if not line.startswith("?? "):
            continue
        relpath = line[3:].strip()
        if not relpath:
            continue
        file_path = workspace / relpath
        if not file_path.exists() or not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            untracked_diffs.append(
                "\n".join(
                    [
                        f"diff --git a/{relpath} b/{relpath}",
                        "new file mode 100644",
                        "index 0000000..0000000",
                        f"Binary file /dev/null and b/{relpath} differ",
                        "",
                    ]
                )
            )
            continue

        lines = [
            f"diff --git a/{relpath} b/{relpath}",
            "new file mode 100644",
            "index 0000000..0000000",
            "--- /dev/null",
            f"+++ b/{relpath}",
            "@@ -0,0 +1,%d @@" % (len(text.splitlines()) or 1),
        ]
        for ln in text.splitlines():
            lines.append(f"+{ln}")
        if not text.endswith("\n"):
            lines.append("+")
        untracked_diffs.append("\n".join(lines) + "\n")

    parts = [tracked]
    if untracked_diffs:
        parts.extend(untracked_diffs)
    return "\n".join(p for p in parts if p).rstrip() + ("\n" if (tracked or untracked_diffs) else "")


def create_worktree(path: Path, base: str = "HEAD") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.rmtree(path)
    run_simple(["git", "worktree", "add", "--detach", str(path), base], cwd=PROJECT_ROOT, check=True)


def run_agent(
    state: AgentState,
    codex_cmd: List[str],
    lock: threading.Lock,
    run_id: str,
    task_mode: str = "code",
    require_file_changes: bool = True,
    sandbox_mode: str = _DEFAULT_AGENT_SANDBOX_MODE,
    bypass_approvals_and_sandbox: bool = False,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> None:
    last_message_path = state.coord_dir / "last-message.txt"

    with lock:
        state.status = "RUNNING"
        state.started_at = now_iso()
        state.duration_ms = 0
        write_status(state, run_id)

    if task_mode == "advisory":
        prompt = (
            "You are an advisory sub-agent named {name}.\n"
            "Topic scope: {scope}.\n"
            "Goal: {objective}.\n"
            "Return concise guidance, checklists, or recommendations in markdown bullets.\n"
            "Do not modify files unless explicitly asked by the user.\n"
        ).format(
            name=state.name,
            scope=state.scope or ".",
            objective=state.objective,
        )
    else:
        prompt = (
            "You are a coding sub-agent named {name}.\n"
            "Work only inside this scope: {scope}.\n"
            "Goal: {objective}.\n"
            "Use the repository and make only code changes needed for this task.\n"
            "Do not modify files outside your scope.\n"
            "You must create/update at least one file in your scope unless explicitly blocked by the platform.\n"
        ).format(
            name=state.name,
            scope=state.scope or ".",
            objective=state.objective,
        )

    blocker: Optional[str] = None
    result: Optional[CodexRunResult] = None
    final_last_message = ""
    total_duration_ms = 0
    if require_file_changes:
        workspace_probe = can_write_workspace(state.workspace)
        if workspace_probe:
            blocker = workspace_probe
            final_last_message = workspace_probe
            result = CodexRunResult(
                exit_code=1,
                thread_id=None,
                last_message=workspace_probe,
                error=blocker,
            )
            append_log(state, f"workspace preflight failed: {workspace_probe}", lock, run_id)

    if not blocker:
        for attempt in range(1, AGENT_RETRY_LIMIT + 1):
            if attempt > 1:
                append_log(
                    state,
                    f"retrying agent execution (attempt {attempt}/{AGENT_RETRY_LIMIT}) after {blocker}",
                    lock,
                    run_id,
                )
                time.sleep(AGENT_RETRY_DELAY_SECONDS * attempt)

            try:
                started = time.time()
                result = run_codex_stream(
                    prompt=prompt,
                    workspace=state.workspace,
                    last_message_path=last_message_path,
                    codex_cmd=codex_cmd,
                    on_line=lambda line: append_log(state, line, lock, run_id),
                    sandbox_mode=sandbox_mode,
                    bypass_approvals_and_sandbox=bypass_approvals_and_sandbox,
                    model=model,
                    model_provider=model_provider,
                )
                done_at = time.time()
                total_duration_ms += int((done_at - started) * 1000)
                final_last_message = result.last_message
                state.changed_files = collect_changed_files(state.workspace)
                blocker = result.error
                if require_file_changes and not blocker and is_write_restricted(result.last_message):
                    blocker = "Platform write restriction detected from agent output."
                if result.exit_code != 0:
                    blocker = blocker or "Agent exited with non-zero status."
                else:
                    violations = [f for f in state.changed_files if not in_scope(f, state.scope)]
                    if violations:
                        blocker = f"Scope violation: edited {', '.join(violations[:5])}"
                    elif require_file_changes and not state.changed_files:
                        blocker = "No file changes were produced; execution was blocked or task was not executed."
                    elif not require_file_changes and state.changed_files:
                        blocker = "Unexpected file changes were produced for an advisory task."
            except Exception as exc:
                blocker = f"Internal agent failure: {exc}"
                total_duration_ms += 1
                result = CodexRunResult(
                    exit_code=1,
                    thread_id=None,
                    last_message=final_last_message,
                    error=blocker,
                )

            if blocker and is_transient_agent_error(blocker) and attempt < AGENT_RETRY_LIMIT:
                continue
            break

    with lock:
        state.finished_at = now_iso()
        state.exit_code = result.exit_code if result else 1
        state.thread_id = result.thread_id if result else None
        state.duration_ms = total_duration_ms
        state.changed_files = collect_changed_files(state.workspace)
        state.blocker_reason = blocker
        state.last_message = final_last_message
        if blocker:
            state.status = "BLOCKED"
            dump_json(
                state.blocker_path,
                {
                    "agent": state.name,
                    "runId": run_id,
                    "state": "BLOCKED",
                    "scope": state.scope,
                    "reason": blocker,
                    "createdAt": now_iso(),
                    "lastMessage": final_last_message,
                },
            )
            dump_json(
                state.impact_path,
                {
                    "agent": state.name,
                    "runId": run_id,
                    "state": state.status,
                    "scope": state.scope,
                    "changedFiles": state.changed_files,
                    "durationMs": state.duration_ms,
                    "error": blocker,
                },
            )
        else:
            state.status = "DONE"
            dump_json(
                state.impact_path,
                {
                    "agent": state.name,
                    "runId": run_id,
                    "state": state.status,
                    "scope": state.scope,
                    "changedFiles": state.changed_files,
                    "durationMs": state.duration_ms,
                    "exitCode": state.exit_code,
                    "threadId": state.thread_id,
                    "lastMessage": final_last_message,
                    "finishedAt": state.finished_at,
                },
            )
        write_status(state, run_id)


def parse_plan(raw_task: str, raw_plan: Optional[object], task_mode: str = "code") -> List[AgentTask]:
    if task_mode != "advisory":
        single_file_scope = detect_single_file_scope(raw_task)
        if single_file_scope:
            return [
                AgentTask(
                    name="agent-implementation",
                    scope=single_file_scope,
                    objective=raw_task,
                )
            ]

    subtasks: List[dict] = []
    if isinstance(raw_plan, list):
        subtasks = [item for item in raw_plan if isinstance(item, dict)]
    elif isinstance(raw_plan, dict):
        if (raw_plan.get("subtasks") or raw_plan.get("agents") or raw_plan.get("tasks") or raw_plan.get("steps") or raw_plan.get("items") or raw_plan.get("plan")):
            for key in ("subtasks", "agents", "tasks", "steps", "items", "plan"):
                candidate = raw_plan.get(key)
                if isinstance(candidate, list):
                    subtasks = [item for item in candidate if isinstance(item, dict)]
                    break
                if isinstance(candidate, dict):
                    subtasks = [candidate]
                    break

        if not subtasks:
            normalized = raw_plan.get("normalizedPlan")
            if isinstance(normalized, dict):
                for key in ("subtasks", "agents", "tasks", "steps", "items", "plan"):
                    candidate = normalized.get(key)
                    if isinstance(candidate, list):
                        subtasks = [item for item in candidate if isinstance(item, dict)]
                        break
                    if isinstance(candidate, dict):
                        subtasks = [candidate]
                        break

        if not subtasks and {"name", "scope", "objective"} & set(raw_plan.keys()):
            subtasks = [raw_plan]

    if not subtasks:
        fallback_scope = "analysis" if task_mode == "advisory" else "codex-rs"
        return [
            AgentTask(
                name="agent-advisor" if task_mode == "advisory" else "agent-implementation",
                scope=fallback_scope,
                objective=raw_task,
            )
        ]

    parsed: List[AgentTask] = []
    used = set()
    for idx, item in enumerate(subtasks, start=1):
        if not isinstance(item, dict):
            continue
        name = normalize_name(str(item.get("name", f"agent-{idx}")))
        base = name
        i = 2
        while name in used:
            name = f"{base}-{i}"
            i += 1
        used.add(name)
        scope = normalize_scope(str(item.get("scope") or item.get("fileScope") or ""))
        objective = str(
            item.get("objective")
            or item.get("task")
            or item.get("goal")
            or item.get("description")
            or raw_task
        )
        parsed.append(AgentTask(name=name, scope=scope, objective=objective))

    if not parsed:
        fallback_scope = "analysis" if task_mode == "advisory" else "codex-rs"
        return [
            AgentTask(
                name="agent-advisor" if task_mode == "advisory" else "agent-implementation",
                scope=fallback_scope,
                objective=raw_task,
            )
        ]
    return parsed


def normalize_disjoint_scopes(tasks: List[AgentTask], fallback_root: str = DEFAULT_SCOPE_ROOT) -> List[AgentTask]:
    used: List[str] = []
    normalized: List[AgentTask] = []
    has_many_agents = len(tasks) > 1

    for item in tasks:
        name = item.name
        base_scope = normalize_scope(item.scope)
        if not base_scope:
            base_scope = fallback_root if not has_many_agents else f"{fallback_root}/{name}"

        candidate = base_scope
        if any(scopes_overlap(candidate, existing) for existing in used):
            candidate = f"{fallback_root}/{name}"

        suffix = 1
        while any(scopes_overlap(candidate, existing) for existing in used):
            candidate = f"{fallback_root}/{name}-{suffix}"
            suffix += 1

        normalized.append(
            AgentTask(
                name=name,
                scope=candidate,
                objective=item.objective,
            )
        )
        used.append(candidate)

    return normalized


def run_planner(
    raw_task: str,
    codex_cmd: List[str],
    run_id: str,
    task_mode: str = "code",
    sandbox_mode: str = _DEFAULT_AGENT_SANDBOX_MODE,
    bypass_approvals_and_sandbox: bool = False,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> Tuple[List[AgentTask], CodexRunResult]:
    planner_dir = COORD_BASE / run_id / "planner"
    status_path = planner_dir / "status.json"
    intent_path = planner_dir / "intent.json"
    impact_path = planner_dir / "impact-report.json"

    dump_json(status_path, {"agent": "planner", "runId": run_id, "state": "RUNNING", "updatedAt": now_iso()})

    if task_mode == "advisory":
        prompt = (
            "You are a planner for a multi-agent advisory team.\n"
            "The user asked for guidance or a checklist, not direct code implementation.\n"
            "Decompose the task into 2-4 named advisory subtasks.\n"
            "Return STRICT JSON only, no code fences.\n"
            "Scope rules are strict:\n"
            "- every scope MUST be a unique short topic tag (for example `requirements`, `risks`, `sequencing`)\n"
            "- scopes MUST NOT overlap or repeat\n"
            "- do not use filesystem paths unless explicitly requested by the user\n\n"
            'Example: {"raw_task":"...", "subtasks":[{"name":"agent-requirements","scope":"requirements","objective":"list requirements and assumptions"}] }\n\n'
            f"User task: {raw_task}"
        )
    else:
        prompt = (
            "You are a planner for a multi-agent engineering team.\n"
            "Decompose the task into 2-4 subtasks for named agents.\n"
            "Return STRICT JSON only, no code fences.\n"
            "Scope rules are strict:\n"
            "- every scope MUST be path-like and MUST NOT overlap another scope (no parent/child relationships)\n"
            "- do not reuse scope prefixes (for example, avoid both `feature` and `feature/src`)\n"
            "- prefer dedicated sibling paths under a shared root when possible\n\n"
            'Example: {"raw_task":"...", "subtasks":[{"name":"agent-a","scope":"feature/a","objective":"..."}] }\n\n'
            f"User task: {raw_task}"
        )

    result = run_codex_stream(
        prompt=prompt,
        workspace=PROJECT_ROOT,
        last_message_path=planner_dir / "last-message.txt",
        codex_cmd=codex_cmd,
        sandbox_mode=sandbox_mode,
        bypass_approvals_and_sandbox=bypass_approvals_and_sandbox,
        model=model,
        model_provider=model_provider,
    )

    parsed = parse_embedded_json(result.last_message)
    retry_attempts = 0
    planner_fallback_detected = False
    fallback_plan = parse_plan(raw_task, parsed, task_mode=task_mode)
    if (
        len(fallback_plan) == 1
        and (
            (task_mode != "advisory" and fallback_plan[0].name == "agent-implementation" and fallback_plan[0].scope == "codex-rs")
            or (task_mode == "advisory" and fallback_plan[0].name == "agent-advisor" and fallback_plan[0].scope == "analysis")
        )
    ):
        planner_fallback_detected = True

    if planner_fallback_detected:
        while retry_attempts < PLANNER_RETRY_LIMIT - 1:
            if task_mode == "advisory":
                retry_shape_example = (
                    "Example: {\"raw_task\":\"...\",\"subtasks\":[{\"name\":\"agent-1\",\"scope\":\"requirements\",\"objective\":\"...\"}]}\n"
                )
            else:
                retry_shape_example = (
                    "Example: {\"raw_task\":\"...\",\"subtasks\":[{\"name\":\"agent-1\",\"scope\":\"feature/a\",\"objective\":\"...\"}]}\n"
                )
            retry_attempt = run_codex_stream(
                prompt=(
                    f"{prompt}\n\n"
                    "Your response is still not in the required planner JSON shape.\n"
                    "Return ONLY valid JSON object with key `subtasks` containing 2-4 entries.\n"
                    f"{retry_shape_example}"
                    "Do not include prose, bullets, or fences."
                ),
                workspace=PROJECT_ROOT,
                last_message_path=planner_dir / "last-message.txt",
                codex_cmd=codex_cmd,
                sandbox_mode=sandbox_mode,
                bypass_approvals_and_sandbox=bypass_approvals_and_sandbox,
                model=model,
                model_provider=model_provider,
            )
            retry_attempts += 1
            parsed_retry = parse_embedded_json(retry_attempt.last_message)
            if parsed_retry is None:
                continue
            plan_retry = parse_plan(raw_task, parsed_retry, task_mode=task_mode)
            if not (
                len(plan_retry) == 1
                and (
                    (task_mode != "advisory" and plan_retry[0].name == "agent-implementation" and plan_retry[0].scope == "codex-rs")
                    or (task_mode == "advisory" and plan_retry[0].name == "agent-advisor" and plan_retry[0].scope == "analysis")
                )
            ):
                parsed = parsed_retry
                result = retry_attempt
                planner_fallback_detected = False
                break

    planner_parse_attempts = retry_attempts + 1

    plan = parse_plan(raw_task, parsed, task_mode=task_mode)
    fallback_root = "analysis" if task_mode == "advisory" else DEFAULT_SCOPE_ROOT
    plan = normalize_disjoint_scopes(plan, fallback_root=fallback_root)

    dump_json(
        intent_path,
        {
            "runId": run_id,
            "task": raw_task,
            "plannerResult": parsed or {},
            "plannerParseAttempts": planner_parse_attempts,
            "fallbackUsed": planner_fallback_detected,
            "normalizedPlan": {
                "subtasks": [
                    {
                        "name": item.name,
                        "scope": item.scope,
                        "objective": item.objective,
                    }
                    for item in plan
                ],
            },
            "parsedAt": now_iso(),
        },
    )
    dump_json(
        impact_path,
        {
            "runId": run_id,
            "agentCount": len(plan),
            "exitCode": result.exit_code,
            "state": "DONE" if result.exit_code == 0 else "BLOCKED",
            "parsed": bool(parsed),
        },
    )
    dump_json(
        status_path,
        {
            "agent": "planner",
            "runId": run_id,
            "state": "DONE" if result.exit_code == 0 else "BLOCKED",
            "threadId": result.thread_id,
            "updatedAt": now_iso(),
        },
    )
    return plan, result


def validate_scope_rules(tasks: List[AgentTask]) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            if scopes_overlap(tasks[i].scope, tasks[j].scope):
                issues.append(
                    f"scope overlap: {tasks[i].name}:{tasks[i].scope or '.'} and {tasks[j].name}:{tasks[j].scope or '.'}"
                )
    return len(issues) == 0, issues


def needs_contract_check(agents: List[AgentState]) -> bool:
    sensitive_prefixes = (
        "codex-rs/codex-app-server-protocol/",
        "codex-rs/protocol/",
    )
    for agent in agents:
        for changed in agent.changed_files:
            rel = changed.replace("\\", "/").strip("/")
            if any(rel.startswith(prefix) for prefix in sensitive_prefixes):
                return True
    return False


def check_mergeability(agents: List[AgentState], run_id: str) -> Dict[str, object]:
    result: Dict[str, object] = {"passed": False, "details": []}
    temp_root = Path(tempfile.mkdtemp(prefix=f"{run_id}-merge-"))
    merge_tree = temp_root / "merge"
    patches: List[Path] = []
    details: List[dict] = []
    non_empty_patches: List[Tuple[AgentState, str]] = []

    for agent in agents:
        patch = collect_diff(agent.workspace)
        if patch.strip():
            non_empty_patches.append((agent, patch))
        else:
            details.append(
                {
                    "agent": agent.name,
                    "skipped": "empty patch",
                    "checkCode": 0,
                    "applyCode": 0,
                }
            )

    if not non_empty_patches:
        result.update(
            {
                "passed": True,
                "details": details + [{"mode": "skip", "reason": "all patches empty"}],
                "mergedDiff": "",
                "patches": [],
            }
        )
        shutil.rmtree(temp_root, ignore_errors=True)
        return result

    try:
        run_simple(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(merge_tree),
                "HEAD",
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )

        for agent, patch in non_empty_patches:
            patch_path = temp_root / f"{agent.name}.patch"
            dump_text(patch_path, patch)
            patches.append(patch_path)
            check = run_simple(["git", "-C", str(merge_tree), "apply", "--check", str(patch_path)], cwd=PROJECT_ROOT)
            detail: Dict[str, object] = {
                "agent": agent.name,
                "patch": str(patch_path),
                "checkCode": check.returncode,
                "checkStdout": check.stdout,
                "checkStderr": check.stderr,
            }
            if check.returncode != 0:
                details.append(detail)
                result["details"] = details
                return result

            apply = run_simple(["git", "-C", str(merge_tree), "apply", str(patch_path)], cwd=PROJECT_ROOT)
            detail["applyCode"] = apply.returncode
            detail["applyStdout"] = apply.stdout
            detail["applyStderr"] = apply.stderr
            details.append(detail)
            if apply.returncode != 0:
                result["details"] = details
                return result

        merged = run_simple(["git", "-C", str(merge_tree), "diff", "--binary"], cwd=PROJECT_ROOT).stdout
        result.update({
            "passed": True,
            "details": details,
            "mergedDiff": merged,
            "patches": [str(p) for p in patches],
        })
    finally:
        if merge_tree.exists():
            run_simple(["git", "worktree", "remove", "--force", str(merge_tree)], cwd=PROJECT_ROOT)
        run_simple(["git", "worktree", "prune"], cwd=PROJECT_ROOT)
        shutil.rmtree(temp_root, ignore_errors=True)

    return result


def run_contract_check(run_id: str, packet_dir: Path) -> Dict[str, object]:
    script = PROJECT_ROOT / "scripts" / "multiagent" / "contract-check.mjs"
    if not script.exists():
        return {
            "runId": run_id,
            "status": "ERROR",
            "command": "missing scripts/multiagent/contract-check.mjs",
            "exitCode": 2,
            "timestamp": now_iso(),
            "stdout": "",
            "stderr": "",
        }
    if not shutil.which("node"):
        return {
            "runId": run_id,
            "status": "ERROR",
            "command": "node (missing)",
            "exitCode": 2,
            "timestamp": now_iso(),
            "stdout": "",
            "stderr": "Node not available",
        }

    proc = run_simple(["node", str(script), "--run-id", run_id], cwd=PROJECT_ROOT)
    check_path = packet_dir / "contract-check.json"
    generated = None
    if check_path.exists():
        try:
            generated = json.loads(check_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            generated = None

    if generated is None:
        return {
            "runId": run_id,
            "status": "ERROR" if proc.returncode != 0 else "PASS",
            "command": "node scripts/multiagent/contract-check.mjs",
            "exitCode": proc.returncode,
            "timestamp": now_iso(),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    generated.setdefault("timestamp", now_iso())
    return generated


def ensure_final_contract_files(packet_dir: Path, contract: Dict[str, object]) -> None:
    if not (packet_dir / "contract-check.json").exists():
        dump_json(packet_dir / "contract-check.json", contract)
    if not (packet_dir / "contract-check.diff.txt").exists():
        dump_text(
            packet_dir / "contract-check.diff.txt",
            f"status={contract.get('status')}\nstdout={contract.get('stdout','')}\nstderr={contract.get('stderr','')}",
        )


def validate_required_artifacts(run_id: str, agents: List[AgentState]) -> List[str]:
    missing: List[str] = []
    for agent in agents:
        if not agent.status_path.exists():
            missing.append(f"{agent.name}: status.json")
        if not agent.intent_path.exists():
            missing.append(f"{agent.name}: intent.json")
        if agent.status == "DONE" and not agent.impact_path.exists():
            missing.append(f"{agent.name}: impact-report.json")
        if agent.status == "BLOCKED" and not agent.blocker_path.exists():
            missing.append(f"{agent.name}: blocker.json")
    if not (COORD_BASE / run_id).exists():
        missing.append("coordination root missing")
    return missing


def render_dashboard(
    run_id: str,
    task: str,
    plan: List[AgentTask],
    agents: List[AgentState],
    overall: str,
    done: bool,
    tick: int,
) -> str:
    rows = []
    rows.append("Codex Multi-Agent Dashboard")
    rows.append(f"Run ID   : {run_id}")
    rows.append(f"State    : {overall}")
    rows.append(f"Task     : {task}")
    rows.append("")
    rows.append("Planner decomposition:")
    for i, item in enumerate(plan, start=1):
        rows.append(f"  {i:>2}. {item.name:16} scope={item.scope or '.':24} {item.objective}")
    rows.append("")
    rows.append("Agents:")
    for a in sorted(agents, key=lambda a: a.name):
        rows.append(
            f"  {a.name:18} status={a.status:7} exit={str(a.exit_code or ''):>4} "
            f"scope={a.scope or '.':20} files={len(a.changed_files):>3}"
        )
    if not done:
        rows.append(f"\nUpdate #{tick}")
        for a in sorted(agents, key=lambda a: a.name):
            if a.log:
                rows.append(f"  {a.name}: {a.log[-1]}")
    else:
        rows.append("")
        for a in sorted(agents, key=lambda a: a.name):
            if a.blocker_reason:
                rows.append(f"  {a.name}: BLOCKED ({a.blocker_reason})")
            else:
                rows.append(f"  {a.name}: {a.status} ({len(a.changed_files)} files)")
    return "\n" + "\n".join(rows)


def inspect_run(run_id: str) -> int:
    print(f"Run: {run_id}")

    impact = load_json_or_none(PACKET_BASE / run_id / "impact-report.json")
    if not impact:
        print(f"  Could not load artifacts/pr-packets/{run_id}/impact-report.json")
        return 1

    print(f"  Overall: {impact.get('state')}")
    print(f"  Task   : {impact.get('task')}")

    if impact.get("scopeRulesOk", True):
        print("  Scope rules: OK")
    else:
        print("  Scope rules: FAILED")
        for issue in impact.get("scopeIssues", []):
            print(f"    - {issue}")

    artifact_errors = impact.get("artifactErrors", [])
    if artifact_errors:
        print("  Artifact errors:")
        for item in artifact_errors:
            print(f"    - {item}")

    agents = impact.get("agents", [])
    if agents:
        print("  Agents:")
        for agent in agents:
            name = agent.get("name", "unknown")
            state = agent.get("state", "UNKNOWN")
            changed = agent.get("changedFiles", [])
            changed_count = len(changed) if isinstance(changed, list) else 0
            print(f"    - {name}: {state} (files={changed_count})")
            blocker_reason = agent.get("blockerReason")
            if blocker_reason:
                print(f"      blockerReason: {blocker_reason}")
            blocker_doc = load_json_or_none(COORD_BASE / run_id / name / "blocker.json")
            if blocker_doc:
                last_message = blocker_doc.get("lastMessage")
                if isinstance(last_message, str) and last_message.strip():
                    print(f"      lastMessage: {last_message.splitlines()[0]}")
                print(f"      blockerEvidence: artifacts/coordination/{run_id}/{name}/blocker.json")
            elif state == "BLOCKED":
                print(f"      blockerEvidence: missing artifacts/coordination/{run_id}/{name}/blocker.json")

    merge = impact.get("mergeability", {})
    if isinstance(merge, dict):
        if merge.get("passed"):
            print("  Mergeability: OK")
        else:
            print("  Mergeability: FAILED")
            for detail in merge.get("details", []):
                if not isinstance(detail, dict):
                    continue
                agent_name = detail.get("agent", "unknown")
                print(f"    - {agent_name}: checkCode={detail.get('checkCode', 'n/a')}")
                if detail.get("checkStderr"):
                    stderr = str(detail.get("checkStderr")).strip()
                    if stderr:
                        print(f"      stderr: {stderr[:240]}")
                if detail.get("checkStdout"):
                    stdout = str(detail.get("checkStdout")).strip()
                    if stdout:
                        print(f"      stdout: {stdout[:240]}")
                if detail.get("patch"):
                    print(f"      patch: {detail.get('patch')}")

    contract = load_json_or_none(PACKET_BASE / run_id / "contract-check.json")
    if contract:
        status = contract.get("status", "UNKNOWN")
        print(f"  Contract check: {status}")
        if "expectedHash" in contract:
            print(f"    expectedHash : {contract.get('expectedHash')}")
        if "generatedHash" in contract:
            print(f"    generatedHash: {contract.get('generatedHash')}")
        if "command" in contract:
            print(f"    command      : {contract.get('command')}")
        if "exitCode" in contract:
            print(f"    exitCode     : {contract.get('exitCode')}")
        if contract.get("diffPath"):
            print(f"    diffPath     : {contract.get('diffPath')}")
    else:
        print(f"  Contract check: missing artifacts/pr-packets/{run_id}/contract-check.json")

    if impact.get("state") != "DONE":
        print("  Evidence:")
        print(f"    - artifacts/pr-packets/{run_id}/summary.md")
        print(f"    - artifacts/pr-packets/{run_id}/contract-check.json")
        print(f"    - artifacts/pr-packets/{run_id}/contract-check.diff.txt")
        print(f"    - artifacts/pr-packets/{run_id}/impact-report.json")
        print(f"    - artifacts/coordination/{run_id}/planner/intent.json")

    return 0 if impact.get("state") == "DONE" else 1


def run_ticket(
    task: str,
    run_id: str,
    ui_mode: str = "tui",
    web_port: int = DEFAULT_WEB_PORT,
    state_file: Optional[Path] = None,
    start_web_server: bool = True,
    agent_sandbox_mode: str = _DEFAULT_AGENT_SANDBOX_MODE,
    task_mode: str = _DEFAULT_TASK_MODE,
    bypass_approvals_and_sandbox: bool = False,
    model: Optional[str] = None,
    model_provider: Optional[str] = None,
) -> int:
    task_mode = infer_task_mode(task, task_mode)
    require_file_changes = task_mode == "code"
    codex_cmd = find_codex_command()
    coord_run = COORD_BASE / run_id
    packet_dir = PACKET_BASE / run_id
    if state_file is None:
        state_file = coord_run / "live-state.json"
    coord_run.mkdir(parents=True, exist_ok=True)
    packet_dir.mkdir(parents=True, exist_ok=True)

    server: Optional[http.server.HTTPServer] = None
    if ui_mode == "web":
        try:
            if start_web_server:
                server, web_port = start_web_dashboard_server(state_file, web_port)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            return 1
        if start_web_server:
            print(f"Web dashboard: http://127.0.0.1:{web_port}/")
        write_state_snapshot(
            state_file,
            {
                "runId": run_id,
                "task": task,
                "taskMode": task_mode,
                "overallState": "RUNNING",
                "tick": 0,
                "updatedAt": now_iso(),
                "planning": [],
                "agents": [],
            },
        )

    planner_sandbox_mode = agent_sandbox_mode if require_file_changes else "read-only"
    worker_sandbox_mode = agent_sandbox_mode if require_file_changes else "read-only"
    plan, planner_result = run_planner(
        task,
        codex_cmd,
        run_id,
        task_mode=task_mode,
        sandbox_mode=planner_sandbox_mode,
        bypass_approvals_and_sandbox=bypass_approvals_and_sandbox,
        model=model,
        model_provider=model_provider,
    )
    scope_ok, scope_errors = validate_scope_rules(plan)

    lock = threading.Lock()
    agents: List[AgentState] = []
    for item in plan:
        coord_dir = coord_run / item.name
        workspace = WORKTREE_ROOT / run_id / item.name
        create_worktree(workspace)
        state = AgentState(
            name=item.name,
            scope=item.scope,
            objective=item.objective,
            workspace=workspace,
            coord_dir=coord_dir,
            status_path=coord_dir / "status.json",
            intent_path=coord_dir / "intent.json",
            impact_path=coord_dir / "impact-report.json",
            blocker_path=coord_dir / "blocker.json",
        )
        dump_json(
            state.intent_path,
            {
                "agent": state.name,
                "runId": run_id,
                "scope": state.scope,
                "objective": state.objective,
                "createdAt": now_iso(),
            },
        )
        state.started_at = now_iso()
        write_status(state, run_id)
        agents.append(state)

    threads = []
    for state in agents:
        thread = threading.Thread(
            target=run_agent,
            args=(
                state,
                codex_cmd,
                lock,
                run_id,
                task_mode,
                require_file_changes,
                worker_sandbox_mode,
                bypass_approvals_and_sandbox,
                model,
                model_provider,
            ),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    tick = 0
    while any(t.is_alive() for t in threads):
        tick += 1
        with lock:
            snapshot = build_dashboard_payload(run_id, task, plan, agents, "RUNNING", tick)
        write_state_snapshot(state_file, snapshot)
        if ui_mode == "tui":
            print("\x1b[2J\x1b[H", end="")
            print(render_dashboard(run_id, task, plan, agents, "RUNNING", False, tick))
        time.sleep(WEB_REFRESH if ui_mode == "web" else DASH_REFRESH)

    for t in threads:
        t.join()

    overall = "DONE"
    if planner_result.exit_code != 0:
        overall = "BLOCKED"
    if not scope_ok:
        overall = "BLOCKED"

    artifact_errors = validate_required_artifacts(run_id, agents)
    if require_file_changes and overall == "DONE" and not any(agent.changed_files for agent in agents):
        overall = "BLOCKED"
        artifact_errors.append("No agent produced any file changes.")
    if artifact_errors:
        overall = "BLOCKED"

    if require_file_changes:
        merge_result = check_mergeability(agents, run_id)
        if not merge_result.get("passed"):
            overall = "BLOCKED"

        if needs_contract_check(agents):
            contract = run_contract_check(run_id, packet_dir)
            ensure_final_contract_files(packet_dir, contract)
            if contract.get("status") != "PASS":
                overall = "BLOCKED"
        else:
            contract = {
                "runId": run_id,
                "status": "SKIPPED",
                "command": "skipped (no protocol-sensitive files changed)",
                "exitCode": 0,
                "timestamp": now_iso(),
                "stdout": "",
                "stderr": "",
            }
            ensure_final_contract_files(packet_dir, contract)
    else:
        merge_result = {
            "passed": True,
            "details": [{"mode": "advisory", "note": "Mergeability skipped for advisory guidance tasks."}],
            "mergedDiff": "",
            "patches": [],
        }
        contract = {
            "runId": run_id,
            "status": "PASS",
            "command": "skipped (advisory task mode)",
            "exitCode": 0,
            "timestamp": now_iso(),
            "stdout": "",
            "stderr": "",
        }
        ensure_final_contract_files(packet_dir, contract)

    with open(packet_dir / "diff.patch", "w", encoding="utf-8") as fp:
        if require_file_changes and merge_result.get("passed") and merge_result.get("mergedDiff"):
            fp.write(str(merge_result.get("mergedDiff")))
        elif require_file_changes:
            for agent in agents:
                fp.write(f"\n# {agent.name}\n")
                fp.write(collect_diff(agent.workspace))
        else:
            fp.write("# Advisory task mode: no code diff generated.\n")

    test_lines = [
        f"run_id: {run_id}",
        f"overall: {overall}",
        f"planner_exit: {planner_result.exit_code}",
        "scope_ok: %s" % scope_ok,
    ]
    if scope_errors:
        test_lines.extend([f"scope_issue: {line}" for line in scope_errors])
    test_lines.append(f"mergeable: {merge_result.get('passed')}")
    test_lines.append(f"contract_status: {contract.get('status')}")
    if artifact_errors:
        test_lines.extend([f"artifact_missing: {line}" for line in artifact_errors])
    dump_text(packet_dir / "test-logs.txt", "\n".join(test_lines) + "\n")

    impact = {
        "runId": run_id,
        "task": task,
        "taskMode": task_mode,
        "state": overall,
        "scopeRulesOk": scope_ok,
        "scopeIssues": scope_errors,
        "artifactErrors": artifact_errors,
        "mergeability": merge_result,
        "contract": {
            "status": contract.get("status"),
            "command": contract.get("command"),
            "exitCode": contract.get("exitCode", contract.get("code", 2)),
        },
        "agents": [
            {
                "name": a.name,
                "scope": a.scope,
                "state": a.status,
                "exitCode": a.exit_code,
                "changedFiles": a.changed_files,
                "blockerReason": a.blocker_reason,
                "lastMessage": a.last_message,
            }
            for a in agents
        ],
    }
    dump_json(packet_dir / "impact-report.json", impact)

    summary = [
        "# PR Packet Summary",
        "",
        f"Run ID: {run_id}",
        f"Overall state: {overall}",
        "",
        "## Evidence",
        f"- artifacts/pr-packets/{run_id}/diff.patch",
        f"- artifacts/pr-packets/{run_id}/test-logs.txt",
        f"- artifacts/pr-packets/{run_id}/contract-check.json",
        f"- artifacts/pr-packets/{run_id}/contract-check.diff.txt",
        f"- artifacts/pr-packets/{run_id}/impact-report.json",
        f"- artifacts/pr-packets/{run_id}/summary.md",
    ]
    if overall == "DONE":
        summary.extend(["", "Status: READY_TO_MERGE"])
        if not require_file_changes:
            summary.extend(["", "## Agent guidance"])
            for agent in agents:
                if agent.last_message:
                    summary.append(f"- {agent.name}: {agent.last_message.strip()[:600]}")
    else:
        blocked_reasons: List[str] = []
        for agent in agents:
            if agent.status == "BLOCKED":
                reason = agent.blocker_reason or "UNKNOWN"
                blocked_reasons.append(f"{agent.name} BLOCKED: {reason}")
                blocked_reasons.append(
                    f"Evidence: artifacts/coordination/{run_id}/{agent.name}/blocker.json"
                )

        if not blocked_reasons:
            blocked_reasons.append("No explicit agent blocker reason captured.")

        summary.extend(["", "Status: BLOCKED"])
        summary.extend([f"- {item}" for item in artifact_errors])
        summary.extend([f"- {item}" for item in blocked_reasons])
        if not scope_ok:
            summary.append("- scope overlap detected")
        if not merge_result.get("passed"):
            summary.append("- mergeability check failed")
            for detail in merge_result.get("details", []):
                if isinstance(detail, dict):
                    if detail.get("checkStderr"):
                        summary.append(f"- merge check stderr ({detail.get('agent', 'unknown')}): {str(detail.get('checkStderr')).strip()[:240]}")
                    if detail.get("checkCode") not in (None, 0):
                        summary.append(f"- merge check code ({detail.get('agent', 'unknown')}): {detail.get('checkCode')}")
        if contract.get("status") != "PASS":
            summary.append("- contract check failed")
            summary.append(f"- Contract details: artifacts/pr-packets/{run_id}/contract-check.json")
            if contract.get("expectedHash"):
                summary.append(f"- expected hash: {contract.get('expectedHash')}")
            if contract.get("generatedHash"):
                summary.append(f"- generated hash: {contract.get('generatedHash')}")
            if contract.get("command"):
                summary.append(f"- command: {contract.get('command')}")
            if contract.get("exitCode") not in (None, 2):
                summary.append(f"- contract exitCode: {contract.get('exitCode')}")
    dump_text(packet_dir / "summary.md", "\n".join(summary) + "\n")

    final_payload = build_dashboard_payload(run_id, task, plan, agents, overall, tick)
    final_payload["taskMode"] = task_mode
    if ui_mode == "web":
        final_payload["overallState"] = overall
        final_payload["finished"] = True
    write_state_snapshot(state_file, final_payload)

    if ui_mode == "tui":
        print("\x1b[2J\x1b[H", end="")
        print(render_dashboard(run_id, task, plan, agents, overall, True, tick))

    print(f"\nEvidence: artifacts/pr-packets/{run_id}")
    if server:
        server.shutdown()
        server.server_close()

    return 0 if overall != "BLOCKED" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex multi-agent runtime orchestrator")
    sub = parser.add_subparsers(dest="command")
    sandbox_default = normalize_sandbox_mode(os.environ.get(_SANDBOX_ENV, _DEFAULT_AGENT_SANDBOX_MODE))
    task_mode_default = normalize_task_mode(os.environ.get(_TASK_MODE_ENV, _DEFAULT_TASK_MODE))
    bypass_default = env_flag_enabled(os.environ.get(_BYPASS_SANDBOX_ENV))
    model_default = os.environ.get(_MODEL_ENV)
    model_provider_default = os.environ.get(_MODEL_PROVIDER_ENV)

    run = sub.add_parser("run")
    run.add_argument("task", nargs="?", help="raw user task")
    run.add_argument(
        "--prompt",
        dest="prompt",
        help="prompt to run (optional for web mode when using in-browser composer)",
    )
    run.add_argument("--run-id", help="optional run identifier")
    run.add_argument("--ui", choices=["tui", "web"], default="tui", help="dashboard UI: tui or web")
    run.add_argument(
        "--agent-sandbox",
        default=sandbox_default,
        choices=_ALLOWED_SANDBOX_MODES,
        help=(
            "Codex sandbox mode for worker agents. "
            "Use 'danger-full-access' only in trusted, isolated environments."
        ),
    )
    run.add_argument(
        "--task-mode",
        default=task_mode_default,
        choices=_ALLOWED_TASK_MODES,
        help="task execution mode: auto, code, or advisory",
    )
    run.add_argument(
        "--bypass-approvals-and-sandbox",
        action="store_true",
        default=bypass_default,
        help=(
            "pass --dangerously-bypass-approvals-and-sandbox to Codex (unsafe, trusted environments only). "
            f"Can also be enabled via {_BYPASS_SANDBOX_ENV}=1."
        ),
    )
    run.add_argument(
        "--model",
        default=model_default,
        help=f"optional model override passed to codex exec (env: {_MODEL_ENV})",
    )
    run.add_argument(
        "--model-provider",
        default=model_provider_default,
        help=f"optional model provider key via config override (env: {_MODEL_PROVIDER_ENV})",
    )
    run.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help="dashboard port for web mode")

    demo = sub.add_parser("demo", help="run the built-in demo task")
    demo.add_argument("--ui", choices=["tui", "web"], default="tui", help="dashboard UI: tui or web")
    demo.add_argument(
        "--agent-sandbox",
        default=sandbox_default,
        choices=_ALLOWED_SANDBOX_MODES,
        help="Codex sandbox mode for worker agents",
    )
    demo.add_argument(
        "--task-mode",
        default=task_mode_default,
        choices=_ALLOWED_TASK_MODES,
        help="task execution mode: auto, code, or advisory",
    )
    demo.add_argument(
        "--bypass-approvals-and-sandbox",
        action="store_true",
        default=bypass_default,
        help=(
            "pass --dangerously-bypass-approvals-and-sandbox to Codex (unsafe, trusted environments only). "
            f"Can also be enabled via {_BYPASS_SANDBOX_ENV}=1."
        ),
    )
    demo.add_argument(
        "--model",
        default=model_default,
        help=f"optional model override passed to codex exec (env: {_MODEL_ENV})",
    )
    demo.add_argument(
        "--model-provider",
        default=model_provider_default,
        help=f"optional model provider key via config override (env: {_MODEL_PROVIDER_ENV})",
    )
    demo.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help="dashboard port for web mode")

    inspect = sub.add_parser("inspect", help="print root-cause summary for a completed run")
    inspect.add_argument("run_id", help="run-id under artifacts/")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "demo":
        task = (
            "Generate an implementation plan for adding a small task management interface. "
            "Focus on practical phases, risks, and sequencing."
        )
        run_id = generate_run_id()
        ui_mode = args.ui
        port = args.port
    elif args.command == "inspect":
        return inspect_run(args.run_id)
    else:
        task = args.task or args.prompt
        run_id = args.run_id or generate_run_id()
        ui_mode = args.ui
        port = args.port
        if not task:
            if ui_mode != "web":
                parser.error("task is required unless --ui web is used.")
            return run_web_prompt_mode(
                run_id=run_id,
                web_port=port,
                agent_sandbox_mode=args.agent_sandbox,
                task_mode=args.task_mode,
                bypass_approvals_and_sandbox=args.bypass_approvals_and_sandbox,
                model=args.model,
                model_provider=args.model_provider,
            )

    return run_ticket(
        task,
        run_id,
        ui_mode=ui_mode,
        web_port=port,
        agent_sandbox_mode=args.agent_sandbox,
        task_mode=args.task_mode,
        bypass_approvals_and_sandbox=args.bypass_approvals_and_sandbox,
        model=args.model,
        model_provider=args.model_provider,
    )


if __name__ == "__main__":
    raise SystemExit(main())
