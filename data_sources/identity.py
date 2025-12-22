"""Canonical identity helper for A-share symbols.

This module centralizes symbol normalization to avoid ad-hoc formatting
across providers. It infers the exchange from the raw 6-digit code and
exposes multiple derived keys used by different data vendors.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict


@dataclass(frozen=True)
class Identity:
    raw_code: str
    exchange: str
    symbol: str
    prefixed: str
    secid: str
    baostock_code: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def canonical_identity(raw_code: str) -> Identity:
    code = str(raw_code or "").strip()
    code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
    code = code.replace(".", "")
    if code.isdigit():
        code = code.zfill(6)
    # infer exchange
    exch = "SZ"
    if code.startswith(("6", "68", "50", "11", "9", "5")):
        exch = "SH"
    elif code.startswith(("8", "4")):
        exch = "BJ"

    symbol = f"{code}.{exch}"
    pref = f"{exch.lower()}{code}"
    secid_prefix = "0"
    if exch == "SH":
        secid_prefix = "1"
    secid = f"{secid_prefix}.{code}"
    baostock_code = f"{exch.lower()}.{code}"
    return Identity(raw_code=code, exchange=exch, symbol=symbol, prefixed=pref, secid=secid, baostock_code=baostock_code)

