import shutil

import pytest

from parcelproof.chain import ARTIFACT_DIR, Chain, local_node


@pytest.fixture(scope="session")
def chain() -> Chain:
    """A throwaway local EVM node for the session.

    Skips rather than fails when the toolchain is absent, so the pure Python suite stays runnable
    without Foundry. CI installs Foundry and runs `forge build`, so these tests do not skip there.
    """
    if shutil.which("anvil") is None:
        pytest.skip("anvil not on PATH; install Foundry to run the on-chain tests")
    if not ARTIFACT_DIR.exists():
        pytest.skip(f"{ARTIFACT_DIR} missing; run `forge build` to run the on-chain tests")

    with local_node() as node:
        yield node
