// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {CustodyMerkle, MerkleAnchor, PerEventLog, PerEventStorage} from "../src/CustodyAnchor.sol";

/// @dev Reference tree builder, deliberately written independently of the Python implementation
/// in `src/parcelproof/merkle.py`. Two implementations that agree on the same roots and proofs
/// is the check that the tree shape is actually specified and not just consistent with itself.
/// Odd nodes are promoted to the next level rather than duplicated: duplicating the last leaf
/// makes two different leaf sets produce the same root.
contract ReferenceTree {
    function parentLevel(bytes32[] memory level) public pure returns (bytes32[] memory next) {
        uint256 width = (level.length + 1) / 2;
        next = new bytes32[](width);
        for (uint256 i = 0; i < width; ++i) {
            uint256 left = 2 * i;
            next[i] = left + 1 < level.length
                ? CustodyMerkle.hashPair(level[left], level[left + 1])
                : level[left];
        }
    }

    function root(bytes32[] memory leaves) public pure returns (bytes32) {
        bytes32[] memory level = leaves;
        while (level.length > 1) {
            level = parentLevel(level);
        }
        return level[0];
    }

    function proof(bytes32[] memory leaves, uint256 index)
        public
        pure
        returns (bytes32[] memory)
    {
        bytes32[] memory buffer = new bytes32[](256);
        uint256 depth;
        bytes32[] memory level = leaves;
        uint256 idx = index;
        while (level.length > 1) {
            uint256 sibling = idx ^ 1;
            if (sibling < level.length) {
                buffer[depth++] = level[sibling];
            }
            idx /= 2;
            level = parentLevel(level);
        }
        bytes32[] memory out = new bytes32[](depth);
        for (uint256 i = 0; i < depth; ++i) {
            out[i] = buffer[i];
        }
        return out;
    }
}

contract CustodyAnchorTest is Test {
    MerkleAnchor internal anchor;
    ReferenceTree internal tree;

    function setUp() public {
        anchor = new MerkleAnchor();
        tree = new ReferenceTree();
    }

    function _leaves(uint256 count) internal pure returns (bytes32[] memory leaves) {
        leaves = new bytes32[](count);
        for (uint256 i = 0; i < count; ++i) {
            leaves[i] = CustodyMerkle.hashLeaf(abi.encodePacked("custody-event-", i));
        }
    }

    function test_hashPairIsCommutative() public pure {
        bytes32 a = keccak256("a");
        bytes32 b = keccak256("b");
        assertEq(CustodyMerkle.hashPair(a, b), CustodyMerkle.hashPair(b, a));
    }

    function test_leafAndNodeHashingAreDomainSeparated() public pure {
        bytes32 a = keccak256("a");
        bytes32 b = keccak256("b");
        bytes32 node = CustodyMerkle.hashPair(a, b);
        assertTrue(node != CustodyMerkle.hashLeaf(abi.encodePacked(a, b)));
        assertTrue(node != CustodyMerkle.hashLeaf(abi.encodePacked(b, a)));
    }

    function test_singleLeafBatchRootIsTheLeaf() public {
        bytes32[] memory leaves = _leaves(1);
        uint256 batchId = anchor.anchor(leaves[0], 1);
        assertTrue(anchor.verify(batchId, leaves[0], new bytes32[](0)));
    }

    /// @dev Covers a power of two, an odd count, and a count that forces promotion on more
    /// than one level.
    function test_everyLeafVerifiesAcrossBatchShapes() public {
        uint256[5] memory sizes = [uint256(2), 3, 5, 7, 16];
        for (uint256 s = 0; s < sizes.length; ++s) {
            bytes32[] memory leaves = _leaves(sizes[s]);
            uint256 batchId = anchor.anchor(tree.root(leaves), uint32(sizes[s]));
            for (uint256 i = 0; i < leaves.length; ++i) {
                assertTrue(
                    anchor.verify(batchId, leaves[i], tree.proof(leaves, i)),
                    "valid proof rejected"
                );
            }
        }
    }

    function test_tamperedLeafFailsVerification() public {
        bytes32[] memory leaves = _leaves(8);
        uint256 batchId = anchor.anchor(tree.root(leaves), 8);
        bytes32[] memory validProof = tree.proof(leaves, 3);

        assertTrue(anchor.verify(batchId, leaves[3], validProof));
        bytes32 tampered = CustodyMerkle.hashLeaf("custody-event-3-but-edited");
        assertFalse(anchor.verify(batchId, tampered, validProof));
    }

    function test_proofFromAnotherBatchFailsVerification() public {
        bytes32[] memory first = _leaves(8);
        bytes32[] memory second = new bytes32[](8);
        for (uint256 i = 0; i < 8; ++i) {
            second[i] = CustodyMerkle.hashLeaf(abi.encodePacked("other-event-", i));
        }
        anchor.anchor(tree.root(first), 8);
        uint256 secondId = anchor.anchor(tree.root(second), 8);

        assertFalse(anchor.verify(secondId, first[3], tree.proof(first, 3)));
    }

    function test_truncatedProofFailsVerification() public {
        bytes32[] memory leaves = _leaves(8);
        uint256 batchId = anchor.anchor(tree.root(leaves), 8);
        bytes32[] memory full = tree.proof(leaves, 3);
        bytes32[] memory short = new bytes32[](full.length - 1);
        for (uint256 i = 0; i < short.length; ++i) {
            short[i] = full[i];
        }
        assertFalse(anchor.verify(batchId, leaves[3], short));
    }

    function test_batchIdsIncrementAndRecordLeafCount() public {
        assertEq(anchor.batchCount(), 0);
        assertEq(anchor.anchor(keccak256("r0"), 4), 0);
        assertEq(anchor.anchor(keccak256("r1"), 9), 1);
        assertEq(anchor.batchCount(), 2);

        (bytes32 root, uint32 leafCount,) = anchor.batches(1);
        assertEq(root, keccak256("r1"));
        assertEq(leafCount, 9);
    }

    function test_emptyBatchReverts() public {
        vm.expectRevert(MerkleAnchor.EmptyBatch.selector);
        anchor.anchor(keccak256("r"), 0);
    }

    function test_unknownBatchReverts() public {
        vm.expectRevert(abi.encodeWithSelector(MerkleAnchor.UnknownBatch.selector, 7));
        anchor.verify(7, keccak256("leaf"), new bytes32[](0));
    }

    function testFuzz_everyLeafVerifies(uint8 rawCount, uint256 rawIndex) public {
        uint256 count = uint256(rawCount) % 64 + 1;
        uint256 index = rawIndex % count;
        bytes32[] memory leaves = _leaves(count);
        // casting to 'uint32' is safe because `count` is a uint8 reduced modulo 64, so at most 64
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 batchId = anchor.anchor(tree.root(leaves), uint32(count));
        assertTrue(anchor.verify(batchId, leaves[index], tree.proof(leaves, index)));
    }

    function test_perEventStrategiesRecord() public {
        PerEventStorage storageStrategy = new PerEventStorage();
        bytes32 h = keccak256("event");
        storageStrategy.record(h);
        assertEq(storageStrategy.recordedAt(h), block.number);

        PerEventLog logStrategy = new PerEventLog();
        vm.expectEmit(true, false, false, false);
        emit PerEventLog.CustodyRecorded(h);
        logStrategy.record(h);
    }
}
