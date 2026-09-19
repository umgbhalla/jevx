from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.relational import Table


def test_table_batches_rows_with_identity_and_reuses_judgments():
    rows = [{"id": "a", "active": True}, {"id": "b", "active": False}]
    question = {"question": "Is this record active?", "field": "active"}
    driver = TraceDriver(
        ScriptDriver(
            {
                "r0": [{"type": "noul", "noul": 0.95}],
                "r1": [{"type": "noul", "noul": 0.1}],
            }
        )
    )
    table = Table(rows, context={"goal": "select active records"})

    with use(driver):
        scores = table.noul(question)
        selected = table.where(question, threshold=0.5)

    assert [float(score) for score in scores] == [0.95, 0.1]
    assert selected == [rows[0]]
    assert table.stats == {"requests": 1, "judged": 2, "cache_hits": 4}
    assert len(driver.trace) == 1
    payload = driver.trace[0]
    assert payload["state"]["context"] == {"goal": "select active records"}
    assert payload["questions"]["r0"]["instructions"]["record"] == rows[0]
    assert payload["questions"]["r1"]["instructions"]["record"] == rows[1]


def test_table_score_and_choice_embed_their_own_rows():
    rows = [{"id": "a", "kind": "charge"}, {"id": "b", "kind": "crash"}]
    driver = TraceDriver(
        ScriptDriver(
            {
                "r0": [
                    {
                        "type": "score",
                        "score": 0,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 1.0, "1": 0.0},
                        "confidence": 1.0,
                    },
                    {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"billing": 1.0, "bug": 0.0},
                        "confidence": 1.0,
                    },
                ],
                "r1": [
                    {
                        "type": "score",
                        "score": 1,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 0.0, "1": 1.0},
                        "confidence": 1.0,
                    },
                    {
                        "type": "choice",
                        "choice": "bug",
                        "probabilities": {"billing": 0.0, "bug": 1.0},
                        "confidence": 1.0,
                    },
                ],
            }
        )
    )
    table = Table(rows)

    with use(driver):
        ranked = table.order_by("severity", ("low", "high"))
        groups = table.group_by("team", {"billing": "charges", "bug": "crashes"})

    assert [row["id"] for row in ranked] == ["b", "a"]
    assert groups == {"billing": [rows[0]], "bug": [rows[1]]}
    assert len(driver.trace) == 2
    assert driver.trace[0]["questions"]["r1"]["instructions"]["record"] == rows[1]
    assert driver.trace[1]["questions"]["r0"]["instructions"]["record"] == rows[0]


def test_table_splits_more_than_twenty_rows_without_losing_alignment():
    rows = [{"id": index} for index in range(21)]
    script = {
        f"r{index}": [{"type": "noul", "noul": 0.1}]
        for index in range(20)
    }
    script["r0"].append({"type": "noul", "noul": 0.9})
    driver = TraceDriver(ScriptDriver(script))
    table = Table(rows)

    with use(driver):
        scores = table.noul("Is this row selected?")

    assert len(scores) == 21
    assert float(scores[-1]) == 0.9
    assert table.stats["requests"] == 2
    assert len(driver.trace) == 2
    assert driver.trace[1]["questions"]["r0"]["instructions"]["record"] == rows[-1]


def test_table_context_changes_invalidate_cached_answers():
    driver = TraceDriver(
        ScriptDriver(
            {"r0": [{"type": "noul", "noul": 0.9}, {"type": "noul", "noul": 0.1}]}
        )
    )
    table = Table([{"id": "same row"}], context={"goal": "first"})

    with use(driver):
        first = table.noul("Does this row help?")
        table.context = {"goal": "second"}
        second = table.noul("Does this row help?")

    assert float(first[0]) == 0.9
    assert float(second[0]) == 0.1
    assert table.stats["requests"] == 2
    assert driver.trace[0]["state"]["context"] != driver.trace[1]["state"]["context"]
