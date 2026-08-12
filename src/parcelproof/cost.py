"""Turning measured gas into money.

Gas is measured and deterministic. Prices are not: they are assumptions, and every number derived
from them inherits that. The two are kept apart here so that a reader can tell which figures in the
README are measurements and which are a measurement multiplied by a stated price.
"""

from __future__ import annotations

from dataclasses import dataclass

WEI_PER_GWEI = 10**9
WEI_PER_ETH = 10**18


@dataclass(frozen=True)
class PriceScenario:
    """A gas price and ETH price to convert gas into USD.

    These are inputs, not findings. `benchmarks/measure_gas.py` records the scenarios it used
    alongside every cost column so the assumption travels with the result.
    """

    name: str
    gas_price_gwei: float
    eth_price_usd: float

    def usd(self, gas: float) -> float:
        wei = gas * self.gas_price_gwei * WEI_PER_GWEI
        return wei / WEI_PER_ETH * self.eth_price_usd


SCENARIOS = (
    PriceScenario("calm", gas_price_gwei=5.0, eth_price_usd=3000.0),
    PriceScenario("typical", gas_price_gwei=20.0, eth_price_usd=3000.0),
    PriceScenario("congested", gas_price_gwei=50.0, eth_price_usd=3000.0),
)
