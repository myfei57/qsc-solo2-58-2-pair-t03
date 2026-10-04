"""Unit tests for pattern specificity and multi-rule adjudication."""

from __future__ import annotations

import unittest

from maskhub.rule.adjudication import adjudicate, adjudicate_all
from maskhub.rule.rule import Rule
from maskhub.rule.specificity import measure


def make_rule(identifier: str, pattern: str, priority: int = 0, action: str = "hash") -> Rule:
    return Rule(
        identifier=identifier,
        field_pattern=pattern,
        action=action,
        parameters={},
        priority=priority,
    )


class SpecificityTest(unittest.TestCase):
    def test_exact_pattern_has_no_wildcards(self) -> None:
        spec = measure("email_address")
        self.assertTrue(spec.exact)
        self.assertEqual(spec.literals, 13)
        self.assertEqual(spec.wildcards, 0)

    def test_wildcard_tokens_and_literals_are_counted(self) -> None:
        spec = measure("email_*")
        self.assertFalse(spec.exact)
        self.assertEqual(spec.literals, 6)
        self.assertEqual(spec.wildcards, 1)

    def test_question_mark_and_brackets_count_as_wildcards(self) -> None:
        spec = measure("user_?[0-9]")
        self.assertFalse(spec.exact)
        self.assertEqual(spec.literals, 5)
        self.assertEqual(spec.wildcards, 2)

    def test_unterminated_bracket_is_a_literal(self) -> None:
        spec = measure("a[")
        self.assertTrue(spec.exact)
        self.assertEqual(spec.literals, 2)

    def test_exact_outranks_wildcard_regardless_of_length(self) -> None:
        self.assertLess(measure("ab").rank(), measure("very_long_pattern_*").rank())


class AdjudicationTest(unittest.TestCase):
    def test_no_match_yields_unmatched_decision(self) -> None:
        decision = adjudicate("unknown_column", [make_rule("r1", "email_*")])
        self.assertFalse(decision.matched)
        self.assertIsNone(decision.rule)
        self.assertIsNone(decision.action)
        self.assertFalse(decision.contested)
        self.assertIn("no rule pattern matches", decision.explanation)

    def test_single_match_wins_trivially(self) -> None:
        decision = adjudicate("email_address", [make_rule("r1", "email_*")])
        self.assertTrue(decision.matched)
        self.assertEqual(decision.rule, "r1")
        self.assertFalse(decision.contested)
        self.assertEqual(decision.contenders[0].outcome, "winner")
        self.assertEqual(decision.contenders[0].reason, "only matching rule")

    def test_higher_priority_wins_over_specificity(self) -> None:
        exact_low = make_rule("exact-low", "email_address", priority=1)
        glob_high = make_rule("glob-high", "*", priority=9)
        decision = adjudicate("email_address", [exact_low, glob_high])
        self.assertEqual(decision.rule, "glob-high")
        self.assertTrue(decision.contested)
        self.assertIn("higher priority (9 > 1)", decision.explanation)

    def test_exact_pattern_beats_wildcard_at_equal_priority(self) -> None:
        exact = make_rule("exact", "email_address")
        prefix = make_rule("prefix", "email_*")
        catchall = make_rule("catchall", "*")
        decision = adjudicate("email_address", [catchall, prefix, exact])
        self.assertEqual(decision.rule, "exact")
        self.assertIn("exact pattern beats wildcard pattern", decision.explanation)
        reasons = {item.rule: item.reason for item in decision.contenders}
        self.assertIn("defeated by 'exact'", reasons["prefix"])
        self.assertIn("defeated by 'exact'", reasons["catchall"])

    def test_more_literals_win_among_wildcard_patterns(self) -> None:
        longer = make_rule("longer", "email_addr*")
        shorter = make_rule("shorter", "email_*")
        decision = adjudicate("email_address", [shorter, longer])
        self.assertEqual(decision.rule, "longer")
        self.assertIn("more literal characters (10 > 6)", decision.explanation)

    def test_fewer_wildcards_win_at_equal_literal_count(self) -> None:
        one_star = make_rule("one-star", "email*address")
        two_stars = make_rule("two-stars", "emai*l*address")
        decision = adjudicate("emailXaddress", [two_stars, one_star])
        self.assertEqual(decision.rule, "one-star")
        self.assertIn("fewer wildcards (1 < 2)", decision.explanation)

    def test_identifier_is_the_final_deterministic_tiebreaker(self) -> None:
        first = make_rule("alpha", "email_*")
        second = make_rule("beta", "email_*")
        decision = adjudicate("email_address", [second, first])
        self.assertEqual(decision.rule, "alpha")
        self.assertIn("identifier 'alpha' sorts before 'beta'", decision.explanation)

    def test_outcome_does_not_depend_on_registration_order(self) -> None:
        rules = [
            make_rule("catchall", "*"),
            make_rule("exact", "email_address", priority=0),
            make_rule("priority", "email_*", priority=5),
        ]
        forward = adjudicate("email_address", rules)
        backward = adjudicate("email_address", list(reversed(rules)))
        self.assertEqual(forward.rule, "priority")
        self.assertEqual(forward.as_dict(), backward.as_dict())

    def test_contenders_are_ordered_winner_first(self) -> None:
        rules = [
            make_rule("catchall", "*"),
            make_rule("exact", "email_address"),
            make_rule("prefix", "email_*"),
        ]
        decision = adjudicate("email_address", rules)
        outcomes = [item.outcome for item in decision.contenders]
        self.assertEqual(outcomes[0], "winner")
        self.assertEqual(outcomes[1:], ["defeated", "defeated"])
        self.assertEqual(
            [item.rule for item in decision.contenders],
            ["exact", "prefix", "catchall"],
        )

    def test_adjudicate_all_covers_every_field(self) -> None:
        rules = [make_rule("exact", "email_address", action="tokenize")]
        decisions = adjudicate_all(["email_address", "other"], rules)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0].action, "tokenize")
        self.assertFalse(decisions[1].matched)

    def test_decision_as_dict_is_json_shaped(self) -> None:
        decision = adjudicate(
            "email_address",
            [make_rule("exact", "email_address"), make_rule("catchall", "*")],
        )
        payload = decision.as_dict()
        self.assertEqual(payload["field"], "email_address")
        self.assertEqual(payload["rule"], "exact")
        self.assertTrue(payload["matched"])
        self.assertTrue(payload["contested"])
        self.assertEqual(payload["contenders"][0]["specificity"]["exact"], True)


if __name__ == "__main__":
    unittest.main()
