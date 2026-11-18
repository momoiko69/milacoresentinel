#!/usr/bin/env python3
"""mcSentinel pre/post tool execution hook gate (Antigravity / AI Studio compatible)."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

SENTINEL_DIR = Path(__file__).resolve().parent
AUDIT_LOG = SENTINEL_DIR / "reports" / "hook_audit.jsonl"
MAX_WRITE_BYTES = 10 * 1024 * 1024
_AUDIT_LOCK = threading.Lock()

_DENY_PATTERNS = (
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME|\*)(?=\s|$)", re.I),
    re.compile(r"\bdel\s+/[sqf]+\s+[a-zA-Z]:\\", re.I),
    re.compile(r"\b(format|mkfs|diskpart|cipher\s+/w)\b", re.I),
    re.compile(r":\(\)\s*\{\s*:\|\s*:&\s*\}\s*;:", re.I),
)

_SENSITIVE_FILE_PATTERNS = (
    re.compile(r"(?:^|/)\.env(?:\.[^/]+)?$", re.I),
    re.compile(r"(?:^|/)\.git/(?:config|hooks(?:/|$))", re.I),
    re.compile(r"(?:^|/)[^/]+\.(?:pem|key)$", re.I),
    re.compile(r"(?:^|/)id_(?:rsa|ed25519)(?:\.[^/]+)?$", re.I),
)

_WRITE_OPS = frozenset({
    "write_file", "edit_file", "delete_file",
    "write_to_file", "replace_file_content", "patch_file",
})
_FILE_TOOL_NAMES = _WRITE_OPS | frozenset({"read_file", "list_dir", "search_files", "view_file"})


def check_command(command: str, caller: str = "studio") -> dict:
    """Evaluate a shell command against mcSentinel safety predicates."""
    cmd = (command or "").strip()
    for rx in _DENY_PATTERNS:
        if rx.search(cmd):
            res = {"decision": "deny", "reason": f"Blocked destructive command by mcSentinel gate ({rx.pattern})."}
            _record_audit("pre_tool_execution", caller, cmd[:300], res["decision"], res["reason"])
            return res
    res = {"decision": "allow", "reason": "ok"}
    _record_audit("pre_tool_execution", caller, cmd[:300], "allow", "")
    return res


def check_file_op(op: str, path: str, content_size: int = 0, caller: str = "file_tools") -> dict:
    """Validate file tool operation safety, sensitive paths, and write size caps (fail-closed)."""
    op_norm = (op or "").strip().lower()
    raw_target = str(path or "").strip()
    try:
        if not raw_target:
            res = {"decision": "deny", "reason": "Empty path denied by mcSentinel gate."}
            _record_audit("pre_tool_execution", caller, f"{op_norm}:", "deny", res["reason"])
            return res
        # Reject Windows ADS / device / UNC paths cleanly
        if raw_target.startswith("\\\\") or (":" in raw_target[2:] and not raw_target.startswith("/")):
            res = {"decision": "deny", "reason": f"Blocked unsafe UNC/stream path: {raw_target}"}
            _record_audit("pre_tool_execution", caller, f"{op_norm}:{raw_target[:260]}", "deny", res["reason"])
            return res
        posix_norm = Path(raw_target).expanduser().resolve().as_posix()
        if op_norm in _WRITE_OPS:
            if content_size > MAX_WRITE_BYTES:
                res = {"decision": "deny", "reason": f"Write size {content_size} exceeds 10 MB mcSentinel limit."}
                _record_audit("pre_tool_execution", caller, f"{op_norm}:{posix_norm[:260]}", "deny", res["reason"])
                return res
            for rx in _SENSITIVE_FILE_PATTERNS:
                if rx.search(posix_norm):
                    res = {"decision": "deny", "reason": f"Blocked write/delete to sensitive target by mcSentinel ({rx.pattern})."}
                    _record_audit("pre_tool_execution", caller, f"{op_norm}:{posix_norm[:260]}", "deny", res["reason"])
                    return res
        _record_audit("pre_tool_execution", caller, f"{op_norm}:{posix_norm[:260]}", "allow", "")
        return {"decision": "allow", "reason": "ok"}
    except Exception as exc:
        res = {"decision": "deny", "reason": f"mcSentinel file gate fail-closed: {exc}"}
        _record_audit("pre_tool_execution", caller, f"{op_norm}:{raw_target[:260]}", "deny", res["reason"])
        return res


def record_post_tool(op: str, target: str, ok: bool, detail: str = "", caller: str = "file_tools") -> None:
    """Record a post_tool_execution audit entry without blocking."""
    _record_audit(
        "post_tool_execution",
        caller,
        f"{op}:{str(target)[:260]}",
        "ok" if ok else "error",
        (detail or "")[:240],
    )


def _record_audit(event: str, caller: str, target: str, decision: str, reason: str = "") -> None:
    try:
        with _AUDIT_LOCK:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": event,
                "caller": caller,
                "decision": decision,
                "reason": reason,
                "target": target,
            }
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        raw = sys.stdin.read().strip()
        data = json.loads(raw) if raw else {}
        hook_ev = str(data.get("hook_event_name") or "").strip().lower()
        tc = data.get("tool_call") or {}
        t_name = str(tc.get("name") or "").strip().lower()
        args = tc.get("args") or {}
        if hook_ev == "post_tool_execution":
            record_post_tool(t_name or "tool", str(args.get("path") or args.get("command") or ""), True, caller="agent_hook")
            print(json.dumps({}))
        elif t_name in _FILE_TOOL_NAMES:
            content_bytes = len(str(args.get("content") or args.get("replacement") or "").encode("utf-8"))
            print(json.dumps(check_file_op(t_name, str(args.get("path") or ""), content_size=content_bytes, caller="agent_hook")))
        else:
            cmd_str = str(args.get("command") or args.get("cmd") or raw)
            print(json.dumps(check_command(cmd_str, caller="agent_hook")))
    except Exception as exc:
        print(json.dumps({"decision": "deny", "reason": f"mcSentinel hook error (fail-closed): {exc}"}))
