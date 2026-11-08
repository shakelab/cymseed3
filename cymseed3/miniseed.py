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
MiniSEED 2 and 3 reading with libmseed.

Two levels of access share the same parser:

- :class:`MiniSeed` joins the records into contiguous segments, one
  list per source identifier, as libmseed does (:meth:`MiniSeed.read`,
  :meth:`MiniSeed.segments`);
- :func:`iter_records` returns the records one at a time
  (:class:`MSRecord`), with their header, extra headers and raw bytes,
  decoding the samples only on request.

Sources are paths (read through ``mmap``), ``bytes`` (e.g. a file
content or a SeedLink packet), ``bytearray``, ``memoryview``, ``mmap``
or any other contiguous buffer of bytes, and binary file objects; the
input is never copied.

Samples are returned as ``array.array`` in their native type (``'i'``
int32, ``'f'`` float32, ``'d'`` float64) or as ``bytes`` for text
records. With NumPy, ``numpy.frombuffer(data, dtype=data.typecode)``
gives an array without copies.

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

    Examples
    --------
    >>> ms = MiniSeed()
    >>> ms.read("day.mseed")  # doctest: +SKIP
    >>> for segment in ms.segments():  # doctest: +SKIP
    ...     print(segment.sid, segment.start_ns, len(segment.data))
    """

    def __init__(self) -> None:
        self._traces = _libmseed.TraceList()

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
        return sorted({fields[0] for fields in self._traces.segments()})

    def clear(self) -> None:
        """Remove all the segments."""
        self._traces.clear()

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


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


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


def _join(log: list) -> str:
    """Join the texts of libmseed messages."""
    return "; ".join(text for _, text in log)


def _warn(log: list, stacklevel: int = 3) -> None:
    """Issue the messages of libmseed as MiniSeedWarning."""
    for _, text in log:
        warnings.warn(text, MiniSeedWarning, stacklevel=stacklevel)
