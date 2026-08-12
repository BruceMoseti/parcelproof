// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title Merkle helpers shared by the anchoring contracts.
/// @dev Leaves and internal nodes are hashed with different one byte prefixes. Without that
/// separation an internal node could be presented as a leaf, which lets a prover claim
/// membership for data that was never committed. Pairs are sorted before hashing so a proof
/// does not have to carry direction bits.
library CustodyMerkle {
    bytes1 internal constant LEAF_PREFIX = 0x00;
    bytes1 internal constant NODE_PREFIX = 0x01;

    function hashLeaf(bytes memory encodedEvent) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(LEAF_PREFIX, encodedEvent));
    }

    function hashPair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b
            ? keccak256(abi.encodePacked(NODE_PREFIX, a, b))
            : keccak256(abi.encodePacked(NODE_PREFIX, b, a));
    }

    /// @notice Folds an inclusion proof over a leaf to produce a candidate root.
    function processProof(bytes32 leaf, bytes32[] calldata proof) internal pure returns (bytes32) {
        bytes32 node = leaf;
        for (uint256 i = 0; i < proof.length; ++i) {
            node = hashPair(node, proof[i]);
        }
        return node;
    }
}

/// @title Anchoring strategy A: one storage slot per custody event.
/// @notice The naive design. Included so the benchmark has a real baseline to measure against
/// rather than an estimated one.
contract PerEventStorage {
    mapping(bytes32 => uint256) public recordedAt;

    function record(bytes32 eventHash) external {
        recordedAt[eventHash] = block.number;
    }
}

/// @title Anchoring strategy B: one log entry per custody event, no storage.
/// @notice Cheaper than strategy A but gives up cheap on-chain readback: a contract cannot
/// query a log, so membership can only be checked by an off-chain indexer.
contract PerEventLog {
    event CustodyRecorded(bytes32 indexed eventHash);

    function record(bytes32 eventHash) external {
        emit CustodyRecorded(eventHash);
    }
}

/// @title Anchoring strategy C: one storage slot per batch, committed as a Merkle root.
/// @notice Custody events stay off-chain. Only the root of each batch is written on-chain, so
/// the per-event cost falls with batch size while inclusion proofs grow with log2 of it.
contract MerkleAnchor {
    struct Batch {
        bytes32 root;
        uint32 leafCount;
        uint64 anchoredAt;
    }

    mapping(uint256 => Batch) public batches;
    uint256 public batchCount;

    event BatchAnchored(uint256 indexed batchId, bytes32 root, uint32 leafCount);

    error EmptyBatch();
    error UnknownBatch(uint256 batchId);

    function anchor(bytes32 root, uint32 leafCount) external returns (uint256 batchId) {
        if (leafCount == 0) revert EmptyBatch();
        batchId = batchCount;
        batches[batchId] = Batch(root, leafCount, uint64(block.timestamp));
        batchCount = batchId + 1;
        emit BatchAnchored(batchId, root, leafCount);
    }

    /// @notice Checks that `leaf` was part of the batch committed under `batchId`.
    /// @dev Normally read with `eth_call`, which costs the caller nothing. `verify` is also the
    /// target of a real transaction in `benchmarks/measure_gas.py`: `view` is a Solidity level
    /// restriction and does not stop an account from calling the function in a transaction, so
    /// verification cost can be read from a receipt without adding a benchmark-only entry point
    /// to the contract.
    function verify(uint256 batchId, bytes32 leaf, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        Batch storage batch = batches[batchId];
        if (batch.leafCount == 0) revert UnknownBatch(batchId);
        return CustodyMerkle.processProof(leaf, proof) == batch.root;
    }
}
