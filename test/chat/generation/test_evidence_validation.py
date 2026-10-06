"""Review and automated consumption reject the same damaged attempt evidence."""
import json

import pytest

from src.services.persistence.generation.models import GenerationSpec, decode_attempt
from src.services.persistence.generation.costs import decode_cost


def evidence():
    spec = GenerationSpec("a" * 64, 7, "reply", "test", "b" * 64, "20260928", 1, 2, .01)
    return spec, {"schema_version": 1, "spec_json": spec.encode(), "token": "c" * 64,
                  "started_at_ms": 1, "state": "completed", "cost_state": "pending", "amount_json": "0.01"}


@pytest.mark.parametrize("field,value", [
    ("started_at_ms", 0), ("started_at_ms", True), ("started_at_ms", 2**53),
    ("started_at_ms", "123"), ("token", ""), ("schema_version", True), ("state", "future_state"),
])
def test_bad_identity_and_time_rejected_by_both_paths(field, value):
    spec, item = evidence()
    item[field] = value
    raw = json.dumps(item)
    for decode in (decode_attempt, decode_cost):
        with pytest.raises(ValueError):
            decode(raw, spec.attempt_id)


@pytest.mark.parametrize("state,cost_state", [("calling", "not_ready"), ("unknown", "needs_review")])
def test_unresolved_attempt_cannot_smuggle_frozen_amount(state, cost_state):
    spec, item = evidence()
    item.update(state=state, cost_state=cost_state)
    raw = json.dumps(item)
    with pytest.raises(ValueError):
        decode_cost(raw, spec.attempt_id)
    item.pop("amount_json")
    assert decode_cost(json.dumps(item), spec.attempt_id) is None
