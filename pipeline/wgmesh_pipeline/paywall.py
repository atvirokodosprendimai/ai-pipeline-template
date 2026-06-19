from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class PaywallPattern:
    reason: str
    regex: Pattern[str]


_PATTERNS: tuple[PaywallPattern, ...] = (
    PaywallPattern(
        "license check",
        re.compile(
            r"\b(?:license|license[_-]?check|check[_-]?license|is[_-]?licensed)\b",
            re.IGNORECASE,
        ),
    ),
    PaywallPattern(
        "trial expiry",
        re.compile(
            r"\b(?:trial[_-]?expired|expire[_-]?trial|is[_-]?trial[_-]?expired)\b",
            re.IGNORECASE,
        ),
    ),
    PaywallPattern(
        "routing pause on expiry",
        re.compile(
            r"\b(?:stop[_-]?routing|pause[_-]?on[_-]?expiry)\b"
            r"|stop\s+routing\s+if\s+expired"
            r"|mesh\s+daemons\s+stop\s+routing"
            r"|pause[\s\S]{0,80}expir"
            r"|stop[\s\S]{0,80}routing[\s\S]{0,80}expir"
            r"|expir[\s\S]{0,80}stop[\s\S]{0,80}routing",
            re.IGNORECASE,
        ),
    ),
    PaywallPattern(
        "kill switch",
        re.compile(r"\b(?:kill[\s_.-]?switch|killswitch)\b", re.IGNORECASE),
    ),
    PaywallPattern(
        "pay-to-unlock",
        re.compile(
            r"\b(?:pay[_-]?to[_-]?unlock"
            r"|feature[_-]?gate"
            r"|account[_-]?state"
            r"|payment[_-]?required"
            r"|paywall)\b"
            r"|feature\s+gate\s+on\s+payment"
            r"|pay[\s\S]{0,80}unlock"
            r"|feature[\s_.-]?gate[\s\S]{0,80}payment"
            r"|account[\s\S]{0,80}state[\s\S]{0,80}gat"
            r"|gated[\s_.-]?feature",
            re.IGNORECASE,
        ),
    ),
)


def detect_component_paywall(
    diff: str, changed_files: list[str], spec_content: str = ""
) -> tuple[bool, list[str]]:
    text = f"{diff}\n{spec_content}"
    matched_reasons = tuple(
        pattern.reason for pattern in _PATTERNS if pattern.regex.search(text)
    )
    return len(matched_reasons) == 0, list(matched_reasons)
