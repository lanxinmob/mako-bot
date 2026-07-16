from pathlib import Path

from src.services.search_metrics import SearchMetrics


def test_search_metrics_tracks_quality_latency_calls_and_cost() -> None:
    metrics = SearchMetrics()
    metrics.record_routing(expected_search=True, routed_to_search=True)
    metrics.record_routing(expected_search=True, routed_to_search=False)
    metrics.record_pipeline(
        attempted=True,
        evidence_success=True,
        correction_mode=True,
        correction_recovered=True,
        provider_unavailable=False,
        fail_closed=False,
        search_calls=3,
        page_fetches=5,
        estimated_cost=0.03,
        latency_ms=100,
    )
    metrics.record_pipeline(
        attempted=True,
        evidence_success=False,
        correction_mode=False,
        correction_recovered=False,
        provider_unavailable=True,
        fail_closed=True,
        search_calls=1,
        page_fetches=0,
        estimated_cost=0.01,
        latency_ms=900,
    )
    metrics.record_answer(
        factual_mode=True, realtime=True, cited=True, consistent=True
    )

    snapshot = metrics.snapshot()
    assert snapshot["search_routing_recall"] == 0.5
    assert snapshot["evidence_retrieval_success_rate"] == 0.5
    assert snapshot["answer_evidence_consistency_rate"] == 1.0
    assert snapshot["realtime_citation_coverage"] == 1.0
    assert snapshot["unavailable_fail_closed_rate"] == 1.0
    assert snapshot["correction_recovery_rate"] == 1.0
    assert snapshot["search_latency_p50_ms"] == 100
    assert snapshot["search_latency_p95_ms"] == 900
    assert snapshot["search_calls"] == 4
    assert snapshot["page_fetches"] == 5
    assert snapshot["estimated_search_cost"] == 0.04


def test_search_eval_corpus_covers_required_categories() -> None:
    corpus = (Path(__file__).parents[1] / "eval" / "search_cases.yaml").read_text(
        encoding="utf-8"
    )
    categories = {
        "explicit_search",
        "implicit_freshness",
        "sports_result",
        "today_yesterday_timezone",
        "ambiguous_entity",
        "conflicting_sources",
        "no_results",
        "provider_unavailable",
        "user_correction",
        "stale_page",
        "preview_vs_result",
    }
    for category in categories:
        assert f"category: {category}" in corpus
