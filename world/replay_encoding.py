"""Canonical reference fragments avoid repeatedly decoding recorded prompts."""
from collections.abc import Mapping
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ReferenceBytes:
    encoded: bytes
    ascii_size: int
    root: str | None
    metadata: bytes = b""

    def __len__(self):
        # Include the small descriptor as well as both retained byte strings.
        return len(self.encoded) + len(self.metadata) + 256


class _CallFields(Mapping):
    def __init__(self, reference):
        self.reference = reference
        self.metadata = json.loads(reference.data.metadata)

    def __getitem__(self, key):
        if key not in self.metadata["fields"]:
            raise KeyError(key)
        if key in self.metadata["values"]:
            return self.metadata["values"][key]
        return self.reference.decoded()["llm_call"][key]

    def __iter__(self):
        return iter(self.metadata["fields"])

    def __len__(self):
        return len(self.metadata["fields"])


class CanonicalReference(Mapping):
    """Immutable canonical bytes with an optional, ephemeral inspection view."""

    def __init__(self, data):
        self.data = data
        self._decoded = None

    def decoded(self):
        if self._decoded is None:
            self._decoded = json.loads(self.data.encoded)
        return self._decoded

    def __getitem__(self, key):
        if self.data.root is None:
            return self.decoded()[key]
        if key != self.data.root:
            raise KeyError(key)
        if self.data.metadata:
            return _CallFields(self)
        return self.decoded()[key]

    def __iter__(self):
        return iter(self.decoded() if self.data.root is None else (self.data.root,))

    def __len__(self):
        return len(self.decoded()) if self.data.root is None else 1


def contains_reference(value, active=None):
    """Fallback for standalone storage callers without a tracked input record."""
    if isinstance(value, CanonicalReference):
        return True
    if isinstance(value, (dict, list, tuple)):
        active = set() if active is None else active
        identity = id(value)
        if identity in active:
            raise ValueError("Circular reference detected")
        active.add(identity)
        try:
            items = value.values() if isinstance(value, dict) else value
            return any(contains_reference(item, active) for item in items)
        finally:
            active.remove(identity)
    return False


def fragment_chunks(value, *, exact, measure_ascii=False):
    """Emit the existing JSON byte contract, inserting already canonical leaves.

    Plain records still use the native encoder. This walker handles only records
    containing references; their large, pre-encoded subtrees remain opaque.
    ASCII measurement yields integer charges for those leaves without copies.
    """
    encoder = json.JSONEncoder(sort_keys=exact, separators=(",", ":"),
                               ensure_ascii=not exact, allow_nan=not exact)
    active = set()

    def visit(item):
        if isinstance(item, CanonicalReference):
            if measure_ascii:
                yield item.data.ascii_size
            elif exact:
                yield item.data.encoded
            else:
                yield encoder.encode(item.decoded()).encode("utf-8")
        elif isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in active:
                raise ValueError("Circular reference detected")
            active.add(identity)
            try:
                if isinstance(item, dict):
                    yield b"{"
                    keys = sorted(item) if exact else item
                    for index, key in enumerate(keys):
                        if index:
                            yield b","
                        # The native encoder owns escaping and scalar-key rules.
                        encoded_key = (encoder.encode(key) if isinstance(key, str)
                                       else encoder.encode({key: None})[1:-6])
                        yield encoded_key.encode("utf-8")
                        yield b":"
                        yield from visit(item[key])
                    yield b"}"
                else:
                    yield b"["
                    for index, nested in enumerate(item):
                        if index:
                            yield b","
                        yield from visit(nested)
                    yield b"]"
            finally:
                active.remove(identity)
        else:
            yield encoder.encode(item).encode("utf-8")

    yield from visit(value)
