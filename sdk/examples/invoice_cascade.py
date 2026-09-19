"""Invoice AP cascade: S1 routes/verifies, S2 extracts/explains, code computes.

Stages: normalize (code) -> triage (S1) -> extract (S2) -> verify (S1+code)
-> exception-resolve (S2) -> release (code+S1). Deterministic gates (sums, FX,
exact+dupes, PO tolerance) run in code; Jev handles every judgment in between.
Never mutates caller state; problems thread through every return.
"""

from __future__ import annotations

import difflib

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.risk import blast_of
from jevx.risk import risk
from jevx.risk import verdict

TRIAGE = j.vector(
    doc_type=j.choice(
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
    fraud=j.noul(
        {
            "question": "Does the source document show fraud patterns?",
            "inspect": ["sender", "amount", "account details"],
        },
        true={"what": "Evidence of impersonation, alteration, or deceptive payment changes."},
        false={"what": "No concrete fraud indicator in the supplied document."},
    ),
    already_paid=j.noul(
        {
            "question": "Was this invoice already paid?",
            "compare": ["invoice number", "vendor", "amount"],
        },
        true={"what": "The ledger contains a payment for this same obligation."},
        false={"what": "No matching payment is present in the ledger."},
    ),
    wrong_vendor=j.noul(
        {
            "question": "Does the invoice name the wrong vendor or entity?",
            "compare": ["invoice", "purchase order"],
        },
        true={"what": "The named legal entity does not match the approved vendor."},
        false={"what": "The vendor and purchasing entity match."},
    ),
    po_status=j.choice(
        {"question": "How does the purchase order cover this invoice?"},
        {
            "priced": {"what": "The invoiced line and amount are covered."},
            "component": {"what": "The invoice is for a component of an approved order."},
            "extra": {"what": "The invoice includes an unapproved additional item."},
            "not_ours": {"what": "The order belongs to another entity or buyer."},
        },
    ),
    urgency=j.score(
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


FIELD_CHECK = j.vector(
    hallucinated=j.noul(
        {
            "question": "Is an extracted value absent from the source document?",
            "compare": ["extracted", "doc"],
        },
        true={"what": "The value is invented or unsupported by the document."},
        false={"what": "The source document contains the extracted value."},
    ),
    off_target=j.noul(
        {
            "question": "Was a different field extracted?",
            "compare": ["field name", "extracted value", "doc"],
        },
        true={"what": "The value belongs to a different field or entity."},
        false={"what": "The value belongs to the requested field."},
    ),
    unreasonable=j.noul(
        {
            "question": "Is the extracted value unreasonable?",
            "inspect": ["currency", "totals", "dates"],
        },
        true={"what": "The value conflicts with arithmetic or the document context."},
        false={"what": "The value is plausible and internally consistent."},
    ),
    absence_wrong=j.noul(
        {
            "question": "Was a supposedly missing value actually present?",
            "compare": ["extracted", "doc"],
        },
        true={"what": "The source contains a value that extraction omitted."},
        false={"what": "The value is genuinely absent from the source."},
    ),
)

RELEASE = j.vector(
    withholds=j.noul(
        {
            "question": "Should the approver withhold payment?",
            "consider": ["duplicate", "vendor mismatch", "unsupported amount"],
        },
        true={"what": "A blocking approval condition applies."},
        false={"what": "No blocking approval condition applies."},
    ),
    over_cap=j.noul(
        {
            "question": "Is the invoice above the approved cap or purchase order?",
            "compare": ["invoice total", "approved amount"],
        },
        true={"what": "The invoice total exceeds the authorized amount."},
        false={"what": "The invoice total is within the authorized amount."},
    ),
)


REQUIRED = ("inv_no", "date", "currency", "total", "tax", "subtotal")


def _fuzzy_key(row: dict) -> str:
    return f"{row.get('vendor', '')} {row.get('total', '')} {row.get('date', '')}"


def _duplicate(doc: dict, ledger: list[dict], invoice: dict | None = None) -> bool:
    if invoice and any(invoice.get("inv_no") == row.get("inv_no") for row in ledger):
        return True
    candidate = invoice or doc
    return any(_fuzzy_dupe(candidate, row) > 0.9 for row in ledger)


def _fuzzy_dupe(a: dict, b: dict) -> float:
    return difflib.SequenceMatcher(None, _fuzzy_key(a), _fuzzy_key(b)).ratio()


def _validate_numbers(invoice: dict, doc: dict, fx: dict, po: str) -> dict:
    problems = []
    total = invoice["total"]
    if abs(total - invoice["subtotal"] - invoice["tax"]) > 0.01:
        problems.append("sums_dont_add")
    currency = invoice["currency"]
    rate = fx.get(currency)
    if rate is None or rate <= 0:
        problems.append(f"missing_fx:{currency}")
        rate = 1.0
    po_total = doc.get("po_total")
    if po in ("priced", "component") and po_total is not None:
        if abs(total - float(po_total)) > max(50.0, 0.02 * total):
            problems.append("po_variance")
    return {"problems": problems, "rate": rate}


def _append_ledger(ledger: list[dict], invoice: dict) -> list[dict]:
    return [*ledger, invoice]


def _po_blast(po: str) -> float:
    return 0.7 if po in ("extra", "not_ours") else 0.1


@j.s2
def extract(text: str) -> dict:
    """Extract invoice fields verbatim. Return JSON with inv_no, date, due, currency,
    total, tax, subtotal, lines, and bank. Do not calculate missing values.
    """


@j.s2
def repair(invoice: dict, po_status: str, flags: object) -> str:
    """Propose short-pay lines, a dispute reason, and a corrected request with citations."""


AP = (
    j.input(doc=j.x, ledger=[], fx={})
    | j.keep(text=j.x.doc.text[:4000], problems=[])
    | j.keep(
        triage=TRIAGE.on(
            {"document": j.x.doc, "source_text": j.x.text[:2000], "ledger": j.x.ledger}
        )
    )
    | j.case[
        j.x.triage.fraud >= 0.70: j.stop("FRAUD_REVIEW", problems=j.x.problems),
        j.x.triage.doc_type.choice != "invoice": j.stop("HOLD", problems=j.x.problems),
        j.x.triage.already_paid >= 0.70: j.stop("DUPLICATE_REVIEW", problems=j.x.problems),
        j.x.triage.wrong_vendor >= 0.65: j.stop("REJECT", problems=j.x.problems),
        ...: j.pass_,
    ]
    | j.keep(invoice=extract(j.x.text))
    | j.require(j.x.invoice, *REQUIRED, else_=j.stop("HOLD_FOR_DOCS", problems=j.x.problems))
    | j.when(
        j.compute(_duplicate, j.x.doc, j.x.ledger, j.x.invoice),
        j.stop("DUPLICATE_REVIEW", problems=j.x.problems),
    )
    | j.keep(
        fields=FIELD_CHECK.on({"source_text": j.x.text[:2000], "extracted": j.x.invoice})
    )
    | j.when(
        j.max(
            j.x.fields.hallucinated,
            j.x.fields.off_target,
            j.x.fields.unreasonable,
            j.x.fields.absence_wrong,
        )
        >= 0.70,
        j.stop(
            "REQUEST_CORRECTED",
            proposal=repair(j.x.invoice, j.x.triage.po_status.choice, j.x.fields),
            problems=j.x.problems,
        ),
    )
    | j.keep(
        validation=j.compute(
            _validate_numbers,
            j.x.invoice,
            j.x.doc,
            j.x.fx,
            j.x.triage.po_status.choice,
        )
    )
    | j.keep(
        release=RELEASE.on(
            {"invoice": j.x.invoice, "po_status": j.x.triage.po_status.choice}
        ),
        blast=j.compute(
            blast_of,
            j.min(j.x.invoice.total * j.x.validation.rate / 10_000, 1.0),
            j.compute(_po_blast, j.x.triage.po_status.choice),
        ),
    )
    | j.keep(
        confidence=1 - j.max(j.x.release.over_cap, j.x.release.withholds),
        ledger_after=j.compute(_append_ledger, j.x.ledger, j.x.invoice),
    )
    | j.keep(risk=j.compute(risk, j.x.blast, j.x.confidence))
    | j.keep(verdict=j.compute(verdict, j.x.risk, review_at=1.5, refuse_at=4.0))
    | j.case[
        (j.x.release.withholds >= 0.60) | (j.x.verdict == "refuse"):
            j.stop("HOLD", risk=j.x.verdict, problems=j.x.validation.problems),
        ((j.x.verdict == "review") | (j.x.release.over_cap >= 0.65))
        & (j.x.triage.po_status.choice == "not_ours"):
            j.stop("PROCUREMENT_REVIEW", problems=j.x.validation.problems),
        (j.x.verdict == "review") | (j.x.release.over_cap >= 0.65):
            j.stop("SHORT_PAY", problems=j.x.validation.problems),
        ...: j.stop(
            "RELEASED",
            inv_no=j.x.invoice.inv_no,
            ledger=j.x.ledger_after,
            problems=j.x.validation.problems,
        ),
    ]
)


def process(doc: dict, ledger: list[dict], fx: dict, backend: Backend | None = None) -> dict:
    """Run the inert AP graph with a live or scripted backend."""
    return AP.run(doc=doc, ledger=ledger, fx=fx, backend=backend or Live())
