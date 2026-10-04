import tempfile
import unittest
from pathlib import Path

from maskhub.catalog.dataset import Dataset
from maskhub.catalog.field import Field
from maskhub.console.runtime import build_runtime
from maskhub.policy.policy import Policy
from maskhub.rule.adjudication import adjudicate
from maskhub.policy.coverage import check_coverage
from maskhub.rule.rule import Rule
from maskhub.source.registry import Source
from maskhub.store.kvstore import RecordStore


class AdjudicationTest(unittest.TestCase):
    def test_priority_takes_precedence_and_explains_losers(self):
        decision = adjudicate(
            "user_email",
            [
                Rule("generic", "*email", "redact", priority=100),
                Rule("exact", "user_email", "hash", priority=10),
            ],
        )

        self.assertEqual(decision.selected_rule, "generic")
        self.assertIn("higher priority", decision.reason)
        self.assertEqual(
            [candidate.rule_id for candidate in decision.candidates],
            ["generic", "exact"],
        )

    def test_specificity_and_identifier_break_priority_ties(self):
        decision = adjudicate(
            "user_email",
            [
                Rule("b", "user_email", "hash", priority=100),
                Rule("a", "user_email", "redact", priority=100),
                Rule("c", "*_email", "tokenize", priority=100),
            ],
        )

        self.assertEqual(decision.selected_rule, "a")
        self.assertIn("more specific", decision.reason)
        self.assertIn("lexicographically smallest", decision.reason)

    def test_disabled_rules_remain_visible_but_are_not_selected(self):
        decision = adjudicate(
            "email",
            [
                Rule("on", "email", "hash", enabled=True),
                Rule("off", "*mail", "redact", enabled=False),
            ],
        )

        self.assertEqual(decision.selected_rule, "on")
        self.assertEqual([item.rule_id for item in decision.ignored], ["off"])


class SnapshotTest(unittest.TestCase):
    def make_runtime(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = build_runtime(RecordStore(Path(temp.name)))
        runtime.sources.register(Source("source", "database", "endpoint"))
        runtime.datasets.save(
            Dataset(
                "dataset",
                "source",
                "owner",
                (Field("user_email", "personal", "owner"),),
            )
        )
        runtime.rules.add(Rule("exact", "user_email", "hash", priority=10))
        runtime.rules.add(Rule("wildcard", "*_email", "redact", priority=10))
        runtime.policies.save(Policy("policy", ("dataset",), ("exact", "wildcard")))
        return runtime

    def test_later_changes_do_not_mutate_activation_snapshot(self):
        runtime = self.make_runtime()
        activated = runtime.policies.activate(
            "policy",
            snapshots=runtime.snapshots,
            rules=runtime.rules,
        )

        runtime.rules.save(Rule("exact", "user_email", "tokenize", priority=100))
        runtime.rules.set_enabled("wildcard", False)

        snapshot = runtime.snapshots.get(activated.snapshot_id)
        self.assertEqual(snapshot.rule("exact").action, "hash")
        self.assertEqual(snapshot.rule("exact").priority, 10)
        self.assertTrue(snapshot.rule("wildcard").enabled)

        report = check_coverage(
            "policy",
            "dataset",
            runtime.policies,
            runtime.datasets,
            runtime.rules,
            runtime.snapshots,
        )
        self.assertEqual(report.snapshot_id, activated.snapshot_id)
        self.assertEqual(report.selected_rules["user_email"], "exact")


if __name__ == "__main__":
    unittest.main()
