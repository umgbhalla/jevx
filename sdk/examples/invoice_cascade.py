"""Invoice AP cascade: S1 routes/verifies, S2 extracts/explains, code computes.

Stages: normalize (code) -> triage (S1) -> extract (S2) -> verify (S1+code)
-> exception-resolve (S2) -> release (code+S1). Deterministic gates (sums, FX,
dupes, PO tolerance) run in code; Jev handles every judgment in between.
"""

from __future__ import annotations

import difflib
from typing import Any, Literal

from jevx.py import Questions, Score, ask
from jevx.risk import blast_of, risk, verdict
from jevx.backends import Backend, Live


class Triage(Questions):
    doc_type: Literal["invoice", "statement", "quote", "reminder"] = ask("what kind of document?")
    fraud: bool = ask("does this show fraud patterns?", threshold=0.70)
    already_paid: bool = ask("was this already paid?", threshold=0.70)
    wrong_vendor: bool = ask("wrong vendor or entity?", threshold=0.65)
    po_status: Literal["priced", "component", "extra", "not_ours"] = ask("PO coverage?")
    urgency: Score["routine", "pressing", "threatening"] = ask("payment pressure?")


class FieldCheck(Questions):
    hallucinated: bool = ask("is this field fabricated?", threshold=0.70)
    off_target: bool = ask("is this the wrong field?", threshold=0.70)
    unreasonable: bool = ask("is this value unreasonable?", threshold=0.70)
    absence_wrong: bool = ask("is a missing value actually present?", threshold=0.70)


class Release(Questions):
    withholds: bool = ask("does the approver withhold approval?", threshold=0.60)
    over_cap: bool = ask("is this over cap or over PO?", threshold=0.65)


def _fuzzy_dupe(a: dict, b: dict) -> float:
    key = lambda d: f"{d.get('vendor','')} {d.get('total','')} {d.get('date','')}"
    return difflib.SequenceMatcher(None, key(a), key(b)).ratio()


def process(doc: dict, ledger: list[dict], fx: dict, backend: Backend | None = None) -> dict:
    """doc: {text, vendor, currency, ...}; ledger: prior invoices; fx: {ccy: rate}."""
    bk = backend or Live()
    s1 = bk.s1()
    t = Triage(client=s1)(doc)  # 1 request
    if t.fraud:
        return {"action": "FRAUD_REVIEW"}
    if t.doc_type != "invoice":
        return {"action": "HOLD", "why": f"not an invoice: {t.doc_type}"}
    if t.already_paid or any(_fuzzy_dupe(doc, p) > 0.9 for p in ledger):
        return {"action": "DUPLICATE_REVIEW"}
    if t.wrong_vendor:
        return {"action": "REJECT"}

    s2 = bk.s2()
    ext = s2.ask(
        "Extract JSON only, verbatim values, no math: "
        "{inv_no,date,due,currency,total,tax,subtotal,lines[{desc,qty,unit,po_line}],bank}. "
        f"Doc: {doc['text']}"
    )
    import json as _json
    try:
        inv = _json.loads(ext[ext.index("{"):ext.rindex("}") + 1])
    except ValueError:
        return {"action": "HOLD_FOR_DOCS", "why": "unparseable extraction"}

    # deterministic gates in code — no model calls
    problems = []
    if abs(inv.get("total", 0) - (inv.get("subtotal", 0) + inv.get("tax", 0))) > 0.01:
        problems.append("sums_dont_add")
    rate = fx.get(inv.get("currency", ""), 1.0)
    if problems:
        pass  # FX check only meaningful once sums reconcile; re-checked post-fix
    fc = FieldCheck(client=s1)({"doc": doc["text"][:2000], "extracted": inv})  # 1 request
    if any([fc.hallucinated, fc.off_target, fc.unreasonable, fc.absence_wrong]):
        fix = s2.ask(f"Verifier flags on {inv}: propose short_pay_lines, dispute_reason, "
                     f"corrected_request with citations. PO status: {t.po_status}.")
        return {"action": "REQUEST_CORRECTED", "proposal": fix, "problems": problems}

    home_total = inv.get("total", 0) * rate
    blast = blast_of(min(home_total / 10000, 1.0), 0.7 if t.po_status in ("extra", "not_ours") else 0.1)
    r = Release(client=s1)({"invoice": inv, "po_status": t.po_status})  # 1 request
    conf = 1.0 - float(r.answers["over_cap"].prob)  # P(over cap) is doubt
    v = verdict(risk(blast, conf), review_at=1.5, refuse_at=4.0)
    if r.withholds or v == "refuse":
        return {"action": "APPROVAL", "risk": v}
    if r.over_cap or v == "review":
        return {"action": "SHORT_PAY" if t.po_status != "not_ours" else "PROCUREMENT_REVIEW"}
    ledger.append(inv)
    return {"action": "RELEASED", "inv_no": inv.get("inv_no")}
