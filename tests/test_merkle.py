import pytest

from parcelproof import merkle
from parcelproof.events import keccak256


def leaves(count: int) -> list[bytes]:
    return [keccak256(f"leaf-{i}".encode()) for i in range(count)]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 31, 64, 100])
def test_every_leaf_verifies(count):
    batch = leaves(count)
    expected = merkle.root(batch)
    for index in range(count):
        assert merkle.verify(batch[index], merkle.proof(batch, index), expected)


def test_single_leaf_root_is_the_leaf():
    batch = leaves(1)
    assert merkle.root(batch) == batch[0]
    assert merkle.proof(batch, 0) == []


def test_hash_pair_is_commutative():
    a, b = leaves(2)
    assert merkle.hash_pair(a, b) == merkle.hash_pair(b, a)


def test_tampered_leaf_fails_verification():
    batch = leaves(8)
    path = merkle.proof(batch, 3)
    assert not merkle.verify(keccak256(b"not-the-leaf"), path, merkle.root(batch))


def test_editing_a_sibling_invalidates_the_proof():
    """Tamper evidence is batch wide: changing any leaf changes the root, so proofs for the
    other leaves in the batch stop folding to the anchored value."""
    batch = leaves(8)
    anchored = merkle.root(batch)
    path = merkle.proof(batch, 3)
    assert merkle.verify(batch[3], path, anchored)

    edited = list(batch)
    edited[6] = keccak256(b"edited")
    assert not merkle.verify(batch[3], merkle.proof(edited, 3), anchored)


def test_promotion_not_duplication_for_odd_levels():
    """If an odd level duplicated its last node instead of promoting it, these two leaf sets
    would produce the same root, and a batch could be extended without changing its commitment."""
    three = leaves(3)
    four = [*three, three[2]]
    assert merkle.root(three) != merkle.root(four)


def test_odd_level_promotes_last_node_unchanged():
    batch = leaves(3)
    level_one = merkle.levels(batch)[1]
    assert level_one == [merkle.hash_pair(batch[0], batch[1]), batch[2]]


def test_proof_length_tracks_tree_depth():
    """Proof size grows with log2 of the batch, which is the cost side of large batches."""
    assert len(merkle.proof(leaves(1), 0)) == 0
    assert len(merkle.proof(leaves(2), 0)) == 1
    assert len(merkle.proof(leaves(256), 0)) == 8
    assert len(merkle.proof(leaves(1024), 0)) == 10


def test_truncated_proof_fails():
    batch = leaves(16)
    path = merkle.proof(batch, 5)
    assert not merkle.verify(batch[5], path[:-1], merkle.root(batch))


def test_reordered_proof_fails():
    batch = leaves(16)
    path = merkle.proof(batch, 5)
    reordered = [path[1], path[0], *path[2:]]
    assert not merkle.verify(batch[5], reordered, merkle.root(batch))


def test_empty_tree_is_rejected():
    with pytest.raises(ValueError, match="zero leaves"):
        merkle.root([])


def test_out_of_range_index_is_rejected():
    with pytest.raises(IndexError):
        merkle.proof(leaves(4), 4)
