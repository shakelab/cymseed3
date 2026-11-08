# ****************************************************************************
# Copyright (C) 2019-2026, ShakeLab Developers.
# This file is part of cymseed3.
#
# cymseed3 is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# cymseed3 is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# with this download. If not, see <http://www.gnu.org/licenses/>
# ****************************************************************************
"""
Tests of MiniSEED writing: MiniSeed.add, MiniSeed.write, pack_records.

Written records are read back with the reader of cymseed3, which is
checked against libmseed in test_reading.py.
"""

from __future__ import annotations

import array
import glob
import math
import pathlib
import warnings

import pytest

from cymseed3 import (
    MiniSeed,
    MiniSeedError,
    MiniSeedWarning,
    iter_records,
    ns_from_string,
    pack_records,
)

# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(glob.glob(str(ROOT / "earthscope" / "libmseed-*"
                                       / "test" / "data"))[0])

CODES = ("XX", "TEST", "00", "HHZ")
SID = "FDSN:XX_TEST_00_H_H_Z"
START = ns_from_string("2026-11-02T10:15:30.123456789Z")
START_US = ns_from_string("2026-11-02T10:15:30.123457Z")


def _series(name, count):
    """Integer test series (as in the ShakeLab MiniSEED tests)."""
    if name == "linear":
        return [i - count // 2 for i in range(count)]
    if name == "triangle":
        return [abs((i % 200) - 100) * 1000 for i in range(count)]
    if name == "oscillator":
        return [int(1e6 * math.exp(-i / count) * math.sin(i / 7.0))
                for i in range(count)]
    if name == "fibonacci":
        values, a, b = [], 0, 1
        for _ in range(count):
            values.append(a)
            a, b = b, (a + b) % 2_000_000_000
        return values
    if name == "extremes":
        return [(2**31 - 1) if i % 2 else -(2**31) for i in range(count)]
    raise ValueError(name)


def _read_back(content):
    ms = MiniSeed()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ms.read(content)
    return ms.segments()


# ----------------------------------------------------------------------------
# Round trips
# ----------------------------------------------------------------------------

# Series and the integer encodings that can store them.
INTEGER_CASES = [
    ("linear", (1, 3, 10, 11)),
    ("triangle", (3, 10, 11)),
    ("oscillator", (3, 10, 11)),
    ("fibonacci", (3, 10)),
    ("extremes", (3,)),
]


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("reclen", [256, 512, 4096])
@pytest.mark.parametrize("name,encodings", INTEGER_CASES)
def test_round_trip_integers(name, encodings, reclen, version):
    """Integer series in every encoding that can store them."""
    values = _series(name, 2500)
    for encoding in encodings:
        ms = MiniSeed()
        ms.add(CODES, START, 100.0, values, encoding=encoding)
        content = ms.write(version=version, reclen=reclen)
        assert {r.encoding for r in iter_records(content)} == {encoding}
        assert all(r.reclen <= reclen for r in iter_records(content))
        (segment,) = _read_back(content)
        assert segment.data == array.array("i", values)
        assert segment.sid == SID
        assert segment.rate == 100.0
        assert segment.start_ns == (START if version == 3 else START_US)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("typecode,encoding", [("f", 4), ("d", 5)])
def test_round_trip_floats(typecode, encoding, version):
    """float32 and float64 samples keep their type and values."""
    values = array.array(typecode, [0.25, -1.5, 3.75, 1e6 + 0.5, -0.0,
                                    math.pi] * 300)
    ms = MiniSeed()
    ms.add(CODES, START, 3.0, values)
    content = ms.write(version=version)
    assert {r.encoding for r in iter_records(content)} == {encoding}
    (segment,) = _read_back(content)
    assert segment.sampletype == typecode
    assert segment.data == values


@pytest.mark.parametrize("version", [2, 3])
def test_round_trip_text(version):
    """Text records."""
    text = b"Log line 1\nLog line 2\n" * 100
    ms = MiniSeed()
    ms.add(("XX", "TEST", "", "LOG"), START, 0.0, text)
    content = ms.write(version=version)
    assert {r.encoding for r in iter_records(content)} == {0}
    records = list(iter_records(content))
    assert b"".join(record.data for record in records) == text
    # libmseed does not join records without a rate: one segment each,
    # all with the same start (their order is not defined).
    segments = _read_back(content)
    assert sorted(s.data for s in segments) == sorted(r.data
                                                      for r in records)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("name", sorted(
    path.name for path in DATA_DIR.glob("*")
    if path.name.startswith(("reference-", "testdata-3channel",
                             "testdata-oneseries", "testdata-encoding"))
))
def test_rewrite_libmseed_files(name, version):
    """Files of libmseed read, written and read again are unchanged."""
    original = MiniSeed()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MiniSeedWarning)
        original.read(DATA_DIR / name)
    segments = original.segments()
    if not segments:
        pytest.skip("no samples")
    rewritten = _read_back(original.write(version=version, reclen=4096))
    assert len(rewritten) == len(segments)
    for new, old in zip(rewritten, segments):
        assert (new.sid, new.rate, new.sampletype, new.data) == \
            (old.sid, old.rate, old.sampletype, old.data)
        # MiniSEED 2 stores microseconds.
        tolerance = 0 if version == 3 else 500
        assert abs(new.start_ns - old.start_ns) <= tolerance


