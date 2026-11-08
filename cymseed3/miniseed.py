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
MiniSEED 2 and 3 reading and writing with libmseed.

Two levels of access share the same parser and packer:

- :class:`MiniSeed` joins the records into contiguous segments, one
  list per source identifier, as libmseed does (:meth:`MiniSeed.read`,
  :meth:`MiniSeed.segments`), and writes segments
  (:meth:`MiniSeed.add`, :meth:`MiniSeed.write`);
- :func:`iter_records` returns the records one at a time
  (:class:`MSRecord`), with their header, extra headers and raw bytes,
  decoding the samples only on request; :func:`pack_records` packs one
  series of samples into records with chosen header fields.

Sources are paths (read through ``mmap``), ``bytes`` (e.g. a file
content or a SeedLink packet), ``bytearray``, ``memoryview``, ``mmap``
or any other contiguous buffer of bytes, and binary file objects; the
input is never copied.

Samples are returned as ``array.array`` in their native type (``'i'``
int32, ``'f'`` float32, ``'d'`` float64) or as ``bytes`` for text
records. With NumPy, ``numpy.frombuffer(data, dtype=data.typecode)``
gives an array without copies. Samples to write are int16, int32,
float32 or float64 buffers (NumPy arrays, ``array.array``,
``memoryview``), lists of numbers, or ``bytes`` for text.

Times are integer nanoseconds since 1970-01-01 UTC. Invalid records and
the warnings of libmseed are reported as :class:`MiniSeedWarning` and
the reading goes on; invalid arguments raise :class:`MiniSeedError`.

