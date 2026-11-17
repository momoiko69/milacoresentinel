#!/usr/bin/env python3
"""mcSentinel pre/post tool execution hook gate (Antigravity / AI Studio compatible)."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

SENTINEL_DIR = Path(__file__).resolve().parent
AUDIT_LOG = SENTINEL_DIR / "reports" / "hook_audit.jsonl"

_DENY_PATTERNS = (
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME|\*)(?=\s|$)", re.I),
    re.compile(r"\bdel\s+/[sqf]+\s+[a-zA-Z]:\\", re.I),
    re.compile(r"\b(format|mkfs|diskpart|cipher\s+/w)\b", re.I),
    re.compile(r":\(\)\s*\{\s*:\|\s*:&\s*\}\s*;:", re.I),
)


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


def _record_audit(event: str, caller: str, target: str, decision: str, reason: str = "") -> None:
    try:
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
    raw = sys.stdin.read().strip()
    data = json.loads(raw) if raw else {}
    args = data.get("tool_call", {}).get("args", {})
    cmd_str = str(args.get("command") or args.get("cmd") or raw)
    print(json.dumps(check_command(cmd_str, caller="agent_hook")))
