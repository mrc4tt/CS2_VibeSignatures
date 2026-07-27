import hashlib


HASH_CHUNK_SIZE = 1024 * 1024


def hash_file(path) -> dict[str, str]:
    """Return lowercase MD5 and SHA-256 digests for one file."""
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            md5_hash.update(chunk)
            sha256_hash.update(chunk)
    return {"md5": md5_hash.hexdigest(), "sha256": sha256_hash.hexdigest()}
