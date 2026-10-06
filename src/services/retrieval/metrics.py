from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: Deque[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


@dataclass
class SearchMetrics:
    """In-process search quality and cost counters.

    Runtime counters cover production outcomes. Evaluation code can call
    ``record_routing`` with labelled cases to measure routing recall.
    """

    routing_expected: int = 0
    routing_true_positive: int = 0
    evidence_attempts: int = 0
    evidence_successes: int = 0
    factual_answers: int = 0
    consistent_answers: int = 0
    realtime_answers: int = 0
    cited_realtime_answers: int = 0
    unavailable_cases: int = 0
    unavailable_fail_closed: int = 0
    correction_cases: int = 0
    correction_recoveries: int = 0
    search_calls: int = 0
    page_fetches: int = 0
    estimated_search_cost: float = 0.0
    latencies_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_routing(self, *, expected_search: bool, routed_to_search: bool) -> None:
        if not expected_search:
            return
        with self._lock:
            self.routing_expected += 1
            self.routing_true_positive += int(routed_to_search)

    def record_pipeline(
        self,
        *,
        attempted: bool,
        evidence_success: bool,
        correction_mode: bool,
        correction_recovered: bool,
        provider_unavailable: bool,
        fail_closed: bool,
        search_calls: int,
        page_fetches: int,
        estimated_cost: float,
        latency_ms: float,
    ) -> None:
        with self._lock:
            if attempted:
                self.evidence_attempts += 1
                self.evidence_successes += int(evidence_success)
                self.latencies_ms.append(max(0.0, latency_ms))
            self.search_calls += max(0, search_calls)
            self.page_fetches += max(0, page_fetches)
            self.estimated_search_cost += max(0.0, estimated_cost)
            if provider_unavailable:
                self.unavailable_cases += 1
                self.unavailable_fail_closed += int(fail_closed)
            if correction_mode:
                self.correction_cases += 1
                self.correction_recoveries += int(correction_recovered)

    def record_answer(
        self,
        *,
        factual_mode: bool,
        realtime: bool,
        cited: bool,
        consistent: bool,
    ) -> None:
        with self._lock:
            if factual_mode:
                self.factual_answers += 1
                self.consistent_answers += int(consistent)
            if realtime:
                self.realtime_answers += 1
                self.cited_realtime_answers += int(cited)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "search_routing_recall": _ratio(
                    self.routing_true_positive, self.routing_expected
                ),
                "evidence_retrieval_success_rate": _ratio(
                    self.evidence_successes, self.evidence_attempts
                ),
                "answer_evidence_consistency_rate": _ratio(
                    self.consistent_answers, self.factual_answers
                ),
                "realtime_citation_coverage": _ratio(
                    self.cited_realtime_answers, self.realtime_answers
                ),
                "unavailable_fail_closed_rate": _ratio(
                    self.unavailable_fail_closed, self.unavailable_cases
                ),
                "correction_recovery_rate": _ratio(
                    self.correction_recoveries, self.correction_cases
                ),
                "search_latency_p50_ms": _percentile(self.latencies_ms, 0.50),
                "search_latency_p95_ms": _percentile(self.latencies_ms, 0.95),
                "search_calls": self.search_calls,
                "page_fetches": self.page_fetches,
                "estimated_search_cost": round(self.estimated_search_cost, 6),
            }

    def reset(self) -> None:
        with self._lock:
            for name in (
                "routing_expected",
                "routing_true_positive",
                "evidence_attempts",
                "evidence_successes",
                "factual_answers",
                "consistent_answers",
                "realtime_answers",
                "cited_realtime_answers",
                "unavailable_cases",
                "unavailable_fail_closed",
                "correction_cases",
                "correction_recoveries",
                "search_calls",
                "page_fetches",
            ):
                setattr(self, name, 0)
            self.estimated_search_cost = 0.0
            self.latencies_ms.clear()


search_metrics = SearchMetrics()
