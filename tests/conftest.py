import shutil
import socket
import subprocess
import time

import pytest

from parcelproof.chain import ARTIFACT_DIR, Chain


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def anvil_url() -> str:
    """A throwaway local EVM node for the session.

    Skips rather than fails when the toolchain is absent so the pure Python suite stays runnable
    without Foundry. CI installs Foundry and runs `forge build`, so these tests do not skip there.
    """
    if shutil.which("anvil") is None:
        pytest.skip("anvil not on PATH; install Foundry to run the on-chain tests")
    if not ARTIFACT_DIR.exists():
        pytest.skip(f"{ARTIFACT_DIR} missing; run `forge build` to run the on-chain tests")

    port = _free_port()
    process = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                Chain(url)
                break
            except (ConnectionError, Exception):  # noqa: B014 - web3 raises several types here
                if process.poll() is not None:
                    raise RuntimeError("anvil exited during startup")
                time.sleep(0.2)
        else:
            raise RuntimeError(f"anvil did not become reachable at {url}")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def chain(anvil_url: str) -> Chain:
    return Chain(anvil_url)
