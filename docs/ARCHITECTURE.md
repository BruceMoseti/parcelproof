# Architecture

Design decisions and their reasons, including the ones that constrain what the system can claim.

## What the system is for

A carrier records custody events for parcels: picked up here, arrived at that facility, delivered at
this time. Those records are commercially meaningful — they settle disputes, trigger penalties under
service level agreements, and support insurance claims. They also sit in a database controlled by the
party with the most to gain from editing them.

parcelproof does not move custody records on-chain. It publishes a commitment to them, so that an
edit made after the fact is detectable by anyone holding the commitment, including the carrier's own
auditors and its customers.

## Threat model

**In scope.** An insider with full read and write access to the custody database, acting after the
fact. They can update, insert, delete, and re-run any application logic. What they cannot do is
change a value that was already anchored on-chain.

Concretely: backdating a scan so a delivery appears to have met its service window; rewriting the
facility a parcel passed through to hide a misroute; deleting an exception event. Each of these
changes the leaf hash of the affected event, so the recomputed root no longer matches the anchored
one, and the inclusion proof fails.

**Out of scope.**

- *Bad data at ingest.* Anchoring proves a record has not changed since it was anchored. It says
  nothing about whether it was true when it was written. A scanner that reports the wrong location
  produces a record that is wrong and provably unmodified.
- *Withholding.* An operator who never anchors a batch, or who drops an event before it is sealed,
  leaves nothing to detect. Anchoring makes edits visible; it does not make omissions visible.
  Detecting those needs an external party to independently observe events, which is a different
  system.
- *Chain-level attacks.* Reorgs, censorship, and the security of the underlying chain are assumed
  away.

## Why the leaf hash is not stored

The custody table has columns for event content and no column for the leaf hash. That is deliberate,
and it is the single most important design decision here.

Storing the hash would create two representations of the same fact. Verification code would then have
a choice about which to trust, and the cheap path — read the stored hash, fold the proof, compare to
the root — would verify that the batch is internally consistent while proving nothing about whether
the event content still matches. An attacker who can edit the content columns can edit a hash column
in the same `UPDATE`.

With no stored hash, recomputing from content is the only thing verification can do. The property
becomes structural rather than a convention that a future change might quietly break.

## Canonical encoding

Leaves are `keccak256(0x00 || encoding)`, where the encoding writes each field as a four-byte
big-endian length followed by its UTF-8 text, in a fixed order.

Length prefixes rather than a delimiter, because a delimiter needs escaping rules to be safe. Under
an encoding that joined fields with `|`, an event with `actor = "carrier-north"` and
`location = "EWR-01"` would produce the same bytes as one with `actor = "carrier-north|EWR-01"` and
an empty location, and a parcel's location could be rewritten without breaking its proof. That
collision is asserted absent in
[`tests/test_events.py`](../tests/test_events.py).

Changing the field order, or the set of fields, changes every leaf hash and invalidates every root
already anchored. It is a breaking change to historical data, not just to code.

## Merkle tree

Two rules make a leaf set map to exactly one root.

**Sorted pairs.** Siblings are ordered before hashing, so a proof is a bare list of hashes with no
direction bits. Cheaper in calldata, and there is one less thing for the two implementations to
disagree about.

**Promotion, not duplication.** A level with an odd node count promotes the last node unchanged.
Duplicating it instead — a common shortcut — means `[a, b, c]` and `[a, b, c, c]` produce the same
root, so a batch could be extended without changing its commitment. Asserted in
[`tests/test_merkle.py`](../tests/test_merkle.py).

**Domain separation.** Leaves are prefixed `0x00` and internal nodes `0x01`. Without it, an internal
node could be presented as a committed leaf, letting a prover claim membership for something that was
never an event.

## What the contract binds, and what it does not

`MerkleAnchor.verify(batchId, leaf, proof)` answers exactly one question: is this 32-byte leaf a
member of the batch committed under this id?

It does not check that the leaf is the hash of any particular custody event. Binding leaf to content
on-chain would mean sending the encoded event as calldata and hashing it in the contract, which costs
calldata for every verification and puts the encoding rules in two places that must agree forever.

The consequence: **a verifier must recompute the leaf itself.** A verifier that accepts a leaf
supplied by the party being audited has verified nothing. The audit path in
[`tests/test_tamper.py`](../tests/test_tamper.py) is written the way an external auditor would do it —
fetch the record, recompute the leaf locally, fold the proof, compare against the root read from the
chain — and that ordering is the point, not an implementation detail.

## Anchoring policy

Anchor when `batch_size` events are pending, or when the oldest pending event has waited
`timeout_s`, whichever comes first.

The timeout is what makes large batches usable. Without it a quiet period leaves events unanchored
indefinitely, so the worst case latency is unbounded and depends on traffic that has not arrived yet.
With it, latency is bounded by `timeout_s` plus one block regardless of batch size, and the cost of
that guarantee is that a partially filled batch pays the full price of an anchor. At low throughput
the timeout dominates and the realised batch is closer to `rate x timeout` than to the configured
size, which is finding 4 in the README.

## Why SQLite and not Postgres

The interesting properties here are cryptographic, not operational. A single-file database means
anyone can clone the repository and reproduce the tamper demonstration with `make demo`, without
Docker, a server, or configuration.

Postgres would add a service to the diagram and would not change a single number in `results/`. The
repository's own rule for new infrastructure — it has to unlock a measurement — rules it out. The
`Ledger` interface is small and synchronous, so the swap is unremarkable if the system ever needed
concurrent writers.

## Why gas comes from receipts, not from `forge test`

`forge test --gas-report` measures the gas consumed inside a call. A transaction also pays 21,000 gas
of intrinsic cost and the cost of its calldata, and those two terms are most of what separates
per-event anchoring from batched anchoring. Measuring only the internal call would hide the effect
the benchmark exists to quantify: at B=4096 the amortised cost per event is 18.2 gas, which is far
below the intrinsic cost of a single transaction, and that is only a coherent statement because the
intrinsic cost is being amortised too.

Verification cost is measured by sending a transaction to `verify`, which is a `view` function.
`view` is enforced by the Solidity compiler when one contract calls another; it does not stop an
account from calling the function in a transaction. So the measurement needs no benchmark-only entry
point in the contract.

## Reproducibility

Gas is a deterministic function of bytecode, input, and hardfork. All three are pinned:

| What | Where | Why |
|---|---|---|
| `solc_version = "0.8.28"` | [`foundry.toml`](../foundry.toml) | Compiler output, and therefore gas, changes between versions |
| `evm_version = "cancun"` | `foundry.toml` | Controls which opcodes the compiler may emit |
| `optimizer`, `optimizer_runs = 200` | `foundry.toml` | Optimisation level changes the code being measured |
| `bytecode_hash = "none"`, `cbor_metadata = false` | `foundry.toml` | Keeps a metadata hash out of the bytecode, so builds are identical |
| `HARDFORK = "prague"` | [`chain.py`](../src/parcelproof/chain.py) | Anvil defaults to `latest`, which tracks unreleased forks |
| Trace seed `20260812` | `benchmarks/` | Fixes which leaf hashes are measured, and therefore the calldata discount |

The last two matter more than they look. Prague's calldata floor makes a 12-hash proof 4.1% more
expensive than on Cancun, so an unpinned hardfork would move published numbers on a toolchain
upgrade. And because a zero calldata byte costs 4 gas against 16 for a non-zero one, the specific
hashes being measured affect the total; seeding the trace fixes them.

A CI job re-measures gas on every push and fails on any diff against the committed tables.
