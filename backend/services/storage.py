"""Where image files live.

Three operations — ``put``, ``delete``, ``url`` — and nothing above this layer
knows whether they land on a disk, S3 or R2. Image files are the only state in
this system that is not in Postgres, so they are also the only state a Postgres
backup does not cover; the mounted volume must be in the backup procedure.

Keys are content-addressed: the SHA-256 of the *re-encoded* bytes, fanned out
over two levels of hex prefix. Uploading the same photograph twice therefore
writes the same path twice instead of filling the volume with duplicates, and no
single directory ever holds the whole catalogue.
"""

import os
from pathlib import Path

from core.config import MEDIA_ROOT, MEDIA_URL_PREFIX


class StorageKeyRejected(Exception):
    """The key would write outside the storage root."""


def image_key(digest: str, size: str, extension: str) -> str:
    """``ab/cd/abcdef...-full.png`` — the path for one derivative."""
    return f"{digest[:2]}/{digest[2:4]}/{digest}-{size}.{extension}"


class LocalStorage:
    """Files on a mounted volume. The development and single-server answer."""

    def __init__(self, root: Path | str = MEDIA_ROOT, url_prefix: str = MEDIA_URL_PREFIX):
        self.root = Path(root)
        self.url_prefix = url_prefix.rstrip("/")

    def _resolve(self, key: str) -> Path:
        """Refuse anything that leaves the root.

        Keys are hashes today and cannot contain a traversal — which is the
        moment to add this, not after some later caller starts passing a name
        the operator typed.
        """
        if key.startswith("/") or key.startswith("\\"):
            raise StorageKeyRejected(key)
        root = self.root.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise StorageKeyRejected(key)
        return target

    def put(self, key: str, data: bytes) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Written to a temporary name and moved into place, so a reader never
        # sees a half-written image if the process dies mid-write.
        staging = target.with_name(target.name + ".part")
        staging.write_bytes(data)
        os.replace(staging, target)
        return self.url(key)

    def delete(self, key: str) -> None:
        # Missing is success. Cleanup runs after partial failures, where some
        # derivatives exist and some never did.
        self._resolve(key).unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return f"{self.url_prefix}/{key}"


storage = LocalStorage()
