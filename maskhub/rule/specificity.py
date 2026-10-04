"""Deterministic specificity measurement for field patterns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Specificity:
    """How narrowly a pattern targets field names.

    Exact patterns (no wildcards) outrank wildcard patterns; among wildcard
    patterns, more literal characters and fewer wildcard tokens win.
    """

    exact: bool
    literals: int
    wildcards: int

    def rank(self) -> tuple[int, int, int]:
        """Sort key where the more specific pattern compares smaller."""

        return (0 if self.exact else 1, -self.literals, self.wildcards)

    def describe(self) -> str:
        if self.exact:
            return f"exact pattern ({self.literals} literals, no wildcards)"
        return (
            f"wildcard pattern ({self.literals} literals, "
            f"{self.wildcards} wildcards)"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "exact": self.exact,
            "literals": self.literals,
            "wildcards": self.wildcards,
            "summary": self.describe(),
        }


def measure(pattern: str) -> Specificity:
    """Count literal characters and wildcard tokens in an fnmatch pattern."""

    literals = 0
    wildcards = 0
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char in "*?":
            wildcards += 1
            index += 1
        elif char == "[":
            end = _bracket_end(pattern, index)
            if end is None:
                literals += 1  # an unterminated '[' matches literally
                index += 1
            else:
                wildcards += 1
                index = end + 1
        else:
            literals += 1
            index += 1
    return Specificity(exact=wildcards == 0, literals=literals, wildcards=wildcards)


def _bracket_end(pattern: str, start: int) -> int | None:
    index = start + 1
    if index < len(pattern) and pattern[index] == "!":
        index += 1
    if index < len(pattern) and pattern[index] == "]":
        index += 1  # a leading ']' is a literal member of the class
    while index < len(pattern) and pattern[index] != "]":
        index += 1
    return index if index < len(pattern) else None