Notes
-----
libmseed translates the MiniSEED 2 fields with no direct MiniSEED 3
counterpart (sequence number, data quality, activity, I/O and quality
flags, blockettes 100, 200-201, 300-500 and 1001) into the extra
headers of the FDSN namespace (:attr:`MSRecord.extra`). The record
flags (:attr:`MSRecord.flags`) are those of MiniSEED 3: bit 0
calibration signals present, bit 1 time tag questionable, bit 2 clock
locked.
"""

from __future__ import annotations

import array
import contextlib
import fnmatch
import json
import mmap
import os
import warnings
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Union

from cymseed3 import _libmseed

__all__ = [
    "LIBMSEED_VERSION",
    "MSRecord",
    "MiniSeed",
    "MiniSeedError",
    "MiniSeedWarning",
    "Segment",
    "codes_to_sid",
    "iter_records",
    "ns_from_string",
    "pack_records",
    "ns_to_string",
    "sid_to_codes",
]

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

# Version of the bundled libmseed.
LIBMSEED_VERSION = _libmseed.LIBMSEED_VERSION_STR

# Encoding assumed by libmseed for MiniSEED 2 without blockette 1000.
_STEIM1 = 10

# Encodings that can be written, by sample type of libmseed.
_ENCODINGS = {"i": (1, 3, 10, 11), "f": (4,), "d": (5,), "t": (0,)}

# MiniSEED versions that can be written.
_VERSIONS = (2, 3)

# MiniSEED 3 record flags (MSRecord.flags).
_FLAG_NAMES = {
    0x01: "calibration signals present",
    0x02: "time tag questionable",
    0x04: "clock locked",
}

# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------


class MiniSeedError(ValueError):
    """Invalid argument or content that libmseed cannot handle."""


class MiniSeedWarning(UserWarning):
    """Invalid record skipped or warning of libmseed."""


# ----------------------------------------------------------------------------
# Identifiers and times
# ----------------------------------------------------------------------------


def sid_to_codes(sid: str) -> tuple[str, str, str, str]:
    """
    Split an FDSN source identifier into its four codes.

    Parameters
    ----------
    sid : str
        Source identifier, e.g. ``"FDSN:IV_MODE__H_N_Z"``.

    Returns
    -------
    tuple of str
        Network, station, location and channel codes; the channel is a
        SEED code when band, source and subsource have one character
        each (``"HNZ"``).

    Raises
    ------
    TypeError
        If ``sid`` is not a string.
    MiniSeedError
        If ``sid`` is not a valid FDSN source identifier.
    """
    if not isinstance(sid, str):
        raise TypeError(f"sid must be a string, not {type(sid).__name__}")
    codes, log = _libmseed.sid_to_codes(sid)
    if codes is None:
        raise MiniSeedError(_join(log) or f"invalid source identifier: {sid}")
    return codes


def codes_to_sid(codes: Any) -> str:
    """
    Build an FDSN source identifier from four codes.

    Parameters
    ----------
    codes : sequence of str
        Network, station, location and channel codes; the location may
        be empty. Surrounding spaces are removed.

    Returns
    -------
    str
        Source identifier, e.g. ``"FDSN:IV_MODE__H_N_Z"``.

    Raises
    ------
    TypeError
        If ``codes`` is not a sequence of four strings.
    MiniSeedError
        If the identifier cannot be built (e.g. longer than 63
        characters).
    """
    codes = _check_codes(codes)
    sid, log = _libmseed.codes_to_sid(*codes)
    if sid is None:
        raise MiniSeedError(
            _join(log) or f"invalid codes: {'.'.join(codes)}"
        )
    return sid


def ns_to_string(time_ns: int) -> str:
    """
    Format a time as an ISO 8601 string.

    Parameters
    ----------
    time_ns : int
        Nanoseconds since 1970-01-01 UTC.

    Returns
    -------
    str
        UTC time with ``Z``, with nanoseconds or microseconds only when
        needed, e.g. ``"2026-11-02T10:15:30.123456789Z"``.

    Raises
    ------
    TypeError
        If ``time_ns`` is not an integer.
    MiniSeedError
        If the time is out of the range of libmseed.
    """
    if not isinstance(time_ns, int) or isinstance(time_ns, bool):
        raise TypeError(
            f"time_ns must be an integer, not {type(time_ns).__name__}"
        )
    try:
        text, log = _libmseed.ns_to_string(time_ns)
    except OverflowError:
        raise MiniSeedError(f"time out of range: {time_ns}") from None
    if text is None:
        raise MiniSeedError(_join(log) or f"time out of range: {time_ns}")
    return text


def ns_from_string(text: str) -> int:
    """
    Parse a time string into nanoseconds.

    Parameters
    ----------
    text : str
        Time in one of the formats of libmseed: ISO 8601 with month and
        day or day of year (``"2026-11-02T10:15:30.5Z"``,
        ``"2026-306T10:15:30"``), SEED ordinal (``"2026,306,10:15:30"``)
        or epoch seconds. Times without zone are UTC.

    Returns
    -------
    int
        Nanoseconds since 1970-01-01 UTC.

    Raises
    ------
    TypeError
        If ``text`` is not a string.
    MiniSeedError
        If the string is not a valid time.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, not {type(text).__name__}")
    time_ns, log = _libmseed.ns_from_string(text)
    if time_ns is None:
        raise MiniSeedError(_join(log) or f"invalid time string: {text!r}")
    return time_ns


# ----------------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Segment:
    """
    Contiguous samples of one source identifier.

    Attributes
    ----------
    sid : str
        FDSN source identifier.
    pubversion : int
        Publication version (the highest of the joined records).
    start_ns : int
        Time of the first sample, in ns since 1970-01-01 UTC.
    end_ns : int
        Time of the last sample, in ns since 1970-01-01 UTC.
    rate : float
        Sampling rate in Hz (0 for text).
    sampletype : str
        ``"i"`` (int32), ``"f"`` (float32), ``"d"`` (float64) or ``"t"``
        (text).
    data : array.array or bytes
        Samples (``bytes`` for text).
    """

    sid: str
    pubversion: int
    start_ns: int
    end_ns: int
    rate: float
    sampletype: str
    data: Union[array.array, bytes]

    # -- properties -----------------------------------------------------

    @property
    def codes(self) -> tuple[str, str, str, str]:
        """Network, station, location and channel codes."""
        return sid_to_codes(self.sid)

    @property
    def samplecnt(self) -> int:
        """Number of samples."""
        return len(self.data)

    # -- summary --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Segment({self.sid}, {ns_to_string(self.start_ns)} - "
            f"{ns_to_string(self.end_ns)}, {self.rate:g} Hz, "
            f"{self.samplecnt} samples, type {self.sampletype!r})"
        )


