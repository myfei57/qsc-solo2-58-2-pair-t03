"""Immutable rule-set snapshot endpoints."""

from __future__ import annotations

from maskhub.console.http import Request, Response


def list_snapshots(runtime, request: Request) -> Response:
    snapshots = [
        {"identifier": item.identifier, "created_at": item.created_at, "rule_count": len(item.rules)}
        for item in runtime.snapshots.all()
    ]
    return Response.json(200, {"count": len(snapshots), "snapshots": snapshots})


def get_snapshot(runtime, request: Request) -> Response:
    identifier = request.query_one("snapshot", "") or ""
    return Response.json(200, runtime.snapshots.get(identifier).as_dict())
