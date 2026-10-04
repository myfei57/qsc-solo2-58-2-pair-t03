"""Masking rule endpoints."""

from __future__ import annotations

from maskhub.console.http import Request, Response
from maskhub.console.validation import optional_text, require_bool, require_int, require_text
from maskhub.errors import InvalidRequest
from maskhub.rule.adjudication import adjudicate
from maskhub.rule.rule import DEFAULT_PRIORITY, Rule


def _rule_payload(payload) -> Rule:
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        raise InvalidRequest("parameters must be an object")
    return Rule(
        identifier=require_text(payload, "identifier"),
        field_pattern=require_text(payload, "field_pattern"),
        action=require_text(payload, "action"),
        parameters=parameters,
        priority=require_int(payload, "priority", DEFAULT_PRIORITY),
        enabled=require_bool(payload, "enabled", True),
    )


def list_rules(runtime, request: Request) -> Response:
    rules = [rule.as_dict() for rule in runtime.rules.all()]
    return Response.json(200, {"count": len(rules), "rules": rules})


def create_rule(runtime, request: Request) -> Response:
    rule = _rule_payload(request.json_object())
    runtime.rules.add(rule)
    runtime.journal.append("rule.create", rule.identifier, rule.action)
    return Response.json(200, rule.as_dict())


def update_rule(runtime, request: Request) -> Response:
    payload = request.json_object()
    identifier = require_text(payload, "identifier")
    existing = runtime.rules.get(identifier)
    rule = _rule_payload(payload)
    if rule.identifier != existing.identifier:
        raise InvalidRequest("rule identifier cannot be changed")
    runtime.rules.save(rule)
    runtime.journal.append("rule.update", rule.identifier, f"priority={rule.priority}")
    return Response.json(200, rule.as_dict())


def set_rule_status(runtime, request: Request) -> Response:
    payload = request.json_object()
    identifier = require_text(payload, "identifier")
    if "enabled" not in payload:
        raise InvalidRequest("enabled is required")
    enabled = require_bool(payload, "enabled", False)
    rule = runtime.rules.set_enabled(identifier, enabled)
    runtime.journal.append(
        "rule.enable" if enabled else "rule.disable",
        identifier,
        optional_text(payload, "reason"),
    )
    return Response.json(200, rule.as_dict())


def remove_rule(runtime, request: Request) -> Response:
    payload = request.json_object()
    identifier = require_text(payload, "identifier")
    runtime.rules.remove(identifier)
    runtime.journal.append("rule.remove", identifier, optional_text(payload, "reason"))
    return Response.json(200, {"removed": identifier})


def _fields(payload) -> list[str]:
    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise InvalidRequest("fields must be a non-empty list")
    names: list[str] = []
    for item in fields:
        if isinstance(item, str):
            if not item.strip():
                raise InvalidRequest("fields entries must be non-empty strings")
            names.append(item.strip())
        elif isinstance(item, dict):
            names.append(require_text(item, "name"))
        else:
            raise InvalidRequest("fields entries must be strings or objects with a name")
    return names


def _resolve_rules(runtime, payload):
    snapshot_id = payload.get("snapshot_id")
    policy_id = payload.get("policy_id")
    if snapshot_id is not None and policy_id is not None:
        raise InvalidRequest("snapshot_id and policy_id cannot both be provided")
    if snapshot_id is not None:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise InvalidRequest("snapshot_id must be a non-empty string")
        snapshot = runtime.snapshots.get(snapshot_id.strip())
        return list(snapshot.rules), snapshot.identifier
    if policy_id is not None:
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise InvalidRequest("policy_id must be a non-empty string")
        policy = runtime.policies.get(policy_id.strip())
        if not policy.snapshot_id:
            raise InvalidRequest(f"policy {policy.identifier} has no immutable snapshot")
        snapshot = runtime.snapshots.get(policy.snapshot_id)
        return [snapshot.rule(rule_id) for rule_id in policy.rules], snapshot.identifier
    return runtime.rules.all(), None


def match_rule(runtime, request: Request) -> Response:
    payload = request.json_object()
    names = _fields(payload)
    rules, snapshot_id = _resolve_rules(runtime, payload)
    decisions = {name: adjudicate(name, rules) for name in names}
    return Response.json(
        200,
        {
            "snapshot_id": snapshot_id,
            "matches": {name: decision.as_dict() for name, decision in decisions.items()},
        },
    )