class MiniSeed:
    """
    MiniSEED records joined into contiguous segments by libmseed.

    Records of the same source identifier are joined when they are
    contiguous within half a sample, as by libmseed; records without
    samples (e.g. detection or empty log records) are skipped.

    The encoding used to write a trace is set by :meth:`add` for its
    source identifier; traces without one (e.g. read from a file) are
    written with the default of their sample type.

    Examples
    --------
    >>> ms = MiniSeed()
    >>> ms.read("day.mseed")  # doctest: +SKIP
    >>> for segment in ms.segments():  # doctest: +SKIP
    ...     print(segment.sid, segment.start_ns, len(segment.data))
    >>> ms.add(("IV", "MODE", "", "HNZ"), 0, 100.0, [1, 2, 3])
    >>> content = ms.write(version=3)
    """

    def __init__(self) -> None:
        self._traces = _libmseed.TraceList()
        self._encodings: dict[str, int] = {}

    # -- reading --------------------------------------------------------

    def read(self, source: Any, *, validate_crc: bool = True) -> int:
        """
        Add the records of a MiniSEED 2 or 3 source.

        Parameters
        ----------
        source : str, path-like, bytes-like or binary file object
            Path (read through ``mmap``), content (``bytes``,
            ``bytearray``, ``memoryview``, ``mmap`` or another
            contiguous buffer of bytes) or file opened in binary mode.
        validate_crc : bool, optional
            If True (default), MiniSEED 3 records with a wrong CRC are
            skipped.

        Returns
        -------
        int
            Number of valid records read (with or without samples).

        Raises
        ------
        TypeError
            If ``source`` is not a supported source.

        Warns
        -----
        MiniSeedWarning
            For invalid data skipped, truncated records, nonzero
            trailing bytes and warnings of libmseed.
        """
        with _open_buffer(source) as buffer:
            count, log = self._traces.read(buffer, bool(validate_crc))
        _warn(log)
        return count

    # -- writing --------------------------------------------------------

    def add(self, codes: Any, start_ns: int, rate: float, data: Any, *,
            encoding: Optional[int] = None, pubversion: int = 1) -> None:
        """
        Add samples of one source identifier.

        Samples contiguous with those of a segment of the same source
        identifier are joined to it (copied by libmseed).

        Parameters
        ----------
        codes : str or sequence of str
            FDSN source identifier (``"FDSN:IV_MODE__H_N_Z"``) or the
            network, station, location and channel codes.
        start_ns : int
            Time of the first sample, in ns since 1970-01-01 UTC.
        rate : float
            Sampling rate in Hz (0 for text).
        data : buffer, list of numbers or bytes
            Samples: int16, int32, float32 or float64 buffer (NumPy
            array, ``array.array``, ``memoryview``), list of numbers
            (int32 if all integers, otherwise float64) or ``bytes`` and
            ``bytearray`` for text. int16 samples are stored as int32.
        encoding : int, optional
            Encoding of the source identifier when written: 1 (int16), 3
            (int32), 10 (STEIM1) or 11 (STEIM2) for integers, 4 for
            float32, 5 for float64, 0 for text. If None (default), the
            encoding set by an earlier call, otherwise the default of
            the data at writing: STEIM2 for integers whose differences
            fit in 30 bits, STEIM1 if they fit in 32 bits, otherwise
            int32; 4, 5 and 0 for the other types.
        pubversion : int, optional
            Publication version (0-255). Default is 1.

        Raises
        ------
        TypeError
            If an argument has a wrong type, or the samples a type that
            MiniSEED cannot store (e.g. int64).
        MiniSeedError
            If a value is invalid, the encoding does not match the data
            or differs from the one set for the same source identifier,
            or libmseed cannot join the samples (e.g. integers added to
            a float segment).
        """
        sid = _sid_of(codes)
        start_ns = _check_time(start_ns)
        rate = _check_rate(rate)
        pubversion = _check_byte("pubversion", pubversion)
        samples, sampletype = _samples_buffer(data)
        if encoding is not None:
            encoding = _check_encoding(encoding, sampletype)
            previous = self._encodings.get(sid)
            if previous is not None and previous != encoding:
                raise MiniSeedError(
                    f"{sid}: encoding {encoding} differs from the encoding "
                    f"{previous} set before"
                )
        ok, log = self._traces.add(sid, start_ns, rate, pubversion,
                                   sampletype, samples)
        if not ok:
            raise MiniSeedError(_join(log) or f"{sid}: samples not added")
        _warn(log)
        if encoding is not None:
            self._encodings[sid] = encoding

    def write(self, target: Any = None, *, version: int = 2,
              reclen: int = 512, owrite: bool = False) -> Optional[bytes]:
        """
        Pack all the segments into MiniSEED records.

        Segments are written sorted by source identifier and time, each
        with the encoding of its source identifier (see :meth:`add`).

        Parameters
        ----------
        target : str or path-like, optional
            Output file. If None (default), the records are returned.
        version : {2, 3}, optional
            MiniSEED version. Default is 2.
        reclen : int, optional
            Record length in bytes: a power of two from 128 to 131072 for
            MiniSEED 2, the maximum length for MiniSEED 3. Default is
            512.
        owrite : bool, optional
            If True, overwrite an existing file. Default is False.

        Returns
        -------
        bytes or None
            The records, or None if written to ``target``.

        Raises
        ------
        TypeError
            If an argument has a wrong type.
        MiniSeedError
            If the version or the record length is invalid, or libmseed
            cannot pack a segment (e.g. integer differences beyond 30
            bits with STEIM2).
        FileExistsError
            If ``target`` exists and ``owrite`` is False.

        Notes
        -----
        MiniSEED 2 stores times to the microsecond: libmseed rounds the
        nanoseconds (MiniSEED 3 keeps them).
        """
        version, reclen = _check_format(version, reclen)
        if target is not None:
            if not isinstance(target, (str, os.PathLike)):
                raise TypeError(
                    "target must be a path, not "
                    f"{type(target).__name__}"
                )
            if not owrite and os.path.exists(target):
                raise FileExistsError(f"File exists: {target}")
        content, log = self._traces.pack(dict(self._encodings), version,
                                         reclen)
        if content is None:
            raise MiniSeedError(_join(log) or "cannot pack the segments")
        _warn(log)
        if target is None:
            return content
        with open(target, "wb" if owrite else "xb") as fid:
            fid.write(content)
        return None

    # -- access ---------------------------------------------------------

    def segments(self, pattern: Optional[str] = None) -> list[Segment]:
        """
        Return the segments, sorted by source identifier and time.

        Parameters
        ----------
        pattern : str, optional
            Shell-style pattern of the source identifiers (``*``, ``?``,
            ``[...]``), e.g. ``"FDSN:IV_MODE__H_N_?"``. All segments if
            None.

        Returns
        -------
        list of Segment
            Segments with a copy of the samples.

        Raises
        ------
        TypeError
            If ``pattern`` is not a string.
        """
        if pattern is not None and not isinstance(pattern, str):
            raise TypeError(
                f"pattern must be a string, not {type(pattern).__name__}"
            )
        segments = [
            Segment(*fields) for fields in self._traces.segments()
            if pattern is None or fnmatch.fnmatchcase(fields[0], pattern)
        ]
        segments.sort(key=lambda segment: (segment.sid, segment.start_ns))
        return segments

    def sids(self) -> list[str]:
        """
        Return the source identifiers, sorted.

        Returns
        -------
        list of str
            One identifier per trace.
        """
        return sorted(self._traces.sids())

    def clear(self) -> None:
        """Remove all the segments and the encodings set by add()."""
        self._traces.clear()
        self._encodings.clear()

    # -- summary --------------------------------------------------------

    def __len__(self) -> int:
        return self._traces.count()

    def __repr__(self) -> str:
        return f"MiniSeed({len(self)} segments)"

    def info(self) -> None:
        """Print one line per segment."""
        print(repr(self))
        for segment in self.segments():
            print(
                f"{segment.sid:<28} {ns_to_string(segment.start_ns):<31} "
                f"{ns_to_string(segment.end_ns):<31} {segment.rate:>9g} Hz "
                f"{segment.samplecnt:>9} {segment.sampletype}"
            )


