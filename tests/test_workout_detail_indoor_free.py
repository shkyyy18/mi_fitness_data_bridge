"""Per-second records for indoor running (proto 3) and free training (proto 8). Synthetic blobs only."""

from __future__ import annotations

import struct

import pytest

from mi_fitness_mcp.adapters.fds import (
    SUPPORTED_RECORD_PROTO_TYPES,
    TYPE_CADENCE,
    TYPE_CALORIES,
    TYPE_DISTANCE,
    TYPE_HR,
    TYPE_PACE,
    FdsParseError,
    parse_sport_record,
)

REPORT_TIME = 1791559380


def _header(version: int, proto_type: int, data_valid: bytes) -> bytes:
    return struct.pack("<IBBB", REPORT_TIME, 8, version, proto_type) + b"\x00" + data_valid


def _indoor_run_v6(records: list[tuple[int, int, int, int]]) -> bytes:
    # v6 channels by position: calories/hr/distance/stride/landing_impact/touchdown_ratio/cadence/pace.
    # landing impact exists without a high value (nibble 0x8), all others exist+high (0xC).
    blob = _header(6, 3, bytes((0xCC, 0xCC, 0x8C, 0xCC)))
    body = struct.pack("<II", len(records), REPORT_TIME)  # no pause-init block for indoor running
    body += b"\x00" + b"\x00" * 4  # IT summary: 41 (v2, 1 B) + 43 (v4, 4 B)
    for hr, dist_dm, cadence, pace in records:
        body += bytes(((3 << 4) | 1, hr, dist_dm, 80))  # calories / hr / distance / stride
        body += struct.pack("<I", (42 << 26) | 0x3FF)  # landing impact (no high value)
        body += bytes((30, cadence)) + struct.pack("<H", pace)
    return blob + body


def test_supported_proto_types_include_indoor_run_and_free_training():
    assert {3, 8, 12, 16} <= SUPPORTED_RECORD_PROTO_TYPES
    assert {1, 2, 4, 5, 15, 22, 23} <= SUPPORTED_RECORD_PROTO_TYPES


def test_indoor_run_v6_roundtrip():
    blob = _indoor_run_v6([(120, 15, 114, 524), (131, 16, 116, 520)])
    assert len(blob) == 12 + 8 + 5 + 2 * 12  # header + segment head + IT summary + 12 B per record

    segments = parse_sport_record(blob, 3)
    assert len(segments) == 1
    start, samples = segments[0]
    assert start == REPORT_TIME
    assert [s[TYPE_HR] for s in samples] == [120, 131]
    assert [s[TYPE_DISTANCE] for s in samples] == [15, 16]
    assert [s[TYPE_CADENCE] for s in samples] == [114, 116]
    assert [s[TYPE_PACE] for s in samples] == [524, 520]
    assert samples[0][TYPE_CALORIES] == 3
    assert 44 not in samples[0]  # exists but carries no high value


def test_indoor_run_unknown_version_is_skipped():
    # Only versions with a known dataValid length are parsed; others are skipped, not guessed.
    blob = _header(5, 3, bytes(3)) + struct.pack("<II", 0, REPORT_TIME)
    assert parse_sport_record(blob, 3) == []


def test_indoor_run_truncated_blob_is_rejected():
    with pytest.raises(FdsParseError, match="sample count"):
        parse_sport_record(_indoor_run_v6([(120, 15, 114, 524)])[:-1], 3)


@pytest.mark.parametrize("proto_type", [8, 12, 16])
@pytest.mark.parametrize("version", [3, 4, 5])
def test_free_training_supported_versions_roundtrip(proto_type, version):
    # hr/calories/spo2/stress; spo2 and stress exist without a high value.
    blob = _header(version, proto_type, bytes((0xCC, 0x88)))
    body = struct.pack("<II", 3, REPORT_TIME) + b"\x00"  # IT state
    if version >= 4:
        body += struct.pack("<I", 123)  # total duration
    if version >= 5:
        body += struct.pack("<HHH", 4, 5, 6)  # action times, weight, ID
    for hr in (98, 104, 117):
        body += bytes((hr, 2, 97, 40))
    segments = parse_sport_record(blob + body, proto_type)
    assert len(segments) == 1
    _, samples = segments[0]
    assert [s[TYPE_HR] for s in samples] == [98, 104, 117]
    assert samples[0][TYPE_CALORIES] == 2
    assert 38 not in samples[0] and 39 not in samples[0]


def test_free_training_one_dimension_versions_are_skipped():
    # v1/v2 use a one-dimension layout that is not implemented.
    blob = _header(2, 8, bytes(1)) + struct.pack("<II", 0, REPORT_TIME)
    assert parse_sport_record(blob, 8) == []


@pytest.mark.parametrize("version", [1, 2])
def test_indoor_run_early_versions_roundtrip(version):
    # Three channels occupy three nibbles; the final nibble is padding.
    blob = _header(version, 3, bytes((0xCC, 0xC0)))
    body = struct.pack("<II", 2, REPORT_TIME)
    if version == 2:
        body += b"\x00"  # IT state starts at v2
    body += bytes((0x31, 120, 15, 0x42, 131, 16))
    assert parse_sport_record(blob + body, 3) == [
        (REPORT_TIME, [
            {TYPE_CALORIES: 3, TYPE_HR: 120, TYPE_DISTANCE: 15},
            {TYPE_CALORIES: 4, TYPE_HR: 131, TYPE_DISTANCE: 16},
        ])
    ]
