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

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case
from jevx.py import choice
from jevx.py import noul
from jevx.py import score
from jevx.py import vector
from jevx.risk import blast_of
from jevx.risk import risk
from jevx.risk import verdict

TRIAGE = vector(
    doc_type=choice(
        {
            "question": "What kind of document is this?",
            "focus": "Classify the source document, not the requested action.",
        },
        {
            "invoice": {"what": "A request for payment for supplied goods or services."},
            "statement": {"what": "A summary of account activity or balances."},
            "quote": {"what": "A proposed price before the work or sale."},
            "reminder": {"what": "A notice about an existing payment obligation."},
        },
    ),
    fraud=noul(
        {
            "question": "Does the source document show fraud patterns?",
            "inspect": ["sender", "amount", "account details"],
        },
        true={"what": "Evidence of impersonation, alteration, or deceptive payment changes."},
        false={"what": "No concrete fraud indicator in the supplied document."},
    ),
    already_paid=noul(
        {
            "question": "Was this invoice already paid?",
            "compare": ["invoice number", "vendor", "amount"],
        },
        true={"what": "The ledger contains a payment for this same obligation."},
        false={"what": "No matching payment is present in the ledger."},
    ),
    wrong_vendor=noul(
        {
            "question": "Does the invoice name the wrong vendor or entity?",
            "compare": ["invoice", "purchase order"],
        },
        true={"what": "The named legal entity does not match the approved vendor."},
        false={"what": "The vendor and purchasing entity match."},
    ),
    po_status=choice(
        {"question": "How does the purchase order cover this invoice?"},
        {
            "priced": {"what": "The invoiced line and amount are covered."},
            "component": {"what": "The invoice is for a component of an approved order."},
            "extra": {"what": "The invoice includes an unapproved additional item."},
            "not_ours": {"what": "The order belongs to another entity or buyer."},
        },
    ),
    urgency=score(
        {
            "question": "How urgent is payment pressure?",
            "focus": "Judge documented terms, not threatening wording alone.",
        },
        (
            {"summary": "routine", "signals": ["normal due date", "no service risk"]},
            {"summary": "pressing", "signals": ["due soon", "limited service impact"]},
            {"summary": "threatening", "signals": ["overdue", "credible interruption or penalty"]},
        ),
    ),
)


FIELD_CHECK = vector(
    hallucinated=noul(
        {
            "question": "Is an extracted value absent from the source document?",
            "compare": ["extracted", "doc"],
        },
        true={"what": "The value is invented or unsupported by the document."},
        false={"what": "The source document contains the extracted value."},
    ),
    off_target=noul(
        {
            "question": "Was a different field extracted?",
            "compare": ["field name", "extracted value", "doc"],
        },
        true={"what": "The value belongs to a different field or entity."},
        false={"what": "The value belongs to the requested field."},
    ),
    unreasonable=noul(
        {
            "question": "Is the extracted value unreasonable?",
            "inspect": ["currency", "totals", "dates"],
        },
        true={"what": "The value conflicts with arithmetic or the document context."},
        false={"what": "The value is plausible and internally consistent."},
    ),
    absence_wrong=noul(
        {
            "question": "Was a supposedly missing value actually present?",
            "compare": ["extracted", "doc"],
        },
        true={"what": "The source contains a value that extraction omitted."},
        false={"what": "The value is genuinely absent from the source."},
    ),
)

RELEASE = vector(
    withholds=noul(
        {
            "question": "Should the approver withhold payment?",
            "consider": ["duplicate", "vendor mismatch", "unsupported amount"],
        },
        true={"what": "A blocking approval condition applies."},
        false={"what": "No blocking approval condition applies."},
    ),
    over_cap=noul(
        {
            "question": "Is the invoice above the approved cap or purchase order?",
            "compare": ["invoice total", "approved amount"],
        },
        true={"what": "The invoice total exceeds the authorized amount."},
        false={"what": "The invoice total is within the authorized amount."},
    ),
)


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
    t = TRIAGE.ask({**doc, "text": text[:2000]}, client=s1)  # 1 request
    if t.fraud >= 0.70:
        return {"action": "FRAUD_REVIEW", "problems": problems}
    if t.doc_type.choice != "invoice":
        return {
            "action": "HOLD",
            "why": f"not an invoice: {t.doc_type.choice}",
            "problems": problems,
        }
    inv_nos = {p.get("inv_no") for p in ledger}
    if t.already_paid >= 0.70 or any(_fuzzy_dupe(doc, p) > 0.9 for p in ledger):
        return {"action": "DUPLICATE_REVIEW", "problems": problems}
    if t.wrong_vendor >= 0.65:
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
    po = t.po_status.choice
    if po in ("priced", "component") and doc.get("po_total") is not None:
        tol = max(50.0, 0.02 * total)
        if abs(total - float(doc["po_total"])) > tol:
            problems.append("po_variance")
    fc = FIELD_CHECK.ask({"doc": text[:2000], "extracted": inv}, client=s1)  # 1 request
    if any(
        value >= 0.70
        for value in (fc.hallucinated, fc.off_target, fc.unreasonable, fc.absence_wrong)
    ):
        fix = s2.ask(
            f"Verifier flags on {inv}: propose short_pay_lines, dispute_reason, "
            f"corrected_request with citations. PO status: {po}."
        )
        return {"action": "REQUEST_CORRECTED", "proposal": fix, "problems": problems}

    home_total = total * rate
    blast = blast_of(min(home_total / 10000, 1.0), 0.7 if po in ("extra", "not_ours") else 0.1)
    r = RELEASE.ask({"invoice": inv, "po_status": po}, client=s1)  # 1 request
    conf = 1.0 - max(float(r.over_cap), float(r.withholds))
    v = verdict(risk(blast, conf), review_at=1.5, refuse_at=4.0)
    out = list(ledger) + [inv]
    return case[
        r.withholds >= 0.60 or v == "refuse" : {
            "action": "HOLD",
            "why": "withheld or risk-refused",
            "risk": v,
            "problems": problems,
        },
        v == "review" or r.over_cap >= 0.65 : {
            "action": "SHORT_PAY" if po != "not_ours" else "PROCUREMENT_REVIEW",
            "problems": problems,
        },
        ... : {
            "action": "RELEASED",
            "inv_no": inv.get("inv_no"),
            "ledger": out,
            "problems": problems,
        },
    ].ask({})