# ----------------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------------


class MSRecord:
    """
    One MiniSEED 2 or 3 record, as parsed by libmseed.

    Records are read with :func:`iter_records`. The attributes are read
    only; the samples are decoded at the first access to :attr:`data`.

    Attributes
    ----------
    offset : int
        Position of the record in the source, in bytes.
    reclen : int
        Record length in bytes.
    format_version : int
        MiniSEED version (2 or 3).
    sid : str
        FDSN source identifier.
    flags : int
        MiniSEED 3 record flags: bit 0 calibration signals present,
        bit 1 time tag questionable, bit 2 clock locked (translated
        from MiniSEED 2).
    start_ns : int
        Time of the first sample, in ns since 1970-01-01 UTC.
    end_ns : int
        Time of the last sample, in ns since 1970-01-01 UTC.
    rate : float
        Sampling rate in Hz (0 if the record has no time series).
    encoding : int
        Data encoding (also the legacy ones, e.g. 16 for CDSN); 10
        (STEIM1, as assumed by libmseed) for MiniSEED 2 records with
        samples and without blockette 1000.
    pubversion : int
        Publication version (from the data quality code in MiniSEED 2:
        R 1, D 2, Q 3, M 4).
    samplecnt : int
        Number of samples declared in the header.
    crc : int or None
        CRC-32C of a MiniSEED 3 record; None for MiniSEED 2.
    raw : bytes
        The record as stored in the source.
    """

    __slots__ = (
        "offset", "reclen", "format_version", "sid", "flags", "start_ns",
        "end_ns", "rate", "encoding", "pubversion", "samplecnt", "crc",
        "raw", "_extra", "_data",
    )

    def __init__(self, header: tuple, data: Any = None) -> None:
        (self.offset, self.reclen, self.format_version, self.sid,
         self.flags, self.start_ns, self.end_ns, self.rate, self.encoding,
         self.pubversion, self.samplecnt, crc, self._extra,
         self.raw) = header
        self.crc = crc if self.format_version == 3 else None
        if self.encoding < 0 and self.samplecnt:
            # No blockette 1000: libmseed decodes the samples as STEIM1.
            self.encoding = _STEIM1
        self._data = data

    # -- properties -----------------------------------------------------

    @property
    def codes(self) -> tuple[str, str, str, str]:
        """Network, station, location and channel codes."""
        return sid_to_codes(self.sid)

    @property
    def extra(self) -> dict:
        """
        Extra headers (FDSN and other namespaces) as a dictionary.

        For MiniSEED 2, the fields translated by libmseed (e.g.
        ``extra["FDSN"]["Sequence"]``, ``["DataQuality"]``,
        ``["Time"]["Quality"]``, ``["Flags"]``, ``["Event"]``).
        """
        if not self._extra:
            return {}
        return json.loads(self._extra)

    @property
    def data(self) -> Union[array.array, bytes]:
        """
        Samples of the record (``bytes`` for text).

        An empty int32 array for records without samples.

        Raises
        ------
        MiniSeedError
            If the samples cannot be decoded.
        """
        if self._data is None:
            data, log = _libmseed.unpack_record(self.raw)
            if data is None:
                raise MiniSeedError(
                    _join(log) or f"cannot decode the record at offset "
                    f"{self.offset}"
                )
            _warn(log)
            self._data = data
        return self._data

    # -- summary --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"MSRecord({self.sid}, {ns_to_string(self.start_ns)}, "
            f"{self.rate:g} Hz, {self.samplecnt} samples, "
            f"version {self.format_version}, {self.reclen} bytes)"
        )

    def info(self) -> None:
        """Print the header fields and the extra headers."""
        print(repr(self))
        flags = ", ".join(
            name for bit, name in _FLAG_NAMES.items() if self.flags & bit
        )
        fields = [
            ("offset", self.offset),
            ("record length", self.reclen),
            ("format version", self.format_version),
            ("source identifier", self.sid),
            ("start time", ns_to_string(self.start_ns)),
            ("end time", ns_to_string(self.end_ns)),
            ("sampling rate", f"{self.rate:g} Hz"),
            ("sample count", self.samplecnt),
            ("encoding", self.encoding),
            ("publication version", self.pubversion),
            ("flags", f"{self.flags:#04x}" + (f" ({flags})" if flags
                                              else "")),
            ("CRC", "-" if self.crc is None else f"{self.crc:#010x}"),
        ]
        for name, value in fields:
            print(f"{name:>20} : {value}")
        if self._extra:
            text = json.dumps(self.extra, indent=2)
            print(f"{'extra headers':>20} : " +
                  text.replace("\n", "\n" + " " * 23))


