# Roadmap

The standing objective and the phase definitions for this repository. Read this together with
[`CLAUDE.md`](../CLAUDE.md) before starting any work here.

## Objective

Turn this repository from an empty scaffold into a project that answers one measurable question
about supply chain provenance, and publishes the measurement.

The target reader is a hiring engineer who opens the repository, reads for ninety seconds, and
leaves able to state what was built, what it cost, and how it was verified. Every claim they see
must be traceable to a committed artifact produced by a script in this repository.

## Where the repository stands today

The full contents of `main` are three files and under sixty lines, across three commits:

| Path | Lines | State |
|---|---|---|
| `README.md` | 1 | Title only |
| `scripts/dev_up.sh` | 27 | References files that do not exist |
| `scripts/deploy_eth_contract.sh` | 32 | References files that do not exist |

There is no application. The scripts describe an intended system — a Docker Compose stack with a
backend on `:8080`, a Vite frontend on `:5173`, an IPFS gateway on `:8081`, and Truffle contracts
under `contracts/` — but none of those directories, and no `.env.example` or `docker-compose.yml`,
were ever committed. `scripts/dev_up.sh` fails on its first real statement.

Both scripts also carry defects that need resolving if they survive Phase 0:

- `deploy_eth_contract.sh:9` — `OUT="$($(npm run migrate))"` is a nested command substitution. It
  runs `npm run migrate`, then tries to execute that output as a command. It should be
  `OUT="$(npm run migrate)"`.
- `deploy_eth_contract.sh:23` — `sed -i ''` is the BSD form. On Linux and in CI, GNU `sed` reads
  `''` as the script argument and the substitution silently targets the wrong thing.
- `dev_up.sh:15-21` — the health-check loop has no failure branch. After sixty failed attempts it
  falls through and prints the success banner anyway.

This is not a restructuring job. It is a greenfield build with a name attached, and planning it as
a cleanup would understate the work.

## Why the current framing does not clear the bar

Two problems, both worth naming before any code is written.

**The subject matter is a known resume cliché.** "Blockchain for supply chain tracking" is one of
the most common portfolio projects in existence, and the usual version is a CRUD app with a smart
contract bolted on. A quant or ML reviewer discounts it on sight. The blockchain is not what makes
a project interesting; whatever is measured about it might be.

**The repository name reads as a homework submission.** `Block-Chain-Delivery-System---Bruce-Moseti`
follows the "assignment title plus student name" convention. The other repositories in this account
are named `lob-simulator`, `cutout-ml`, `contextforge`, `rootline` — short, lowercase, product-like.
Renaming costs nothing and GitHub preserves redirects.

The bar to clear is set by `lob-simulator`, in this same account: a stated research question, a
headline results table where every cell traces to a CSV under `results/tables/`, and `make all`
reproducing the whole thing from scratch. That is the standard this repository has to meet, and the
subject matter has to be chosen so that meeting it is possible.

## The reframe

Keep the delivery domain. Replace "we put deliveries on a blockchain" with a cost question that has
a real answer.

> **Research question.** On-chain anchoring makes parcel custody records tamper-evident, but every
> anchor costs gas and delays settlement. What anchoring policy minimises amortised cost per custody
> event subject to a settlement latency SLA, and what does provenance actually cost per ten thousand
> parcels?

This works because the honest reason logistics companies do not put custody records on-chain is
cost, and nobody publishes the curve. Measuring it is a contribution, not a demo.

It also has a property most portfolio benchmarks lack: **EVM gas is deterministic**. Given fixed
bytecode and a fixed input trace, gas consumption is identical on every run. The reproducibility
claim is exact rather than statistical, which is a stronger guarantee than `lob-simulator` can make
and is worth saying out loud in the README.

**The headline artifact** is one sentence a recruiter can read and an engineer can check:

> Anchoring custody events in Merkle batches of *B* cuts amortised on-chain cost from *$A* to *$C*
> per 10,000 parcels at *G* gwei, a *N*x reduction, while holding p95 settlement latency under *M*
> minutes. Inclusion proofs remain *P* bytes and cost *V* gas to verify on-chain.

Every symbol in that sentence is filled from a CSV in `results/tables/`. None of them are guessed
here.

## Three pillars, one per audience

Each pillar is independently shippable and each maps to one of the reviewer types.

### Pillar 1 — Verifiable custody (software engineering)

An off-chain custody event log with an on-chain Merkle root. Events are recorded in Postgres,
batched into a Merkle tree, and only the root is written on-chain. An inclusion proof endpoint
returns the path for any event; a verifier checks it against the root.

The demonstration that matters: pull a proof for a custody event, verify it, then mutate that row
in the database and show verification fail. Tamper evidence stops being a claim in a README and
becomes something the reader watches happen.

### Pillar 2 — The cost and latency frontier (quant)

A sweep over anchoring strategies and batch sizes, measuring what each actually costs.

Strategies to compare: per-event storage write, per-event event log, and batched Merkle anchoring
at batch sizes across roughly 1 to 2048. The gas schedule makes a large gap plausible — a cold
storage write is orders of magnitude more expensive than a calldata byte — but *plausible is not
measured*, and the numbers in the README come only from `make bench`.

Measure per configuration: total gas, amortised gas per custody event, calldata bytes, proof size,
and on-chain verification gas for an inclusion proof. Note that verification cost grows with
log(batch size) while anchoring cost per event falls with batch size, so there is a genuine
two-sided tradeoff rather than a monotone win.

