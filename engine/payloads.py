"""Lossless, bounded storage encoding for large model-call JSON bodies.

The logical value remains the exact original UTF-8 string. Compressed bodies
are SQLite BLOBs with a versioned marker, length and SHA-256, not summaries.
No external file is needed to restore a database containing these records.
"""
from __future__ import annotations

import hashlib
import sqlite3
import struct
import zlib
from typing import Any


MAGIC = b"\x89AEJSON\r\n"
VERSION = 1
HEADER_SIZE = len(MAGIC) + 1 + 8 + 32
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MIN_COMPRESS_BYTES = 1024


class PayloadIntegrityError(ValueError):
    """A stored model body is corrupt, oversized, or uses an unknown format."""


def pack_payload(value: str | None) -> str | bytes | None:
    """Compress only when the complete framed result saves at least 10%."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("model payload must be a string or None")
    original = value.encode("utf-8")
    # Large existing bodies stay plain: compression must not impose a new
    # content limit on historically supported calls.
    if not MIN_COMPRESS_BYTES <= len(original) <= MAX_PAYLOAD_BYTES:
        return value
    packed = (MAGIC + bytes([VERSION]) + struct.pack(">Q", len(original))
              + hashlib.sha256(original).digest() + zlib.compress(original, 6))
    return packed if len(packed) <= len(original) * 0.9 else value


def unpack_payload(value: Any) -> Any:
    """Return a logical value; reject a broken encoded body without fallback."""
    if not isinstance(value, bytes) or not value.startswith(MAGIC):
        return value
    if len(value) < HEADER_SIZE or value[len(MAGIC)] != VERSION:
        raise PayloadIntegrityError("unsupported or truncated model payload")
    length = struct.unpack(">Q", value[len(MAGIC) + 1:len(MAGIC) + 9])[0]
    if length > MAX_PAYLOAD_BYTES:
        raise PayloadIntegrityError("model payload exceeds the decode limit")
    expected = value[len(MAGIC) + 9:HEADER_SIZE]
    decoder = zlib.decompressobj()
    try:
        original = decoder.decompress(value[HEADER_SIZE:], length + 1)
    except zlib.error as exc:
        raise PayloadIntegrityError("invalid compressed model payload") from exc
    if (len(original) != length or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail
            or hashlib.sha256(original).digest() != expected):
        raise PayloadIntegrityError("model payload length or checksum mismatch")
    try:
        return original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PayloadIntegrityError("model payload is not UTF-8") from exc


def payload_row_factory(cursor: sqlite3.Cursor, row: tuple) -> sqlite3.Row:
    """Preserve SQLite Row's API while decoding any encoded returned bodies.

    Decode values, rather than column names, so aliases and joined queries
    behave identically. Other BLOB values remain untouched.
    """
    return sqlite3.Row(cursor, tuple(unpack_payload(value) for value in row))


def configure_payload_reads(connection: sqlite3.Connection) -> None:
    connection.row_factory = payload_row_factory
