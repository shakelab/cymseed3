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
Tests of MiniSEED reading: segments and records.

The reference (tests/data/libmseed_reference.json) is written by the
file readers of the bundled libmseed (ms3_readtracelist, ms3_readmsr_r)
on its own test files.
"""

from __future__ import annotations

import array
import dataclasses
import glob
import hashlib
import io
import json
import mmap
import os
import pathlib
import sys
import threading
import warnings

import pytest

from cymseed3 import (
    MiniSeed,
    MiniSeedError,
    MiniSeedWarning,
    MSRecord,
    Segment,
    codes_to_sid,
    iter_records,
    ns_from_string,
    ns_to_string,
    sid_to_codes,
)

# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(glob.glob(str(ROOT / "earthscope" / "libmseed-*"
                                       / "test" / "data"))[0])
REFERENCE = json.loads(
    (ROOT / "tests" / "data" / "libmseed_reference.json").read_text()
)["files"]

# Files on which libmseed reports warnings or errors.
NOISY = {
    "testdata-invalid-blockette-offsets.mseed2",
    "reference-testdata-steim1-LE.mseed2",
    "reference-testdata-steim2-LE.mseed2",
}

STEIM2 = DATA_DIR / "reference-testdata-steim2.mseed2"
STEIM2_V3 = DATA_DIR / "reference-testdata-steim2.mseed3"
TEXT = DATA_DIR / "reference-testdata-text.mseed2"
CHANNELS = DATA_DIR / "testdata-3channel-signal.mseed3"


def _digest(data):
    """SHA-256 of samples as in the reference (little-endian)."""
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    if sys.byteorder == "big":
        data = array.array(data.typecode, data)
        data.byteswap()
    return hashlib.sha256(data.tobytes()).hexdigest()


def _read(path, **kwargs):
    """Read a file, ignoring the expected warnings of noisy files."""
    ms = MiniSeed()
    with warnings.catch_warnings():
        if pathlib.Path(path).name in NOISY:
            warnings.simplefilter("ignore", MiniSeedWarning)
        ms.read(path, **kwargs)
    return ms


def _records(path, **kwargs):
    with warnings.catch_warnings():
        if pathlib.Path(path).name in NOISY:
            warnings.simplefilter("ignore", MiniSeedWarning)
        return list(iter_records(path, **kwargs))


# ----------------------------------------------------------------------------
# Conformance with libmseed
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_segments_match_libmseed(name):
    """Segments equal those of libmseed (records with samples only)."""
    expected = [s for s in REFERENCE[name]["segments"] if s["samplecnt"]]
    segments = _read(DATA_DIR / name).segments()
    assert len(segments) == len(expected)
    for segment, ref in zip(segments, expected):
        assert segment.sid == ref["sid"]
        assert segment.pubversion == ref["pubversion"]
        assert segment.start_ns == ref["start_ns"]
        assert segment.end_ns == ref["end_ns"]
        assert segment.rate == pytest.approx(ref["rate"], rel=1e-9)
        assert segment.sampletype == ref["sampletype"]
        assert segment.samplecnt == ref["samplecnt"]
        assert _digest(segment.data) == ref["sha256"]


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_records_match_libmseed(name):
    """Record headers equal those of the libmseed file reader."""
    expected = REFERENCE[name]["records"]
    records = _records(DATA_DIR / name)
    assert len(records) == len(expected)
    for record, ref in zip(records, expected):
        for key, value in ref.items():
            if key == "rate":
                assert record.rate == pytest.approx(value, rel=1e-9)
            else:
                assert getattr(record, key) == value, key


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_record_data_equal_segments(name):
    """The samples of the records, joined, equal those of the segments."""
    with warnings.catch_warnings():
        if name in NOISY:
            warnings.simplefilter("ignore", MiniSeedWarning)
        lazy = [record.data for record in _records(DATA_DIR / name)
                if record.samplecnt]
    unpacked = [record.data for record in
                _records(DATA_DIR / name, unpack=True) if record.samplecnt]
    assert lazy == unpacked
    total = sum(len(data) for data in lazy)
    assert total == sum(s.samplecnt for s in _read(DATA_DIR / name)
                        .segments())


def test_no_warnings_on_valid_files():
    """Valid files are read without warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for name in sorted(set(REFERENCE) - NOISY):
            MiniSeed().read(DATA_DIR / name)
            list(iter_records(DATA_DIR / name, unpack=True))


# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------


def _sources(path):
    content = path.read_bytes()
    return {
        "str": str(path),
        "path": path,
        "bytes": content,
        "bytearray": bytearray(content),
        "memoryview": memoryview(content),
        "array": array.array("B", content),
    }


@pytest.mark.parametrize("kind", ["str", "path", "bytes", "bytearray",
                                  "memoryview", "array"])
@pytest.mark.parametrize("path", [STEIM2, STEIM2_V3])
def test_sources(kind, path):
    """Paths and buffers give the same segments."""
    ms = MiniSeed()
    assert ms.read(_sources(path)[kind]) == len(REFERENCE[path.name]
                                                ["records"])
    assert ms.segments() == _read(path).segments()
    assert len(list(iter_records(_sources(path)[kind]))) == \
        len(REFERENCE[path.name]["records"])


def test_source_mmap_and_file():
    """mmap objects and binary files are accepted."""
    with open(STEIM2_V3, "rb") as fid:
        with mmap.mmap(fid.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            ms = MiniSeed()
            ms.read(mm)
            assert len(list(iter_records(mm))) == 4
        fid.seek(0)
        other = MiniSeed()
        other.read(fid)
    assert ms.segments() == other.segments()


def test_source_numpy():
    """NumPy byte arrays are buffers (no copy)."""
    np = pytest.importorskip("numpy")
    content = np.frombuffer(STEIM2.read_bytes(), dtype=np.uint8)
    ms = MiniSeed()
    ms.read(content)
    assert ms.segments() == _read(STEIM2).segments()


def test_source_errors(tmp_path):
    """Unsupported sources raise TypeError."""
    with pytest.raises(TypeError):
        MiniSeed().read(12)
    with pytest.raises(TypeError):
        MiniSeed().read(io.StringIO("text"))
    with pytest.raises(TypeError):
        MiniSeed().read(memoryview(bytes(range(16)))[::2])
    with pytest.raises(FileNotFoundError):
        MiniSeed().read(tmp_path / "missing.mseed")


def test_empty_sources(tmp_path):
    """Empty files and buffers give no records."""
    empty = tmp_path / "empty.mseed"
    empty.write_bytes(b"")
    for source in (empty, b"", bytearray()):
        ms = MiniSeed()
        assert ms.read(source) == 0
        assert len(ms) == 0
        assert list(iter_records(source)) == []


def test_buffer_not_modified():
    """Reading with CRC validation does not touch the buffer."""
    content = bytearray(STEIM2_V3.read_bytes())
    original = bytes(content)
    MiniSeed().read(content)
    list(iter_records(content, unpack=True))
    assert content == original


def test_stream_packet():
    """A single record (e.g. a SeedLink packet) is a valid source."""
    record = next(iter_records(STEIM2))
    packet = record.raw
    (single,) = iter_records(packet)
    assert single.raw == packet
    assert single.data == record.data
    ms = MiniSeed()
    assert ms.read(packet) == 1
    assert ms.segments()[0].data == record.data


# ----------------------------------------------------------------------------
# Invalid content
# ----------------------------------------------------------------------------


def test_invalid_crc():
    """Records with a wrong CRC are skipped unless not validated."""
    content = bytearray(STEIM2_V3.read_bytes())
    first = next(iter_records(STEIM2_V3))
    content[first.reclen - 1] ^= 0xFF
    with pytest.warns(MiniSeedWarning, match="invalid record at offset 0 "
                                             r"skipped \(507 bytes\): .*CRC"):
        records = list(iter_records(content))
    assert len(records) == 3
    assert records[0].offset == first.reclen
    with pytest.warns(MiniSeedWarning, match="CRC is invalid"):
        assert MiniSeed().read(content) == 3
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(list(iter_records(content, validate_crc=False))) == 4


def test_garbage_between_records():
    """Invalid bytes are skipped up to the next record."""
    records = list(iter_records(STEIM2))
    content = records[0].raw + b"garbage!" * 20 + b"".join(
        record.raw for record in records[1:])
    with pytest.warns(MiniSeedWarning, match="invalid data at offset 512 "
                                             r"skipped \(160 bytes\)"):
        found = list(iter_records(content))
    assert [r.raw for r in found] == [r.raw for r in records]
    assert found[1].offset == 512 + 160
    with pytest.warns(MiniSeedWarning, match="invalid data"):
        ms = MiniSeed()
        ms.read(content)
    assert ms.segments() == _read(STEIM2).segments()


def test_zero_padding_is_silent():
    """Zero bytes between and after records are skipped silently."""
    records = list(iter_records(STEIM2))
    content = (records[0].raw + bytes(1000)
               + b"".join(r.raw for r in records[1:]) + bytes(30))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(list(iter_records(content))) == len(records)


def test_trailing_and_truncated():
    """Nonzero trailing bytes and truncated records are reported."""
    content = STEIM2.read_bytes()
    with pytest.warns(MiniSeedWarning, match="trailing bytes"):
        assert len(list(iter_records(content + b"xyz"))) == 4
    with pytest.warns(MiniSeedWarning, match="incomplete record"):
        assert MiniSeed().read(STEIM2_V3.read_bytes()[:-10]) == 3


def test_libmseed_messages():
    """Warnings of libmseed carry the offset of the record."""
    path = DATA_DIR / "testdata-invalid-blockette-offsets.mseed2"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        MiniSeed().read(path)
    texts = [str(w.message) for w in caught
             if issubclass(w.category, MiniSeedWarning)]
    assert texts == [
        "invalid record at offset 0 skipped (512 bytes): "
        "FDSN:IU_COLA_00_L_H_Z: Blockette offset (40) is within the fixed "
        "header, impossible",
        "record at offset 512: FDSN:IU_COLA_00_L_H_Z: Offset to next "
        "blockette (40) is within current blockette ending at byte 64",
        "record at offset 1024: FDSN:IU_COLA_00_L_H_Z: Offset to next "
        "blockette (1000) from type 1001 is beyond record length",
    ]


def test_detection_record():
    """Records without samples are records, not segments."""
    path = DATA_DIR / "testdata-detection.record.mseed2"
    ms = MiniSeed()
    assert ms.read(path) == 1
    assert len(ms) == 0
    (record,) = iter_records(path)
    assert record.samplecnt == 0
    assert record.data == array.array("i")
    assert "Detection" in record.extra["FDSN"]["Event"]


# ----------------------------------------------------------------------------
# MiniSeed and Segment
# ----------------------------------------------------------------------------


def test_read_accumulates_and_clear():
    """Repeated reads join contiguous records; clear empties."""
    records = list(iter_records(STEIM2))
    ms = MiniSeed()
    ms.read(b"".join(r.raw for r in records[2:]))
    ms.read(b"".join(r.raw for r in records[:2]))
    assert ms.segments() == _read(STEIM2).segments()
    ms.clear()
    assert len(ms) == 0 and ms.segments() == [] and ms.sids() == []


def test_segments_selection():
    """sids() and patterns on the source identifiers."""
    ms = _read(CHANNELS)
    assert ms.sids() == ["FDSN:IU_COLA_00_L_H_1", "FDSN:IU_COLA_00_L_H_2",
                         "FDSN:IU_COLA_00_L_H_Z"]
    assert len(ms) == 3
    assert [s.codes[3] for s in ms.segments("*_L_H_[12]")] == ["LH1", "LH2"]
    assert ms.segments("FDSN:XX*") == []
    with pytest.raises(TypeError):
        ms.segments(1)


def test_segment():
    """Segments are read-only, with codes and sample count."""
    segment = _read(STEIM2).segments()[0]
    assert isinstance(segment, Segment)
    assert segment.codes == ("XX", "TEST", "", "BHZ")
    assert segment.samplecnt == len(segment.data) == 499
    assert segment.data.typecode == "i"
    assert segment.rate == 40.0
    assert segment.end_ns - segment.start_ns == 498 * 25_000_000
    with pytest.raises(dataclasses.FrozenInstanceError):
        segment.rate = 1.0
    assert "XX_TEST__B_H_Z" in repr(segment)


def test_text_segment():
    """Text records give bytes."""
    (segment,) = _read(TEXT).segments()
    assert segment.sampletype == "t"
    assert isinstance(segment.data, bytes)
    assert segment.data.startswith(b"I've seen things")
    assert segment.rate == 0.0


def test_info(capsys):
    """info() prints a summary."""
    _read(CHANNELS).info()
    out = capsys.readouterr().out
    assert out.startswith("MiniSeed(3 segments)")
    assert "FDSN:IU_COLA_00_L_H_Z" in out
    record = next(iter_records(CHANNELS))
    record.info()
    out = capsys.readouterr().out
    assert "clock locked" in out
    assert "Quality" in out


# ----------------------------------------------------------------------------
# MSRecord
# ----------------------------------------------------------------------------


def test_record_fields():
    """Offsets, raw bytes and the version-specific fields."""
    records = list(iter_records(STEIM2))
    offset = 0
    for record in records:
        assert isinstance(record, MSRecord)
        assert record.offset == offset
        assert len(record.raw) == record.reclen == 512
        assert record.crc is None
        offset += record.reclen
    assert STEIM2.read_bytes() == b"".join(r.raw for r in records)
    record = next(iter_records(STEIM2_V3))
    assert record.format_version == 3
    assert isinstance(record.crc, int)
    assert record.codes == ("XX", "TEST", "", "BHZ")
    assert "MSRecord(FDSN:XX_TEST__B_H_Z" in repr(record)


def test_record_extra_from_miniseed2():
    """MiniSEED 2 blockettes appear as FDSN extra headers."""
    record = next(iter_records(DATA_DIR / "testdata-3channel-signal.mseed2"))
    assert record.flags & 0x04
    assert record.extra == {"FDSN": {"Time": {"Quality": 100}}}
    assert next(iter_records(STEIM2)).extra == {}


def test_record_data_is_cached():
    """Samples are decoded once."""
    record = next(iter_records(STEIM2))
    assert record.data is record.data


def test_record_iterator_closes_files(tmp_path):
    """A partially consumed iterator releases the file."""
    path = tmp_path / "copy.mseed"
    path.write_bytes(STEIM2.read_bytes())
    iterator = iter_records(path)
    next(iterator)
    iterator.close()
    os.remove(path)


# ----------------------------------------------------------------------------
# Identifiers and times
# ----------------------------------------------------------------------------


def test_sid_and_codes():
    """Round trip between codes and source identifiers."""
    assert codes_to_sid(("IV", "MODE", "", "HNZ")) == "FDSN:IV_MODE__H_N_Z"
    assert codes_to_sid([" IV", "MODE ", "", "HNZ"]) == "FDSN:IV_MODE__H_N_Z"
    assert sid_to_codes("FDSN:IV_MODE__H_N_Z") == ("IV", "MODE", "", "HNZ")
    long_codes = ("XX", "S" * 24, "00", "HHZ")
    assert sid_to_codes(codes_to_sid(long_codes)) == long_codes


def test_sid_and_codes_errors():
    """Invalid identifiers and codes."""
    with pytest.raises(MiniSeedError):
        sid_to_codes("IV.MODE..HNZ")
    with pytest.raises(MiniSeedError):
        codes_to_sid(("XX", "S" * 40, "L" * 20, "HHZ"))
    with pytest.raises(TypeError):
        codes_to_sid("IV.MODE..HNZ")
    with pytest.raises(TypeError):
        codes_to_sid(("IV", "MODE", "HNZ"))
    with pytest.raises(TypeError):
        sid_to_codes(None)


def test_times():
    """Round trip between strings and nanoseconds."""
    text = "2026-11-02T10:15:30.123456789Z"
    time_ns = ns_from_string(text)
    assert time_ns == 1793614530123456789
    assert ns_to_string(time_ns) == text
    assert ns_to_string(1793614530000000000) == "2026-11-02T10:15:30Z"
    assert ns_to_string(1793614530500000000) == \
        "2026-11-02T10:15:30.500000Z"
    assert ns_from_string("2026-306T10:15:30") == 1793614530000000000
    assert ns_to_string(-1) == "1969-12-31T23:59:59.999999999Z"


def test_times_errors():
    """Invalid times."""
    with pytest.raises(MiniSeedError):
        ns_from_string("not a time")
    with pytest.raises(TypeError):
        ns_from_string(1)
    with pytest.raises(TypeError):
        ns_to_string(1.5)
    with pytest.raises(MiniSeedError):
        ns_to_string(2**64)


# ----------------------------------------------------------------------------
# Threads
# ----------------------------------------------------------------------------


def test_threads():
    """Reading in threads gives the same results."""
    expected = _read(CHANNELS).segments()
    results = []

    def work():
        ms = MiniSeed()
        ms.read(CHANNELS)
        results.append(ms.segments())

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [expected] * 4
