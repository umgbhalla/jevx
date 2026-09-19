"""Jev quickstart: raw HTTP + SDK. Needs TYPESAFE_API_KEY."""
import json
import os
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
KEY = os.environ.get("TYPESAFE_API_KEY", "")

BODY = {
    "state": "The deploy failed twice and customers are seeing 500s. Can someone look now?",
    "model": "jev-latest",
    "questions": {
        "is_urgent": {
            "type": "noul",
            "instructions": "Does this need attention right now?",
        },
        "team": {
            "type": "choice",
            "instructions": "Which team should pick this up?",
            "criteria": {
                "infra": "Deploys, availability, and on-call incidents.",
                "billing": "Payments, invoices, and subscriptions.",
            },
        },
        "severity": {
            "type": "score",
            "instructions": "How severe is the impact?",
            "criteria": ["Cosmetic.", "Degraded for some users.", "Full outage."],
        },
    },
}


def raw():
    req = urllib.request.Request(
        API,
        data=json.dumps(BODY).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.dumps(json.loads(r.read()), indent=2))


def via_sdk():
    from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

    client = TypeSafeClient()
    resp = client.system_one(
        state=BODY["state"],
        questions={
            "is_urgent": Noul(instructions="Does this need attention right now?"),
            "team": Choice(
                instructions="Which team should pick this up?",
                criteria={
                    "infra": "Deploys, availability, and on-call incidents.",
                    "billing": "Payments, invoices, and subscriptions.",
                },
            ),
            "severity": Score(
                instructions="How severe is the impact?",
                criteria=["Cosmetic.", "Degraded for some users.", "Full outage."],
            ),
        },
    )
    print(resp.answers["is_urgent"].noul)
    print(resp.answers["team"].choice, resp.answers["team"].confidence)
    print(resp.answers["severity"].score)


if __name__ == "__main__":
    (via_sdk if os.environ.get("USE_SDK") else raw)()