def iter_records(source: Any, *, unpack: bool = False,
                 validate_crc: bool = True) -> Iterator[MSRecord]:
    """
    Iterate over the records of a MiniSEED 2 or 3 source.

    Parameters
    ----------
    source : str, path-like, bytes-like or binary file object
        Path (read through ``mmap``), content (``bytes``,
        ``bytearray``, ``memoryview``, ``mmap`` or another contiguous
        buffer of bytes) or file opened in binary mode.
    unpack : bool, optional
        If True, decode the samples while reading; otherwise (default)
        at the first access to :attr:`MSRecord.data`.
    validate_crc : bool, optional
        If True (default), MiniSEED 3 records with a wrong CRC are
        skipped.

    Yields
    ------
    MSRecord
        The valid records, in the order of the source; also those
        without samples.

    Raises
    ------
    TypeError
        If ``source`` is not a supported source.

    Warns
    -----
    MiniSeedWarning
        For invalid data skipped, truncated records, nonzero trailing
        bytes and warnings of libmseed.
    """
    with _open_buffer(source) as buffer:
        scanner = _libmseed.Scanner(buffer, bool(unpack), bool(validate_crc))
        try:
            while True:
                header = scanner.next()
                _warn(scanner.messages, stacklevel=4)
                if header is None:
                    break
                data = scanner.data() if unpack else None
                yield MSRecord(header, data)
        finally:
            # Release the buffer before the mmap of a path is closed.
            del scanner


