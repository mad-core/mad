"""HTTP integration tests for session timestamp surface (issue #17).

Covers:
  - GET /v1/sessions and /v1/sessions/{id} expose ISO-8601 ``created_at``
    and ``updated_at`` in the response body.
  - GET /v1/sessions accepts ``created_after``, ``created_before``,
    ``updated_after``, ``updated_before``, ``order_by``, ``order``.
  - Negative twins: invalid date format → 422; out-of-range filter →
    empty list (200, not 4xx).
  - OpenAPI declares the new query params and response shape (rule 5).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient


def _create(client: TestClient, session_payload: dict) -> str:
    return client.post("/v1/sessions", json=session_payload).json()["session_id"]


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Response shape — happy path
# ---------------------------------------------------------------------------


def test_get_session_returns_iso8601_timestamps(client: TestClient, session_payload: dict) -> None:
    """GET /v1/sessions/{id} surfaces created_at and updated_at as parseable
    ISO-8601 strings; updated_at >= created_at on a freshly created session.
    """
    session_id = _create(client, session_payload)

    r = client.get(f"/v1/sessions/{session_id}")
    assert r.status_code == 200
    body = r.json()
    created = _parse_iso(body["created_at"])
    updated = _parse_iso(body["updated_at"])
    assert created.tzinfo is not None
    assert updated >= created


def test_list_sessions_returns_iso8601_timestamps(
    client: TestClient, session_payload: dict
) -> None:
    """GET /v1/sessions surfaces both timestamps for each entry."""
    session_id = _create(client, session_payload)

    r = client.get("/v1/sessions")
    assert r.status_code == 200
    body = r.json()
    matching = [s for s in body if s["session_id"] == session_id]
    assert len(matching) == 1
    entry = matching[0]
    created = _parse_iso(entry["created_at"])
    updated = _parse_iso(entry["updated_at"])
    assert created.tzinfo is not None
    assert updated >= created


def test_updated_at_advances_after_message(
    client: TestClient, fake_launcher, session_payload: dict
) -> None:
    """Sending a message bumps ``updated_at`` past the original create time —
    that's the property clients rely on to filter "recently active" sessions.
    """
    fake_launcher.script([[{"type": "session.status_idle", "stop_reason": "end_turn"}]])
    session_id = _create(client, session_payload)
    initial = _parse_iso(client.get(f"/v1/sessions/{session_id}").json()["updated_at"])

    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "go"})

    # The /messages handler emits user.message synchronously through the
    # emitter, which calls touch_session() — so by the time the response
    # returns, updated_at must already have advanced.
    after = _parse_iso(client.get(f"/v1/sessions/{session_id}").json()["updated_at"])
    assert after > initial


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_list_sessions_filter_out_of_range_returns_empty(
    client: TestClient, session_payload: dict
) -> None:
    """A ``created_after`` in the future returns 200 with an empty list — no
    sessions match, but the request itself is well-formed.
    """
    _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={"created_after": "2099-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_filter_includes_recent_session(
    client: TestClient, session_payload: dict
) -> None:
    """A ``created_after`` set to a past instant still includes the session
    just created (positive twin to the empty-result test)."""
    session_id = _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={"created_after": "2000-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 200
    ids = [s["session_id"] for s in r.json()]
    assert session_id in ids


def test_list_sessions_order_by_created_at_desc_puts_newest_first(
    client: TestClient, session_payload: dict
) -> None:
    """``order_by=created_at&order=desc`` returns sessions newest-first."""
    sid_1 = _create(client, session_payload)
    sid_2 = _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={"order_by": "created_at", "order": "desc"},
    )
    assert r.status_code == 200
    body = r.json()
    timestamps = [_parse_iso(s["created_at"]) for s in body]
    assert timestamps == sorted(timestamps, reverse=True), (
        f"expected non-increasing timestamps, got {timestamps}"
    )
    ids = [s["session_id"] for s in body]
    # Both created sessions appear in the listing.
    assert sid_1 in ids and sid_2 in ids


# ---------------------------------------------------------------------------
# Negative twins (rule 1)
# ---------------------------------------------------------------------------


def test_list_sessions_rejects_invalid_date_format(
    client: TestClient,
) -> None:
    """A non-ISO date in ``created_after`` returns 422 with a structured
    detail — clients can render the field name and the parser error.
    """
    r = client.get("/v1/sessions", params={"created_after": "not-a-date"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and len(detail) >= 1
    locs = [tuple(item.get("loc", [])) for item in detail]
    assert any("created_after" in loc for loc in locs), (
        f"422 detail must reference created_after; got {locs}"
    )


def test_list_sessions_rejects_invalid_order_by(
    client: TestClient,
) -> None:
    """``order_by=garbage`` is rejected with 422 — the contract enumerates
    only ``created_at`` and ``updated_at``."""
    r = client.get("/v1/sessions", params={"order_by": "garbage"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    locs = [tuple(item.get("loc", [])) for item in detail]
    assert any("order_by" in loc for loc in locs)


def test_list_sessions_rejects_invalid_order(
    client: TestClient,
) -> None:
    """``order`` only accepts ``asc`` and ``desc`` — anything else is 422."""
    r = client.get("/v1/sessions", params={"order": "sideways"})
    assert r.status_code == 422
    locs = [tuple(item.get("loc", [])) for item in r.json()["detail"]]
    assert any("order" in loc for loc in locs)


# ---------------------------------------------------------------------------
# Aggressive datetime parsing — naive datetime + date-only must NOT 500
# (regression: comparing offset-naive against the tz-aware Session
#  timestamp raised TypeError → 500 in production)
# ---------------------------------------------------------------------------


def test_list_sessions_accepts_date_only_filter_without_500(
    client: TestClient, session_payload: dict
) -> None:
    """``created_after=2026-05-01`` (date with no time, no tz) must be
    interpreted as UTC midnight and compared safely. Returning 500 because
    of naive vs aware datetime arithmetic is the exact bug this guards.
    """
    session_id = _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={
            "created_after": "2000-01-01",
            "order_by": "created_at",
            "order": "desc",
        },
    )
    assert r.status_code == 200, r.text
    ids = [s["session_id"] for s in r.json()]
    assert session_id in ids


def test_list_sessions_accepts_naive_datetime_filter_without_500(
    client: TestClient, session_payload: dict
) -> None:
    """``2026-05-01T00:00:00`` (naive datetime) must be interpreted as UTC
    rather than crashing the comparison."""
    session_id = _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={"created_after": "2000-01-01T00:00:00"},
    )
    assert r.status_code == 200, r.text
    ids = [s["session_id"] for s in r.json()]
    assert session_id in ids


def test_list_sessions_naive_future_datetime_returns_empty(
    client: TestClient, session_payload: dict
) -> None:
    """Naive future datetime is normalized to UTC and excludes a session
    that was just created — confirms the normalization, not just that the
    comparison didn't crash."""
    _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={"created_after": "2099-01-01T00:00:00"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_partial_date_returns_422(
    client: TestClient,
) -> None:
    """A truncated date like ``2026-05`` is NOT a valid ISO-8601 date or
    datetime — FastAPI must reject with 422, not pass through to the use
    case where it would fail unpredictably."""
    r = client.get("/v1/sessions", params={"created_after": "2026-05"})
    assert r.status_code == 422
    locs = [tuple(item.get("loc", [])) for item in r.json()["detail"]]
    assert any("created_after" in loc for loc in locs)


def test_list_sessions_combined_filters_and_ordering_no_500(
    client: TestClient, session_payload: dict
) -> None:
    """Combine every query param in one request — the exact shape that
    triggered the 500 in production. Must return 200 with a sorted list."""
    sid_a = _create(client, session_payload)
    sid_b = _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={
            "created_after": "2000-01-01",
            "created_before": "2099-01-01T00:00:00+00:00",
            "updated_after": "2000-01-01T00:00:00",
            "updated_before": "2099-12-31",
            "order_by": "created_at",
            "order": "desc",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    timestamps = [_parse_iso(s["created_at"]) for s in body]
    assert timestamps == sorted(timestamps, reverse=True)
    ids = [s["session_id"] for s in body]
    assert sid_a in ids and sid_b in ids


def test_list_sessions_rejects_garbage_datetime_with_loc(
    client: TestClient,
) -> None:
    """A purely non-ISO string in any of the four datetime params returns
    422 with a ``loc`` that names the offending field — not 500."""
    for field in (
        "created_after",
        "created_before",
        "updated_after",
        "updated_before",
    ):
        r = client.get("/v1/sessions", params={field: "not-a-date"})
        assert r.status_code == 422, f"{field} did not 422: {r.text}"
        locs = [tuple(item.get("loc", [])) for item in r.json()["detail"]]
        assert any(field in loc for loc in locs), (
            f"{field} 422 did not reference itself in loc; got {locs}"
        )


def test_list_sessions_inverted_window_returns_empty_not_500(
    client: TestClient, session_payload: dict
) -> None:
    """An inverted window (``created_after`` after ``created_before``)
    returns 200 with an empty list — the contract is "filter, don't crash".
    """
    _create(client, session_payload)

    r = client.get(
        "/v1/sessions",
        params={
            "created_after": "2099-01-01",
            "created_before": "2000-01-01",
        },
    )
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# OpenAPI contract (rule 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "param",
    [
        "created_after",
        "created_before",
        "updated_after",
        "updated_before",
        "order_by",
        "order",
    ],
)
def test_openapi_declares_list_filter_params(client: TestClient, param: str) -> None:
    """Every documented filter must appear as a query param on
    ``GET /v1/sessions`` so it is visible in /docs and Postman."""
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/sessions"]["get"]
    names = {p["name"]: p for p in op.get("parameters", [])}
    assert param in names, (
        f"OpenAPI does not declare ?{param} on GET /v1/sessions; declared: {sorted(names)}"
    )
    assert names[param]["in"] == "query"


def test_openapi_get_session_response_includes_timestamps(
    client: TestClient,
) -> None:
    """The response model for GET /v1/sessions/{id} must list created_at
    and updated_at — the /docs page is the contract for clients."""
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/sessions/{session_id}"]["get"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]
    ref = schema_ref["$ref"].rsplit("/", 1)[-1]
    component = spec["components"]["schemas"][ref]
    assert "created_at" in component["properties"]
    assert "updated_at" in component["properties"]
    assert "created_at" in component["required"]
    assert "updated_at" in component["required"]


def test_openapi_list_sessions_item_schema_includes_timestamps(
    client: TestClient,
) -> None:
    """The list response items must declare both timestamps."""
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/v1/sessions"]["get"]
    items = op["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    ref = items["$ref"].rsplit("/", 1)[-1]
    component = spec["components"]["schemas"][ref]
    assert "created_at" in component["properties"]
    assert "updated_at" in component["properties"]
