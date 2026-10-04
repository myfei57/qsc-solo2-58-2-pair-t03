"""Immutable rule snapshot endpoints."""

from __future__ import annotations

from maskhub.console.http import Request, Response
from maskhub.console.validation import require_text
from maskhub.errors import InvalidRequest
from maskhub.rule.adjudication import adjudicate_all


def list_snapshots(runtime, request: Request) -> Response:
    snapshots = [snapshot.summary() for snapshot in runtime.snapshots.all()]
    return Response.json(200, {"count": len(snapshots), "snapshots": snapshots})


def get_snapshot(runtime, request: Request) -> Response:
    identifier = request.query_one("snapshot", "") or ""
    return Response.json(200, runtime.snapshots.get(identifier).as_dict())


def explain_snapshot(runtime, request: Request) -> Response:
    """Replay adjudication against a frozen snapshot.

    This is how a past result is explained: the snapshot holds the exact
    rule set that was in effect, and adjudication is deterministic, so the
    replayed decisions and reasons are the ones that applied at the time.
    """

    payload = request.json_object()
    snapshot = runtime.snapshots.get(require_text(payload, "snapshot"))
    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise InvalidRequest("fields must be a non-empty list")
    names = [require_text({"name": item}, "name") for item in fields]
    decisions = adjudicate_all(names, snapshot.rules)
    return Response.json(
        200,
        {
            "snapshot": snapshot.identifier,
            "policy": snapshot.policy,
            "created_at": snapshot.created_at,
            "decisions": [decision.as_dict() for decision in decisions],
        },
    )
