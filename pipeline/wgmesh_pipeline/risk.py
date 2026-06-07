from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


HIGH_RISK_RE = re.compile(
    r"auth|authn|oauth|crypto|wireguard[ -]?key|secrets?|token|credential|payment|polar|billing|stripe",
    re.IGNORECASE,
)
NET_NEW_CALL_RE = re.compile(
    r"\b(http\.(Post|Get|Do)|http\.NewRequest|fetch\(|axios\.|requests\.|urllib\.|net\.Dial|grpc\.Dial|curl\s+|https?://)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RiskResult:
    tier: str
    reasons: tuple[str, ...]

    @property
    def high(self) -> bool:
        return self.tier == "high"


def classify_risk(changed_files: Iterable[str], diff_text: str, *, max_files: int) -> RiskResult:
    files = tuple(changed_files)
    reasons: list[str] = []

    risky_paths = [path for path in files if HIGH_RISK_RE.search(path)]
    if risky_paths:
        reasons.append(f"high-risk path: {risky_paths[0]}")

    if len(files) > max_files:
        reasons.append(f"changed file count {len(files)} exceeds MAX_FILES={max_files}")

    if _adds_network_call(diff_text):
        reasons.append("net-new outbound network call")

    if reasons:
        return RiskResult(tier="high", reasons=tuple(reasons))
    return RiskResult(tier="low", reasons=())


def _adds_network_call(diff_text: str) -> bool:
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if NET_NEW_CALL_RE.search(line[1:]):
            return True
    return False

