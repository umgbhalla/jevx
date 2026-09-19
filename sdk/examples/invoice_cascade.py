"""Invoice AP cascade: S1 routes/verifies, S2 extracts/explains, code computes.

Stages: normalize (code) -> triage (S1) -> extract (S2) -> verify (S1+code)
-> exception-resolve (S2) -> release (code+S1). Deterministic gates (sums, FX,
exact+dupes, PO tolerance) run in code; Jev handles every judgment in between.
Never mutates caller state; problems thread through every return.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Literal

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask
from jevx.risk import blast_of
from jevx.risk import risk
from jevx.risk import verdict


class Triage(Questions):
    doc_type: Literal["invoice", "statement", "quote", "reminder"] = ask("what kind of document?")
    fraud: bool = ask("does this show fraud patterns?", threshold=0.70)
    already_paid: bool = ask("was this already paid?", threshold=0.70)
    wrong_vendor: bool = ask("wrong vendor or entity?", threshold=0.65)
    po_status: Literal["priced", "component", "extra", "not_ours"] = ask("PO coverage?")
    urgency: Score[Literal["routine", "pressing", "threatening"]] = ask("payment pressure?")


class FieldCheck(Questions):
    hallucinated: bool = ask("is this field fabricated?", threshold=0.70)
    off_target: bool = ask("is this the wrong field?", threshold=0.70)
    unreasonable: bool = ask("is this value unreasonable?", threshold=0.70)
    absence_wrong: bool = ask("is a missing value actually present?", threshold=0.70)


class Release(Questions):
    withholds: bool = ask("does the approver withhold approval?", threshold=0.60)
    over_cap: bool = ask("is this over cap or over PO?", threshold=0.65)


REQUIRED = ("inv_no", "date", "currency", "total", "tax", "subtotal")


def _fuzzy_key(d: dict) -> str:
    return f"{d.get('vendor', '')} {d.get('total', '')} {d.get('date', '')}"


def _fuzzy_dupe(a: dict, b: dict) -> float:
    return difflib.SequenceMatcher(None, _fuzzy_key(a), _fuzzy_key(b)).ratio()


def _parse_extraction(text: str) -> dict | None:
    """Strip fences, slice largest brace block, require keys."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        start, end = t.index("{"), t.rindex("}")
    except ValueError:
        return None
    try:
        inv = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(inv, dict) or any(k not in inv for k in REQUIRED):
        return None
    return inv


@ensure(
    lambda *a, result=None, **k: (
        result is not None
        and result["action"]
        in (
            "FRAUD_REVIEW",
            "HOLD",
            "DUPLICATE_REVIEW",
            "REJECT",
            "HOLD_FOR_DOCS",
            "REQUEST_CORRECTED",
            "APPROVAL",
            "SHORT_PAY",
            "PROCUREMENT_REVIEW",
            "RELEASED",
        )
    ),
    msg="known AP action",
)
def process(doc: dict, ledger: list[dict], fx: dict, backend: Backend | None = None) -> dict:
    """doc: {text, vendor, currency, ...}; ledger: prior invoices; fx: {ccy: rate}.

    fx rates must be > 0; missing currency is a problem, never a silent 1.0.
    """
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    text = doc.get("text", "")
    problems: list[str] = []
    t = Triage(client=s1).ask({**doc, "text": text[:2000]})  # 1 request
    if t.fraud:
        return {"action": "FRAUD_REVIEW", "problems": problems}
    if t.doc_type != "invoice":
        return {"action": "HOLD", "why": f"not an invoice: {t.doc_type}", "problems": problems}
    inv_nos = {p.get("inv_no") for p in ledger}
    if t.already_paid or any(_fuzzy_dupe(doc, p) > 0.9 for p in ledger):
        return {"action": "DUPLICATE_REVIEW", "problems": problems}
    if t.wrong_vendor:
        return {"action": "REJECT", "problems": problems}

    raw = s2.ask(
        "Extract JSON only, verbatim values, no math: "
        "{inv_no,date,due,currency,total,tax,subtotal,lines[{desc,qty,unit,po_line}],bank}. "
        f"Doc: {text[:4000]}"
    )
    inv = _parse_extraction(raw)
    if inv is None:
        return {"action": "HOLD_FOR_DOCS", "why": "unparseable extraction", "problems": problems}
    if inv.get("inv_no") in inv_nos:
        return {"action": "DUPLICATE_REVIEW", "why": "exact inv_no match", "problems": problems}

    total = inv.get("total", 0)
    if abs(total - (inv.get("subtotal", 0) + inv.get("tax", 0))) > 0.01:
        problems.append("sums_dont_add")
    ccy = inv.get("currency", "")
    rate = fx.get(ccy)
    if rate is None or rate <= 0:
        problems.append(f"missing_fx:{ccy}")
        rate = 1.0
    po = t.po_status
    if po in ("priced", "component") and doc.get("po_total") is not None:
        tol = max(50.0, 0.02 * total)
        if abs(total - float(doc["po_total"])) > tol:
            problems.append("po_variance")
    fc = FieldCheck(client=s1).ask({"doc": text[:2000], "extracted": inv})  # 1 request
    if any([fc.hallucinated, fc.off_target, fc.unreasonable, fc.absence_wrong]):
        fix = s2.ask(
            f"Verifier flags on {inv}: propose short_pay_lines, dispute_reason, "
            f"corrected_request with citations. PO status: {po}."
        )
        return {"action": "REQUEST_CORRECTED", "proposal": fix, "problems": problems}

    home_total = total * rate
    blast = blast_of(min(home_total / 10000, 1.0), 0.7 if po in ("extra", "not_ours") else 0.1)
    r = Release(client=s1).ask({"invoice": inv, "po_status": po})  # 1 request
    conf = 1.0 - max(float(r.answers["over_cap"].prob), float(r.answers["withholds"].prob))
    v = verdict(risk(blast, conf), review_at=1.5, refuse_at=4.0)
    match (r.withholds, v, r.over_cap, po):
        case (True, _, _, _) | (_, "refuse", _, _):
            return {
                "action": "HOLD",
                "why": "withheld or risk-refused",
                "risk": v,
                "problems": problems,
            }
        case (_, "review", _, _) | (_, _, True, _):
            action = "SHORT_PAY" if po != "not_ours" else "PROCUREMENT_REVIEW"
            return {"action": action, "problems": problems}
        case _:
            out = list(ledger) + [inv]
            return {
                "action": "RELEASED",
                "inv_no": inv.get("inv_no"),
                "ledger": out,
                "problems": problems,
            }
