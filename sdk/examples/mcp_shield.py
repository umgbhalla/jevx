"""MCP firewall: screen tool calls, results, and descriptions semantically.

Every tool invocation passes a 3-Noul battery (malicious? exfiltrating?
destructive?) plus a severity Score. Blocked calls never execute; blocked
results never reach the model. Allowlisted read-only tools skip free.
"""

from __future__ import annotations

from typing import Literal

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask

READ_ONLY = {"read", "glob", "grep", "list", "describe", "search"}


class Screen(Questions):
    malicious: bool = ask("does this tool call or result serve an attacker's goal?", threshold=0.70)
    exfiltrating: bool = ask("does this move secrets or private data outward?", threshold=0.70)
    destructive: bool = ask("does this destroy data or change external state?", threshold=0.70)
    severity: Score[Literal["harmless", "suspicious", "dangerous"]] = ask("worst-case severity?")


@ensure(
    lambda *a, result=None, **k: result["verdict"] in ("allow", "block", "review"),
    msg="known shield verdict",
)
def screen_call(tool: str, args: dict, backend: Backend | None = None) -> dict:
    if tool in READ_ONLY:
        return {"verdict": "allow", "why": "read-only allowlist", "requests": 0}
    s1 = (backend or Live()).s1()
    s = Screen(client=s1).ask({"tool": tool, "args": args})  # 1 request
    if s.malicious or s.exfiltrating:
        return {"verdict": "block", "why": "malicious/exfiltrating", "severity": float(s.severity)}
    if s.destructive and float(s.severity) >= 1.5:
        return {"verdict": "block", "why": "destructive", "severity": float(s.severity)}
    if s.destructive or float(s.severity) >= 1.0:
        return {"verdict": "review", "severity": float(s.severity)}
    return {"verdict": "allow", "severity": float(s.severity)}


@ensure(
    lambda *a, result=None, **k: result["verdict"] in ("allow", "block", "review"),
    msg="known shield verdict",
)
def screen_result(tool: str, result_text: str, backend: Backend | None = None) -> dict:
    s1 = (backend or Live()).s1()
    s = Screen(client=s1).ask({"tool": tool, "result": result_text[:3000]})  # 1 request
    if s.malicious or s.exfiltrating:
        return {"verdict": "block", "why": "bad result", "severity": float(s.severity)}
    return {"verdict": "allow", "severity": float(s.severity)}