def pack_records(codes: Any, start_ns: int, rate: float, data: Any, *,
                 version: int = 2, reclen: int = 512,
                 encoding: Optional[int] = None, pubversion: int = 1,
                 flags: int = 0,
                 extra: Optional[dict] = None) -> list[MSRecord]:
    """
    Pack one series of samples into MiniSEED records.

    Unlike :meth:`MiniSeed.write`, the record header fields can be set:
    flags and extra headers are written in every record.

    Parameters
    ----------
    codes : str or sequence of str
        FDSN source identifier or the four codes.
    start_ns : int
        Time of the first sample, in ns since 1970-01-01 UTC.
    rate : float
        Sampling rate in Hz (0 for text).
    data : buffer, list of numbers or bytes
        Samples, as in :meth:`MiniSeed.add`; empty for a record with
        header only.
    version : {2, 3}, optional
        MiniSEED version. Default is 2.
    reclen : int, optional
        Record length in bytes (maximum length for MiniSEED 3). Default
        is 512.
    encoding : int, optional
        Encoding; the default of the data if None (see
        :meth:`MiniSeed.add`).
    pubversion : int, optional
        Publication version (0-255; in MiniSEED 2 the data quality code:
        1 R, 2 D, 3 Q, 4 M). Default is 1.
    flags : int, optional
        MiniSEED 3 record flags (0-255): bit 0 calibration signals
        present, bit 1 time tag questionable, bit 2 clock locked.
        Default is 0.
    extra : dict, optional
        Extra headers (FDSN namespace and others). For MiniSEED 2,
        libmseed writes the FDSN fields it knows as fixed header fields
        and blockettes (e.g. ``{"FDSN": {"Time": {"Quality": 100}}}``
        as blockette 1001).

    Returns
    -------
    list of MSRecord
        The records; their offsets are relative to the joined records
        (``b"".join(record.raw for record in records)``).

    Raises
    ------
    TypeError
        If an argument has a wrong type.
    MiniSeedError
        If a value is invalid, the encoding does not match the data or
        libmseed cannot pack the samples.

    Notes
    -----
    MiniSEED 2 stores times to the microsecond: libmseed rounds the
    nanoseconds (MiniSEED 3 keeps them).
    """
    sid = _sid_of(codes)
    start_ns = _check_time(start_ns)
    rate = _check_rate(rate)
    version, reclen = _check_format(version, reclen)
    pubversion = _check_byte("pubversion", pubversion)
    flags = _check_byte("flags", flags)
    samples, sampletype = _samples_buffer(data)
    encoding = (-1 if encoding is None
                else _check_encoding(encoding, sampletype))
    if extra is None:
        extra_json = b""
    elif isinstance(extra, dict):
        extra_json = json.dumps(extra, separators=(",", ":")).encode()
    else:
        raise TypeError(f"extra must be a dict, not {type(extra).__name__}")
    content, log = _libmseed.pack_samples(
        sid, start_ns, rate, pubversion, sampletype, samples, encoding,
        version, reclen, flags, extra_json,
    )
    if content is None:
        raise MiniSeedError(_join(log) or f"{sid}: samples not packed")
    _warn(log)
    return list(iter_records(content))


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _check_byte(name: str, value: Any) -> int:
    """Validate an integer from 0 to 255."""
    value = _check_int(name, value)
    if not 0 <= value <= 255:
        raise MiniSeedError(f"{name} must be from 0 to 255, not {value}")
    return value


