"""Parser for Google Datastore/Firestore export files (LevelDB log format,
onestore_v3 EntityProto records), as produced by `gcloud firestore export`.

No dependency on google-cloud libraries: records are decoded with a minimal
generic protobuf walker, so a backup on disk can be used without credentials.
"""
from __future__ import annotations

import os
import struct
from typing import Any, Dict, Iterator, List

_BLOCK_SIZE = 32768

# onestore_v3 Property.Meaning value marking an embedded serialized EntityProto
_MEANING_ENTITY_PROTO = 19


def _leveldb_records(path: str) -> Iterator[bytes]:
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    current = b""
    while pos + 7 <= len(data):
        block_off = pos % _BLOCK_SIZE
        if _BLOCK_SIZE - block_off < 7:
            pos += _BLOCK_SIZE - block_off
            continue
        crc, length, rtype = struct.unpack("<IHB", data[pos:pos + 7])
        pos += 7
        payload = data[pos:pos + length]
        pos += length
        if rtype == 1:  # FULL
            yield payload
            current = b""
        elif rtype == 2:  # FIRST
            current = payload
        elif rtype == 3:  # MIDDLE
            current += payload
        elif rtype == 4:  # LAST
            current += payload
            yield current
            current = b""
        else:
            if length == 0 and crc == 0 and pos % _BLOCK_SIZE:
                pos += _BLOCK_SIZE - (pos % _BLOCK_SIZE)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _tag_len(tag: int) -> int:
    n = 1
    while tag >= 0x80:
        tag >>= 7
        n += 1
    return n


def _parse_fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield (field_number, wire_type, value); groups (wt 3) yield raw bytes."""
    pos = 0
    end = len(buf)
    while pos < end:
        tag, pos = _read_varint(buf, pos)
        fnum, wt = tag >> 3, tag & 7
        if wt == 0:
            val, pos = _read_varint(buf, pos)
            yield fnum, wt, val
        elif wt == 1:
            yield fnum, wt, struct.unpack("<d", buf[pos:pos + 8])[0]
            pos += 8
        elif wt == 2:
            ln, pos = _read_varint(buf, pos)
            yield fnum, wt, buf[pos:pos + ln]
            pos += ln
        elif wt == 3:  # start group: capture raw bytes until matching end group
            depth = 1
            start = pos
            while depth:
                t2, pos = _read_varint(buf, pos)
                w2 = t2 & 7
                if w2 == 3:
                    depth += 1
                elif w2 == 4:
                    depth -= 1
                    if depth == 0:
                        yield fnum, 3, buf[start:pos - _tag_len(t2)]
                        break
                elif w2 == 0:
                    _, pos = _read_varint(buf, pos)
                elif w2 == 1:
                    pos += 8
                elif w2 == 2:
                    ln, pos = _read_varint(buf, pos)
                    pos += ln
                elif w2 == 5:
                    pos += 4
        elif wt == 5:
            yield fnum, wt, struct.unpack("<f", buf[pos:pos + 4])[0]
            pos += 4
        else:
            raise ValueError(f"bad wire type {wt}")


def _decode_key(buf: bytes) -> List[Dict[str, Any]]:
    path: List[Dict[str, Any]] = []
    for fnum, wt, val in _parse_fields(buf):
        if fnum == 14 and wt == 2:  # Reference.path
            for f2, w2, v2 in _parse_fields(val):
                if f2 == 1 and w2 == 3:  # Path.Element group
                    elem: Dict[str, Any] = {}
                    for f3, _w3, v3 in _parse_fields(v2):
                        if f3 == 2:
                            elem["kind"] = v3.decode("utf-8", "replace")
                        elif f3 == 3:
                            elem["id"] = v3
                        elif f3 == 4:
                            elem["name"] = v3.decode("utf-8", "replace")
                    path.append(elem)
    return path


def _decode_property_value(buf: bytes, meaning: int | None) -> Any:
    out: Dict[str, Any] = {}
    for fnum, _wt, val in _parse_fields(buf):
        if fnum == 1:
            out["int"] = val
        elif fnum == 2:
            out["bool"] = bool(val)
        elif fnum == 3:
            if meaning == _MEANING_ENTITY_PROTO and isinstance(val, bytes):
                out["str"] = decode_entity(val)
            else:
                out["str"] = val.decode("utf-8", "replace") if isinstance(val, bytes) else val
        elif fnum == 4:
            out["double"] = val
        elif fnum == 12:
            out["ref"] = _decode_key(val) if isinstance(val, bytes) else str(val)
    if len(out) == 1:
        return next(iter(out.values()))
    return out or None


def _decode_property(buf: bytes) -> tuple[str | None, Any, bool]:
    name = None
    meaning = None
    multiple = False
    raw_val = None
    for fnum, _wt, val in _parse_fields(buf):
        if fnum == 1:
            meaning = val
        elif fnum == 3:
            name = val.decode("utf-8", "replace")
        elif fnum == 4:
            multiple = bool(val)
        elif fnum == 5:
            raw_val = val
    value = _decode_property_value(raw_val, meaning) if raw_val is not None else None
    return name, value, multiple


def decode_entity(buf: bytes) -> Dict[str, Any]:
    """Decode a serialized onestore_v3 EntityProto into a plain dict.

    Key path is stored under "__key__" as a list of {kind, id|name} elements.
    """
    ent: Dict[str, Any] = {}
    key_path: List[Dict[str, Any]] = []
    for fnum, wt, val in _parse_fields(buf):
        if fnum == 13 and wt == 2:
            key_path = _decode_key(val)
        elif fnum in (14, 15) and wt == 2:  # property / raw_property
            name, value, multiple = _decode_property(val)
            if name is None:
                continue
            if multiple:
                ent.setdefault(name, []).append(value)
            elif name in ent:
                prev = ent[name]
                if not isinstance(prev, list):
                    ent[name] = [prev]
                ent[name].append(value)
            else:
                ent[name] = value
    ent["__key__"] = key_path
    return ent


def load_export(export_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load every entity from an export directory (the one holding output-N files).

    Returns a mapping of entity kind -> list of entity dicts.
    """
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    files = sorted(f for f in os.listdir(export_dir) if f.startswith("output-"))
    if not files:
        raise FileNotFoundError(f"no output-N files found in {export_dir}")
    for fname in files:
        for rec in _leveldb_records(os.path.join(export_dir, fname)):
            if not rec:
                continue
            try:
                ent = decode_entity(rec)
            except Exception:
                continue
            kp = ent.get("__key__") or []
            kind = kp[-1]["kind"] if kp else "UNKNOWN"
            by_kind.setdefault(kind, []).append(ent)
    return by_kind
