"""Declarative masking rules."""

from maskhub.rule.adjudication import Contender, Decision, adjudicate, adjudicate_all
from maskhub.rule.registry import RuleRegistry
from maskhub.rule.rule import Rule
from maskhub.rule.snapshot import RuleSnapshot, SnapshotRegistry
from maskhub.rule.specificity import Specificity, measure

__all__ = [
    "Contender",
    "Decision",
    "Rule",
    "RuleRegistry",
    "RuleSnapshot",
    "SnapshotRegistry",
    "Specificity",
    "adjudicate",
    "adjudicate_all",
    "measure",
]
