"""Snapshot immutability and end-to-end adjudication flow through the router."""

from __future__ import annotations

import json
import tempfile
import unittest

from maskhub.console.errors import error_response
from maskhub.console.http import Request
from maskhub.console.routes import build_router
from maskhub.console.runtime import build_runtime
from maskhub.errors import NotFound
from maskhub.policy.policy import Policy
from maskhub.rule.adjudication import adjudicate
from maskhub.rule.rule import Rule
from maskhub.rule.snapshot import SnapshotRegistry
from maskhub.store.kvstore import RecordStore


def make_rule(identifier: str, pattern: str, priority: int = 0, action: str = "hash") -> Rule:
    return Rule(
        identifier=identifier,
        field_pattern=pattern,
        action=action,
        parameters={},
        priority=priority,
    )


def make_policy(identifier: str = "p1", rules: tuple[str, ...] = ("r1",)) -> Policy:
    return Policy(identifier=identifier, datasets=("ds1",), rules=rules)


class SnapshotRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecordStore(self._tmp.name)
        self.store.load()
        self.snapshots = SnapshotRegistry(self.store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_capture_freezes_full_rule_definitions(self) -> None:
        rules = [make_rule("r2", "*", action="redact"), make_rule("r1", "email_*")]
        snapshot = self.snapshots.capture(make_policy(rules=("r1", "r2")), rules)
        self.assertTrue(snapshot.identifier.startswith("snap-"))
        self.assertEqual(snapshot.policy, "p1")
        self.assertEqual([rule.identifier for rule in snapshot.rules], ["r1", "r2"])
        self.assertEqual(snapshot.rules[1].action, "redact")

    def test_capture_is_idempotent_for_identical_content(self) -> None:
        policy = make_policy()
        first = self.snapshots.capture(policy, [make_rule("r1", "email_*")])
        second = self.snapshots.capture(policy, [make_rule("r1", "email_*")])
        self.assertEqual(first.identifier, second.identifier)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(len(self.snapshots.all()), 1)

    def test_different_content_yields_a_different_snapshot(self) -> None:
        policy = make_policy()
        first = self.snapshots.capture(policy, [make_rule("r1", "email_*")])
        second = self.snapshots.capture(policy, [make_rule("r1", "email_*", priority=5)])
        self.assertNotEqual(first.identifier, second.identifier)
        self.assertEqual(len(self.snapshots.all()), 2)

    def test_snapshot_round_trips_through_storage(self) -> None:
        snapshot = self.snapshots.capture(
            make_policy(), [make_rule("r1", "email_*", priority=3, action="tokenize")]
        )
        loaded = self.snapshots.get(snapshot.identifier)
        self.assertEqual(loaded, snapshot)
        self.assertEqual(loaded.rules[0].priority, 3)
        self.assertEqual(loaded.rules[0].action, "tokenize")

    def test_unknown_snapshot_raises_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.snapshots.get("snap-missing")

    def test_registry_exposes_no_mutation_beyond_capture(self) -> None:
        for verb in ("delete", "remove", "update", "save", "put"):
            self.assertFalse(hasattr(self.snapshots, verb), verb)


class ConsoleFlowTest(unittest.TestCase):
    """Drive the HTTP router the way the console would."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecordStore(self._tmp.name)
        self.store.load()
        self.runtime = build_runtime(self.store)
        self.router = build_router(self.runtime)
        self.call("POST", "/sources", {"identifier": "src1", "kind": "db", "endpoint": "db:1"})
        self.call(
            "POST",
            "/datasets",
            {
                "identifier": "ds1",
                "source": "src1",
                "owner": "team-a",
                "fields": [
                    {"name": "email_address", "sensitivity": "personal"},
                    {"name": "full_name", "sensitivity": "personal"},
                    {"name": "nickname", "sensitivity": "public"},
                ],
            },
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def call(self, method: str, path: str, payload: dict | None = None, query: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else b""
        params = {
            name: (value if isinstance(value, list) else [value])
            for name, value in (query or {}).items()
        }
        request = Request(
            method=method,
            path=path,
            query=params,
            headers={},
            body=body,
        )
        try:
            response = self.router.dispatch(request)
        except Exception as exc:  # mirrors the server's error boundary
            response = error_response(exc)
        decoded = json.loads(response.payload) if response.payload else {}
        return response.status, decoded

    def create_rule(self, identifier: str, pattern: str, priority: int = 0, action: str = "hash"):
        status, payload = self.call(
            "POST",
            "/rules",
            {
                "identifier": identifier,
                "field_pattern": pattern,
                "action": action,
                "priority": priority,
            },
        )
        self.assertEqual(status, 200, payload)
        return payload

    def activate(self, policy: str = "p1"):
        status, payload = self.call("POST", "/policy/activate", {"identifier": policy})
        self.assertEqual(status, 200, payload)
        return payload

    def create_policy(self, rules: list[str], policy: str = "p1"):
        status, payload = self.call(
            "POST",
            "/policies",
            {"identifier": policy, "datasets": ["ds1"], "rules": rules},
        )
        self.assertEqual(status, 200, payload)
        return payload

    def test_resolve_explains_winner_and_losers(self) -> None:
        self.create_rule("catchall", "*", action="redact")
        self.create_rule("email-exact", "email_address", action="hash")
        self.create_rule("email-glob", "email_*", action="tokenize")
        status, payload = self.call(
            "POST", "/rule/resolve", {"fields": ["email_address", "full_name"]}
        )
        self.assertEqual(status, 200, payload)
        decisions = {item["field"]: item for item in payload["decisions"]}

        email = decisions["email_address"]
        self.assertEqual(email["rule"], "email-exact")
        self.assertEqual(email["action"], "hash")
        self.assertTrue(email["contested"])
        self.assertIn("exact pattern beats wildcard pattern", email["explanation"])
        losers = {c["rule"]: c for c in email["contenders"] if c["outcome"] == "defeated"}
        self.assertEqual(set(losers), {"catchall", "email-glob"})
        self.assertIn("defeated by 'email-exact'", losers["catchall"]["reason"])

        name = decisions["full_name"]
        self.assertEqual(name["rule"], "catchall")
        self.assertFalse(name["contested"])

    def test_priority_beats_specificity_in_live_resolve(self) -> None:
        self.create_rule("exact-low", "email_address", priority=1, action="hash")
        self.create_rule("glob-high", "email_*", priority=7, action="tokenize")
        status, payload = self.call("POST", "/rule/resolve", {"fields": ["email_address"]})
        self.assertEqual(status, 200, payload)
        decision = payload["decisions"][0]
        self.assertEqual(decision["rule"], "glob-high")
        self.assertIn("higher priority (7 > 1)", decision["explanation"])

    def test_activation_captures_snapshot_and_serving_uses_it(self) -> None:
        self.create_rule("email-exact", "email_address", action="hash")
        self.create_rule("catchall", "*", action="redact")
        self.create_policy(["email-exact", "catchall"])
        activated = self.activate()
        snapshot_id = activated["snapshot"]
        self.assertTrue(snapshot_id.startswith("snap-"))

        status, payload = self.call("POST", "/dataset/resolve", {"dataset": "ds1"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["snapshot"], snapshot_id)
        decisions = {item["field"]: item for item in payload["decisions"]}
        # public field is not part of the sensitive surface
        self.assertEqual(set(decisions), {"email_address", "full_name"})
        self.assertEqual(decisions["email_address"]["rule"], "email-exact")
        self.assertEqual(decisions["full_name"]["rule"], "catchall")

    def test_rule_removal_does_not_touch_used_snapshots(self) -> None:
        self.create_rule("email-exact", "email_address", action="hash")
        self.create_rule("catchall", "*", action="redact")
        self.create_policy(["email-exact", "catchall"])
        snapshot_id = self.activate()["snapshot"]

        status, before = self.call("POST", "/dataset/resolve", {"dataset": "ds1"})
        self.assertEqual(status, 200, before)

        # disable the rule after results were produced under it
        status, _ = self.call("POST", "/rule/remove", {"identifier": "email-exact"})
        self.assertEqual(status, 200)
        status, _ = self.call("POST", "/rule/remove", {"identifier": "catchall"})
        self.assertEqual(status, 200)

        # serving still resolves through the frozen snapshot, unchanged
        status, after = self.call("POST", "/dataset/resolve", {"dataset": "ds1"})
        self.assertEqual(status, 200, after)
        self.assertEqual(after, before)

        # and the snapshot still explains the past result on demand
        status, explained = self.call(
            "POST",
            "/snapshot/explain",
            {"snapshot": snapshot_id, "fields": ["email_address"]},
        )
        self.assertEqual(status, 200, explained)
        decision = explained["decisions"][0]
        self.assertEqual(decision["rule"], "email-exact")
        self.assertEqual(decision["action"], "hash")
        self.assertIn("exact pattern beats wildcard pattern", decision["explanation"])

    def test_rule_change_produces_new_snapshot_on_next_activation(self) -> None:
        self.create_rule("email-exact", "email_address", action="hash")
        self.create_rule("catchall", "*", action="redact")
        self.create_policy(["email-exact", "catchall"])
        first_snapshot = self.activate()["snapshot"]

        self.call("POST", "/policy/retire", {"identifier": "p1"})
        # change the rule set, then re-activate
        self.call("POST", "/rule/remove", {"identifier": "email-exact"})
        self.create_rule("email-exact", "email_address", action="tokenize")
        second_snapshot = self.activate()["snapshot"]

        self.assertNotEqual(first_snapshot, second_snapshot)

        # the old snapshot still replays the old result
        status, old = self.call(
            "POST",
            "/snapshot/explain",
            {"snapshot": first_snapshot, "fields": ["email_address"]},
        )
        self.assertEqual(status, 200, old)
        self.assertEqual(old["decisions"][0]["action"], "hash")

        # the new snapshot explains the new result
        status, new = self.call(
            "POST",
            "/snapshot/explain",
            {"snapshot": second_snapshot, "fields": ["email_address"]},
        )
        self.assertEqual(status, 200, new)
        self.assertEqual(new["decisions"][0]["action"], "tokenize")

        status, listing = self.call("GET", "/snapshots")
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 2)

    def test_snapshot_detail_is_fetchable(self) -> None:
        self.create_rule("email-exact", "email_address", priority=4, action="hash")
        self.create_policy(["email-exact"])
        snapshot_id = self.activate()["snapshot"]
        status, payload = self.call("GET", "/snapshot", query={"snapshot": snapshot_id})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["identifier"], snapshot_id)
        self.assertEqual(payload["policy"], "p1")
        self.assertEqual(payload["rules"][0]["priority"], 4)
        self.assertEqual(len(payload["digest"]), 64)

    def test_resolve_without_active_policy_is_a_404(self) -> None:
        self.create_rule("catchall", "*")
        status, payload = self.call("POST", "/dataset/resolve", {"dataset": "ds1"})
        self.assertEqual(status, 404)
        self.assertIn("no active policy", payload["error"])

    def test_activation_fails_loudly_when_a_rule_is_missing(self) -> None:
        self.create_rule("catchall", "*")
        self.create_rule("temporary", "tmp_*")
        self.create_policy(["catchall", "temporary"])
        # the rule disappears after the policy was created
        status, _ = self.call("POST", "/rule/remove", {"identifier": "temporary"})
        self.assertEqual(status, 200)
        status, payload = self.call("POST", "/policy/activate", {"identifier": "p1"})
        self.assertEqual(status, 404)
        self.assertIn("temporary", payload["error"])

    def test_snapshot_explain_rejects_unknown_snapshot(self) -> None:
        status, payload = self.call(
            "POST", "/snapshot/explain", {"snapshot": "snap-nope", "fields": ["x"]}
        )
        self.assertEqual(status, 404)
        self.assertIn("unknown snapshot", payload["error"])

    def test_create_rule_rejects_non_integer_priority(self) -> None:
        status, payload = self.call(
            "POST",
            "/rules",
            {
                "identifier": "bad",
                "field_pattern": "*",
                "action": "hash",
                "priority": "high",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("priority", payload["error"])


if __name__ == "__main__":
    unittest.main()