Settlement latency comes from a queueing model over the anchor policy: with batch size *B*, a
maximum wait timer *T*, and Poisson arrivals at rate *λ*, an event waits for its batch to fill or
for the timer to expire. Report the full latency distribution, not just the mean — p50, p95, p99.
This reuses the Poisson arrival machinery already demonstrated in `lob-simulator`, which makes the
two projects read as a coherent line of work rather than unrelated exercises.

The deliverable is the frontier: amortised cost per event against p95 settlement latency, with the
knee identified and the policy that sits on it.

### Pillar 3 — Delivery ETA prediction (ML/AI)

Only after pillars 1 and 2 are committed and reproducible.

The custody event stream is naturally a supervised problem: given the events observed so far,
predict remaining time to delivery. Use real data — the Olist Brazilian e-commerce dataset has
roughly a hundred thousand orders with genuine purchase, carrier handoff, and delivery timestamps.
Do not commit the raw dataset; commit a download script and a checksum, and record the licence.

Baselines are the point, not model complexity. Report a global median baseline, then a
route-and-carrier historical median, then a gradient boosted model, all on the same held-out split
computed by the same script. Report MAE, P90 absolute error, and calibration. If the model does not
beat the route-median baseline, that is the result and it gets published as the result.

## Explicit non-goals

Cutting these is part of the plan, and the README should say they were cut on purpose.

- **IPFS.** Present in the original `dev_up.sh`. It adds a service to the diagram and unlocks no
  number. Cut unless a measurement requires it.
- **Truffle.** Sunset upstream. Use Foundry: `forge snapshot` and `forge test --gas-report` produce
  exactly the deterministic gas accounting Pillar 2 depends on, which makes this a tooling choice
  the benchmark actually rests on rather than a preference.
- **Any token, coin, or NFT.** Nothing here needs one and their presence invites the exact
  dismissal this reframe exists to avoid.
- **Multi-chain support, wallet integrations, user account systems, role-based admin dashboards.**
  None are load-bearing for the research question.
- **Mainnet deployment.** A local Anvil devnet gives identical gas accounting for free. If a public
  testnet deployment is added later it is for the demo link, not the measurements.

## Phases

Each phase states its verification. A phase is not finished until its check passes.

**Phase 0 — Decide and reset.**
Settle the open decisions below. Rename the repository. Replace the one-line README with an honest
description of what is being built. Either fix the three script defects or delete the scripts as
part of the Foundry migration.
→ verify: `README.md` states the research question; no committed script references a path that does
not exist.

**Phase 1 — Custody ledger and anchoring.**
Solidity anchor contract, Postgres event log, Merkle tree construction, inclusion proof endpoint,
FastAPI backend, Docker Compose, `.env.example`, CI running the full test suite.
→ verify: a test mutates a committed custody record and asserts inclusion proof verification flips
from pass to fail; `docker compose up` followed by the seed script produces a verifiable proof on a
clean machine; CI is green.

**Phase 2 — The benchmark.**
`benchmarks/` harness, the strategy and batch size sweep, the latency model, `results/tables/*.csv`,
`results/figures/*.png`, and the headline table in the README.
→ verify: `make bench` reproduces every gas column byte-identically on a second run; every number in
the README resolves to a committed CSV; the frontier figure is committed.

**Phase 3 — ETA prediction.**
Dataset download script with checksum, feature construction from the custody event schema, the three
baselines, held-out evaluation, metrics written to `results/`.
→ verify: `make eval` reproduces the metrics table; the README reports the model against both
baselines on the same split, including the case where it loses.

**Phase 4 — Make it legible.**
`docs/ARCHITECTURE.md`, a deployed demo following the pattern already used by `firstpass-app` and
`resume-lock-app`, a case study page walking through one parcel from pickup to proof, and repository
topics.
→ verify: a reader who has never seen the repository can, from the README alone, state what was
built, what it cost, and how tamper evidence was demonstrated.

## Target layout

Modelled on `lob-simulator` and `rootline`, both in this account.

```
README.md                 headline table, research question, architecture
CLAUDE.md                 behavioural guidelines + project rules
LICENSE                   MIT, matching the other repositories
Makefile                  make up / test / bench / eval / all
docker-compose.yml
.env.example
contracts/                Foundry project: anchor contract + gas tests
backend/                  FastAPI: ingest, batching, proof endpoints
  tests/
benchmarks/               sweep scripts, latency model
results/tables/           committed CSVs — every README number lives here
results/figures/          committed PNGs
ml/                       Phase 3 only
docs/ARCHITECTURE.md
docs/ROADMAP.md           this file
.github/workflows/ci.yml
```

## Open decisions

These need an answer before Phase 1 and should not be resolved silently.

1. **Keep the blockchain framing at all?** The alternative is to archive this repository and put the
   same effort into deepening `lob-simulator` or `contextforge`, which already carry the quant and
   ML signal. The reframe above is worth building only if the cost question is genuinely interesting
   to its author; a second flagship is worth more than a fourth adequate repository. This is the
   decision that determines whether any of the rest happens.
2. **New name.** `parcelproof` matches the naming convention already in use. `custody-chain` and
   `provenance-ledger` are alternatives. The current name should not survive either way.
3. **Scope floor.** Phases 1 and 2 alone make the repository defensible to a software engineering
   and a quant reviewer. Phase 3 is what adds the ML signal, and it is also the phase most likely to
   produce a negative result. Decide up front whether a negative ETA result will be published,
   because deciding afterwards is how projects quietly lose their integrity.
4. **Real data in Phase 3.** Olist is real, licensed, and citable, which is a large step up from a
   synthetic generator. Confirm its licence permits the intended use before building on it.
