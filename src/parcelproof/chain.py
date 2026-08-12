"""Talking to a local EVM node.

Gas is read from transaction receipts rather than from `forge test`. The difference matters: a
receipt includes the 21,000 gas intrinsic cost of a transaction and the cost of its calldata, and
those two terms are most of what separates per-event anchoring from batched anchoring. Measuring
only the internal call would quietly hide the effect the benchmark exists to quantify.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = REPO_ROOT / "contracts" / "out" / "CustodyAnchor.sol"
DEFAULT_RPC_URL = "http://127.0.0.1:8545"


class ArtifactMissing(RuntimeError):
    pass


def load_artifact(contract_name: str) -> dict:
    path = ARTIFACT_DIR / f"{contract_name}.json"
    if not path.exists():
        raise ArtifactMissing(f"{path} not found; run `forge build` first")
    return json.loads(path.read_text())


# EIP-2028 calldata pricing. A non-zero byte costs 16 gas, a zero byte costs 4, so two
# transactions running identical code still differ in gas when their arguments contain different
# numbers of zero bytes. Hashes are effectively random, so this shows up constantly.
GAS_PER_NONZERO_CALLDATA_BYTE = 16
GAS_PER_ZERO_CALLDATA_BYTE = 4
ZERO_BYTE_DISCOUNT = GAS_PER_NONZERO_CALLDATA_BYTE - GAS_PER_ZERO_CALLDATA_BYTE


@dataclass(frozen=True)
class Receipt:
    tx_hash: str
    gas_used: int
    calldata_bytes: int
    calldata_zero_bytes: int

    @property
    def gas_at_uniform_calldata(self) -> int:
        """Gas with the zero-byte calldata discount removed.

        Charging every calldata byte the non-zero rate isolates the part of the cost that comes
        from the code path rather than from the accident of which bytes the arguments happened to
        contain. For a fixed call shape this value is exactly constant, which is what lets the
        benchmark extrapolate a full trace from a sample of transactions.
        """
        return self.gas_used + ZERO_BYTE_DISCOUNT * self.calldata_zero_bytes


class Chain:
    """A thin wrapper over a development node with unlocked accounts."""

    def __init__(self, rpc_url: str = DEFAULT_RPC_URL) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(
                f"no EVM node at {rpc_url}; start one with `anvil` or run `make bench`"
            )
        self.account = self.w3.eth.accounts[0]
        self.w3.eth.default_account = self.account

    def deploy(self, contract_name: str) -> Contract:
        artifact = load_artifact(contract_name)
        factory = self.w3.eth.contract(
            abi=artifact["abi"], bytecode=artifact["bytecode"]["object"]
        )
        tx_hash = factory.constructor().transact()
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return self.w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])

    def send(self, function_call) -> Receipt:
        """Send a contract call as a transaction and return its measured gas.

        Works for `view` functions too. `view` is enforced by the Solidity compiler when one
        contract calls another, not by the EVM when an account submits a transaction, so
        verification cost can be measured without adding a benchmark-only function to the
        contract.
        """
        data = function_call._encode_transaction_data()
        tx_hash = self.w3.eth.send_transaction(
            {"from": self.account, "to": function_call.address, "data": data}
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt["status"] != 1:
            raise RuntimeError(f"transaction reverted: {tx_hash.hex()}")
        calldata = bytes.fromhex(data[2:] if data.startswith("0x") else data)
        return Receipt(
            tx_hash=tx_hash.hex(),
            gas_used=int(receipt["gasUsed"]),
            calldata_bytes=len(calldata),
            calldata_zero_bytes=calldata.count(0),
        )
