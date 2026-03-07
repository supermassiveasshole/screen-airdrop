"""Restore payload bytes back to files/directories."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tarfile

from screen_airdrop.common.errors import E3001, E3002, ScreenAirdropError
from screen_airdrop.common.manifest import Manifest


def restore_payload(payload: bytes, manifest: Manifest, output_dir: str) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    if digest != manifest.payload_sha256:
        raise ScreenAirdropError(E3001, "payload sha256 mismatch")

    if manifest.compress == "gzip":
        try:
            tar_bytes = gzip.decompress(payload)
        except Exception as exc:
            raise ScreenAirdropError(E3002, "gzip decompress failed: {0}".format(exc))
    elif manifest.compress == "none":
        tar_bytes = payload
    else:
        raise ScreenAirdropError(E3002, "unsupported compression: {0}".format(manifest.compress))

    os.makedirs(output_dir, exist_ok=True)

    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
            tf.extractall(path=output_dir)
    except Exception as exc:
        raise ScreenAirdropError(E3002, "tar extract failed: {0}".format(exc))

    return os.path.join(output_dir, manifest.input_root_name)
