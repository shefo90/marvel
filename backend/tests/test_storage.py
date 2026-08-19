"""The file store behind uploaded imagery.

A thin interface — ``put`` / ``delete`` / ``url`` — because image files are the
one piece of state that does not live in Postgres, and moving them to S3 or R2
later should be a config change rather than a rewrite. Nothing above this layer
knows what a filesystem is.
"""

import pytest

from services.storage import LocalStorage, StorageKeyRejected, image_key


def _store(tmp_path) -> LocalStorage:
    return LocalStorage(root=tmp_path, url_prefix="/media")


def test_a_stored_file_is_readable_back(tmp_path):
    store = _store(tmp_path)

    store.put("ab/cd/abcd-full.png", b"pixels")

    assert (tmp_path / "ab" / "cd" / "abcd-full.png").read_bytes() == b"pixels"


def test_put_returns_the_url_the_browser_will_use(tmp_path):
    store = _store(tmp_path)

    url = store.put("ab/cd/abcd-full.png", b"pixels")

    assert url == "/media/ab/cd/abcd-full.png"


def test_storing_the_same_key_twice_is_not_an_error(tmp_path):
    """Content-addressed keys mean re-uploading the same photo lands on the same
    path. That has to be a no-op, not a crash."""
    store = _store(tmp_path)
    store.put("ab/cd/abcd-full.png", b"pixels")

    store.put("ab/cd/abcd-full.png", b"pixels")

    assert (tmp_path / "ab" / "cd" / "abcd-full.png").read_bytes() == b"pixels"


def test_delete_removes_the_file(tmp_path):
    store = _store(tmp_path)
    store.put("ab/cd/abcd-full.png", b"pixels")

    store.delete("ab/cd/abcd-full.png")

    assert not (tmp_path / "ab" / "cd" / "abcd-full.png").exists()


def test_deleting_something_that_is_not_there_is_not_an_error(tmp_path):
    """Cleanup runs after a partial failure, where some derivatives exist and
    some do not. Raising there would turn a tidy-up into a second failure."""
    _store(tmp_path).delete("ab/cd/never-written.png")


@pytest.mark.parametrize(
    "key",
    ["../escape.png", "ab/../../escape.png", "/absolute.png", "ab/cd/../../../x.png"],
)
def test_a_key_that_climbs_out_of_the_root_is_refused(tmp_path, key):
    """Keys are hashes today, so nothing can currently reach here — which is
    exactly when to put the guard in, rather than after something else starts
    calling it with a user-supplied name."""
    with pytest.raises(StorageKeyRejected):
        _store(tmp_path).put(key, b"pixels")


def test_the_key_is_derived_from_the_content_hash():
    key = image_key("abcdef0123456789", "full", "png")

    assert key == "ab/cd/abcdef0123456789-full.png"


def test_keys_fan_out_so_one_directory_never_holds_every_image():
    """Two levels of hex prefix: 65,536 directories, so no single directory ends
    up with a hundred thousand entries."""
    first = image_key("00ff1111", "full", "png")
    second = image_key("ff001111", "full", "png")

    assert first.split("/")[:2] != second.split("/")[:2]
