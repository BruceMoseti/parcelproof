from parcelproof.cost import SCENARIOS, PriceScenario


def test_usd_conversion_matches_hand_arithmetic():
    """21,000 gas at 20 gwei is 0.00042 ETH, which is $1.26 at $3,000."""
    scenario = PriceScenario("check", gas_price_gwei=20.0, eth_price_usd=3000.0)
    assert scenario.usd(21_000) == 1.26


def test_cost_is_linear_in_gas():
    scenario = PriceScenario("check", gas_price_gwei=7.5, eth_price_usd=2500.0)
    assert scenario.usd(2_000) == 2 * scenario.usd(1_000)


def test_zero_gas_costs_nothing():
    assert SCENARIOS[0].usd(0) == 0.0


def test_published_scenarios_are_ordered_by_gas_price():
    prices = [scenario.gas_price_gwei for scenario in SCENARIOS]
    assert prices == sorted(prices)
    assert [scenario.name for scenario in SCENARIOS] == ["calm", "typical", "congested"]