def _check_encoding(encoding: Any, sampletype: str) -> int:
    """Validate an encoding for a sample type."""
    encoding = _check_int("encoding", encoding)
    allowed = _ENCODINGS[sampletype]
    if encoding not in allowed:
        kind = {"i": "integer", "f": "float32", "d": "float64",
                "t": "text"}[sampletype]
        raise MiniSeedError(
            f"encoding {encoding} cannot store {kind} samples (allowed: "
            f"{', '.join(str(code) for code in allowed)})"
        )
    return encoding


def _check_format(version: Any, reclen: Any) -> tuple[int, int]:
    """Validate the MiniSEED version and the record length."""
    version = _check_int("version", version)
    reclen = _check_int("reclen", reclen)
    if version not in _VERSIONS:
        raise MiniSeedError(f"MiniSEED version must be 2 or 3, not "
                            f"{version}")
    if version == 2 and (reclen < 128 or reclen > 131072
                         or reclen & (reclen - 1)):
        raise MiniSeedError(
            "MiniSEED 2 record length must be a power of two from 128 to "
            f"131072, not {reclen}"
        )
    if version == 3 and not 40 <= reclen <= 10485760:
        raise MiniSeedError(
            "MiniSEED 3 record length must be from 40 to 10485760, not "
            f"{reclen}"
        )
    return version, reclen