def test_microseconds_in_later_records():
    """
    MiniSEED 2: each record keeps the exact start time (libmseed 3.5
    writes blockette 1001 when the period is not a multiple of 100 us).
    """
    ms = MiniSeed()
    ms.add(CODES, START_US, 3.0, list(range(2000)), encoding=3)
    content = ms.write(version=2, reclen=256)
    records = list(iter_records(content))
    assert len(records) > 10
    count = 0
    for record in records:
        expected = START_US + round(count * 1e9 / 3.0)
        assert abs(record.start_ns - expected) <= 500
        count += record.samplecnt


# ----------------------------------------------------------------------------
# Encodings
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("linear", 11), ("oscillator", 11), ("fibonacci", 10), ("extremes", 3),
])
def test_default_integer_encoding(name, expected):
    """STEIM2, STEIM1 or int32 from the sample differences."""
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, _series(name, 1000))
    assert {r.encoding for r in iter_records(ms.write())} == {expected}


def test_encoding_errors():
    """Encodings that cannot store the data."""
    ms = MiniSeed()
    with pytest.raises(MiniSeedError, match="cannot store float64"):
        ms.add(CODES, START, 100.0, [0.5], encoding=11)
    with pytest.raises(MiniSeedError, match="cannot store integer"):
        ms.add(CODES, START, 100.0, [1], encoding=4)
    with pytest.raises(TypeError):
        ms.add(CODES, START, 100.0, [1], encoding="steim2")
    ms.add(CODES, START, 100.0, [0, 40000], encoding=1)
    with pytest.raises(MiniSeedError, match="int16"):
        ms.write()
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, _series("fibonacci", 100), encoding=11)
    with pytest.raises(MiniSeedError):
        ms.write()


def test_encoding_per_sid():
    """The encoding belongs to the source identifier."""
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, [1, 2, 3], encoding=10)
    ms.add(CODES, START + 3 * 10**7, 100.0, [4, 5, 6])
    ms.add(("XX", "TEST", "00", "HHE"), START, 100.0, [1, 2, 3])
    with pytest.raises(MiniSeedError, match="differs"):
        ms.add(CODES, START + 6 * 10**7, 100.0, [7], encoding=11)
    encodings = {r.sid: r.encoding for r in iter_records(ms.write())}
    assert encodings == {SID: 10, "FDSN:XX_TEST_00_H_H_E": 11}
    ms.clear()
    ms.add(CODES, START, 100.0, [1, 2, 3], encoding=11)
    assert len(ms) == 1


# ----------------------------------------------------------------------------
# Data types
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("typecode,sampletype", [
    ("h", "i"), ("i", "i"), ("f", "f"), ("d", "d"),
])
def test_array_types(typecode, sampletype):
    """array.array of int16, int32, float32 and float64."""
    values = array.array(typecode, [1, -2, 3, 32767])
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, values)
    (segment,) = _read_back(ms.write())
    assert segment.sampletype == sampletype
    assert list(segment.data) == list(values)


def test_numpy_types():
    """NumPy arrays, also non-native views, are buffers."""
    np = pytest.importorskip("numpy")
    for dtype in ("int16", "int32", "float32", "float64"):
        values = np.arange(-50, 50).astype(dtype)
        ms = MiniSeed()
        ms.add(CODES, START, 100.0, values)
        (segment,) = _read_back(ms.write())
        assert np.array_equal(
            np.frombuffer(segment.data, dtype=segment.data.typecode),
            values)
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, np.arange(10, dtype="int64"))
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, np.arange(10)[::2]
                       .astype("int32")[::2])
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0,
                       np.zeros((2, 2), dtype="int32"))


def test_lists():
    """Lists of integers are int32, mixed lists float64."""
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, [1, 2.5, 3])
    (segment,) = _read_back(ms.write())
    assert segment.sampletype == "d"
    with pytest.raises(MiniSeedError, match="int32"):
        MiniSeed().add(CODES, START, 100.0, [2**31])
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, [1, "2"])
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, [True, False])


def test_unsupported_data():
    """Text as str, uint8 buffers and other objects."""
    with pytest.raises(TypeError, match="bytes"):
        MiniSeed().add(CODES, START, 0.0, "text")
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, array.array("B", [1, 2]))
    with pytest.raises(TypeError):
        MiniSeed().add(CODES, START, 100.0, 5)


def test_empty_data():
    """Adding no samples changes nothing."""
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, [])
    assert len(ms) == 0
    assert ms.write() == b""


# ----------------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------------


