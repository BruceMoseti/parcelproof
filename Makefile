.PHONY: all install build test test-fast bench gas frontier figures demo clean

PYTHON ?= python3

## Reproduce every table and figure in results/ from scratch.
all: build test bench figures

install:
	$(PYTHON) -m pip install -e ".[dev]"
	forge --version

build:
	forge build

## Solidity unit tests, then the Python suite. The Python on-chain tests need `build` first.
test: build
	forge test
	$(PYTHON) -m pytest -q

## Everything except the tests that need a local EVM node.
test-fast:
	$(PYTHON) -m pytest -q -m "not onchain"

bench: gas frontier

## Measure per-transaction gas on a local EVM. Every gas number in the README comes from here.
gas: build
	$(PYTHON) benchmarks/measure_gas.py

## Simulate anchoring policies and price them with the measured gas.
frontier:
	$(PYTHON) benchmarks/run_frontier.py

figures:
	$(PYTHON) benchmarks/plots.py

## Ingest, anchor, prove, tamper, detect. Starts its own throwaway EVM node.
demo: build
	$(PYTHON) -m parcelproof.demo

clean:
	rm -f results/tables/*.csv results/figures/*.png
	forge clean