def _check_int(name: str, value: Any) -> int:
    """Validate an integer argument (not bool)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"{name} must be an integer, not {type(value).__name__}"
        )
    return value


def _check_time(start_ns: Any) -> int:
    """Validate a time in ns (signed 64-bit)."""
    start_ns = _check_int("start_ns", start_ns)
    if not -(2**63) < start_ns < 2**63:
        raise MiniSeedError(f"start_ns out of the int64 range: {start_ns}")
    return start_ns


def _check_rate(rate: Any) -> float:
    """Validate a sampling rate in Hz."""
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        raise TypeError(f"rate must be a number, not {type(rate).__name__}")
    rate = float(rate)
    if not 0.0 <= rate < float("inf"):
        raise MiniSeedError(f"rate must be finite and not negative, not "
                            f"{rate}")
    return rate


def _check_codes(codes: Any) -> tuple[str, str, str, str]:
    """Validate four codes and strip their spaces."""
    if isinstance(codes, str) or not hasattr(codes, "__len__"):
        raise TypeError("codes must be a sequence of four strings")
    if len(codes) != 4 or not all(isinstance(code, str) for code in codes):
        raise TypeError("codes must be a sequence of four strings")
    return tuple(code.strip() for code in codes)


@contextlib.contextmanager
def _open_buffer(source: Any) -> Iterator[Any]:
    """Yield a contiguous byte buffer of a source."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as fid:
            if os.fstat(fid.fileno()).st_size == 0:
                yield b""
                return
            with mmap.mmap(fid.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                yield mm
        return
    if hasattr(source, "read") and not isinstance(source, mmap.mmap):
        content = source.read()
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("the file must be opened in binary mode")
        yield content
        return
    try:
        view = memoryview(source)
    except TypeError:
        raise TypeError(
            "source must be a path, a bytes-like object or a binary file, "
            f"not {type(source).__name__}"
        ) from None
    with view:
        if not view.c_contiguous:
            raise TypeError("the source buffer must be contiguous")
        if view.format != "B" or view.ndim != 1:
            with view.cast("B") as flat:
                yield flat
        else:
            yield view


def _samples_buffer(data: Any) -> tuple[Any, str]:
    """
    Return the raw samples (contiguous bytes) and the libmseed sample
    type ('i', 'f', 'd' or 't') of data to write.
    """
    if isinstance(data, (bytes, bytearray)):
        return data, "t"
    if isinstance(data, str):
        raise TypeError("text samples must be bytes, not str")
    if isinstance(data, (list, tuple)):
        if all(isinstance(value, int) and not isinstance(value, bool)
               for value in data):
            try:
                values = array.array("i", data)
            except OverflowError:
                raise MiniSeedError(
                    "integer samples out of the int32 range"
                ) from None
            return memoryview(values).cast("B"), "i"
        if all(isinstance(value, (int, float))
               and not isinstance(value, bool) for value in data):
            return memoryview(array.array("d", data)).cast("B"), "d"
        raise TypeError("sample lists must hold numbers only")
    try:
        view = memoryview(data)
    except TypeError:
        raise TypeError(
            "data must be a buffer, a list of numbers or bytes, not "
            f"{type(data).__name__}"
        ) from None
    if view.ndim != 1 or not view.c_contiguous:
        raise TypeError("sample buffers must be one-dimensional and "
                        "contiguous")
    code = view.format.lstrip("@=")
    if code in ("h", "i", "l", "q") and view.itemsize == 2:
        return memoryview(array.array("i", view)).cast("B"), "i"
    if code in ("h", "i", "l", "q") and view.itemsize == 4:
        return view.cast("B"), "i"
    if code == "f" and view.itemsize == 4:
        return view.cast("B"), "f"
    if code == "d" and view.itemsize == 8:
        return view.cast("B"), "d"
    raise TypeError(
        f"unsupported sample type {view.format!r} (itemsize "
        f"{view.itemsize}): use int16, int32, float32, float64 or bytes"
    )


def _sid_of(codes: Any) -> str:
    """Return the source identifier of a sid or of four codes."""
    if isinstance(codes, str):
        sid_to_codes(codes)
        return codes
    return codes_to_sid(codes)


def _join(log: list) -> str:
    """Join the texts of libmseed messages."""
    return "; ".join(text for _, text in log)


def _warn(log: list, stacklevel: int = 3) -> None:
    """Issue the messages of libmseed as MiniSeedWarning."""
    for _, text in log:
        warnings.warn(text, MiniSeedWarning, stacklevel=stacklevel)