def test_joining_and_order():
    """Contiguous samples are joined; segments are written in order."""
    ms = MiniSeed()
    ms.add(("XX", "B", "", "HHZ"), START, 100.0, [1, 2, 3])
    ms.add(CODES, START + 10**9, 100.0, [4, 5])
    ms.add(CODES, START, 100.0, [1, 2, 3])
    ms.add(CODES, START + 3 * 10**7, 100.0, [4, 5, 6])
    assert len(ms) == 3
    records = list(iter_records(ms.write()))
    assert [(r.sid, r.samplecnt) for r in records] == [
        ("FDSN:XX_B__H_H_Z", 3), (SID, 6), (SID, 2)]
    ms2 = MiniSeed()
    ms2.read(ms.write())
    assert [s.data for s in ms2.segments(SID)] == [
        array.array("i", [1, 2, 3, 4, 5, 6]), array.array("i", [4, 5])]


def test_mixed_types_same_sid():
    """libmseed does not join samples of different types."""
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, [1, 2, 3])
    with pytest.raises(MiniSeedError):
        ms.add(CODES, START + 3 * 10**7, 100.0, [0.5])


def test_add_after_read():
    """Samples added after reading join the read segments."""
    ms = MiniSeed()
    ms.read(DATA_DIR / "reference-testdata-steim2.mseed3")
    (segment,) = ms.segments()
    ms.add(segment.sid, segment.end_ns + 25_000_000, segment.rate, [7, 8])
    (joined,) = ms.segments()
    assert joined.samplecnt == segment.samplecnt + 2


# ----------------------------------------------------------------------------
# Arguments and files
# ----------------------------------------------------------------------------


def test_argument_errors():
    """Invalid codes, times, rates and versions."""
    ms = MiniSeed()
    with pytest.raises(MiniSeedError):
        ms.add("IV.MODE..HNZ", START, 100.0, [1])
    with pytest.raises(TypeError):
        ms.add(CODES, 1.5, 100.0, [1])
    with pytest.raises(MiniSeedError, match="int64"):
        ms.add(CODES, 2**70, 100.0, [1])
    with pytest.raises(MiniSeedError):
        ms.add(CODES, START, -1.0, [1])
    with pytest.raises(TypeError):
        ms.add(CODES, START, "100", [1])
    with pytest.raises(MiniSeedError):
        ms.add(CODES, START, 100.0, [1], pubversion=300)
    ms.add(CODES, START, 100.0, [1])
    with pytest.raises(MiniSeedError, match="version"):
        ms.write(version=4)
    with pytest.raises(MiniSeedError, match="power of two"):
        ms.write(reclen=500)
    with pytest.raises(MiniSeedError):
        ms.write(version=3, reclen=20)
    with pytest.raises(TypeError):
        ms.write(reclen=512.0)
    assert ms.write(version=3, reclen=500)


def test_write_file(tmp_path):
    """Files are written once unless owrite is True."""
    path = tmp_path / "out.mseed"
    ms = MiniSeed()
    ms.add(CODES, START, 100.0, list(range(100)))
    assert ms.write(path) is None
    assert path.read_bytes() == ms.write()
    with pytest.raises(FileExistsError):
        ms.write(path)
    ms.write(str(path), version=3, owrite=True)
    assert next(iter_records(path)).format_version == 3
    with pytest.raises(TypeError):
        ms.write(1)


# ----------------------------------------------------------------------------
# pack_records
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("version", [2, 3])
def test_pack_records_fields(version):
    """Flags, publication version and extra headers in every record."""
    records = pack_records(
        CODES, START_US, 100.0, list(range(2000)), version=version,
        reclen=512, encoding=10, pubversion=2, flags=0x04,
        extra={"FDSN": {"Time": {"Quality": 80}}},
    )
    assert len(records) > 3
    offset = 0
    count = 0
    for record in records:
        assert record.offset == offset
        assert record.format_version == version
        assert record.encoding == 10
        assert record.pubversion == 2
        assert record.flags == 0x04
        assert record.extra["FDSN"]["Time"]["Quality"] == 80
        assert (record.crc is None) == (version == 2)
        assert record.start_ns == START_US + count * 10_000_000
        offset += record.reclen
        count += record.samplecnt
    assert count == 2000
    content = b"".join(record.raw for record in records)
    (segment,) = _read_back(content)
    assert segment.data == array.array("i", range(2000))


def test_pack_records_header_only():
    """Empty data give one record without samples."""
    (record,) = pack_records(CODES, START, 100.0, [], version=3,
                             extra={"FDSN": {"Event": {"InProgress": True}}})
    assert record.samplecnt == 0
    assert record.extra["FDSN"]["Event"]["InProgress"] is True


def test_pack_records_errors():
    """Invalid flags and extra headers."""
    with pytest.raises(MiniSeedError):
        pack_records(CODES, START, 100.0, [1], flags=256)
    with pytest.raises(TypeError):
        pack_records(CODES, START, 100.0, [1], extra="{}")
