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
# cython: language_level=3, boundscheck=False, wraparound=False
"""
Low-level binding of libmseed (private).

The public interface is :mod:`cymseed3.miniseed`. This module only moves
data between libmseed and Python objects: it never raises for invalid
MiniSEED content, but returns the messages of libmseed as
``(level, text)`` pairs (level 1 warning, level 2 error), which the
public layer turns into warnings or exceptions.

Buffers are typed memoryviews (``bytes``, ``bytearray``, ``mmap`` and
any C-contiguous buffer of bytes), so no copy of the input is made.
Samples are returned as ``array.array`` (``'i'``, ``'f'``, ``'d'``) or
``bytes`` for text.
"""

import threading

from cpython cimport array
from libc.stdint cimport int64_t, uint8_t, uint32_t, uint64_t
from libc.string cimport memcpy, memset

import array as _array

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

LIBMSEED_VERSION_STR = LIBMSEED_VERSION.decode("ascii")

# Sample arrays: 'i' must hold libmseed int32 samples.
cdef array.array _INT_ARRAY = _array.array("i")
cdef array.array _FLOAT_ARRAY = _array.array("f")
cdef array.array _DOUBLE_ARRAY = _array.array("d")

if _INT_ARRAY.itemsize != 4:
    raise ImportError("cymseed3 needs a 4-byte C int")

# Message prefixes, used to tell warnings from errors.
cdef const char *_WARNING_PREFIX = b"W:"
cdef const char *_ERROR_PREFIX = b"E:"

# ----------------------------------------------------------------------------
# libmseed messages
# ----------------------------------------------------------------------------

# libmseed keeps its logging parameters per thread: they are set before
# every call, and the messages go to a list of the calling thread.
_local = threading.local()


cdef void _log_print(const char *message) noexcept nogil:
    # Level-0 (verbose) messages are not requested.
    pass


cdef void _diag_print(const char *message) noexcept nogil:
    with gil:
        messages = getattr(_local, "messages", None)
        if messages is None:
            return
        text = message.decode("utf-8", "replace").strip()
        if text.startswith("E:"):
            messages.append((2, text[2:].strip()))
        elif text.startswith("W:"):
            messages.append((1, text[2:].strip()))
        else:
            messages.append((1, text))


cdef list _start_log():
    """Route the libmseed messages of this thread to a new list."""
    messages = []
    _local.messages = messages
    ms_rloginit(_log_print, _WARNING_PREFIX, _diag_print, _ERROR_PREFIX, 0)
    return messages


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

cdef object _samples(void *data, int64_t count, char sampletype):
    """Copy libmseed samples into an array.array (bytes for text)."""
    cdef array.array result
    cdef size_t size
    if count <= 0 or data == NULL:
        count = 0
        if sampletype not in (b"t", b"f", b"d"):
            sampletype = b"i"
    if sampletype == b"t":
        return (<char *>data)[:count] if count else b""
    if sampletype == b"i":
        result = array.clone(_INT_ARRAY, count, zero=False)
        size = 4
    elif sampletype == b"f":
        result = array.clone(_FLOAT_ARRAY, count, zero=False)
        size = 4
    elif sampletype == b"d":
        result = array.clone(_DOUBLE_ARRAY, count, zero=False)
        size = 8
    else:
        return None
    if count:
        memcpy(result.data.as_voidptr, data, <size_t>count * size)
    return result


cdef str _decode(const char *text):
    return text.decode("ascii", "replace")


cdef bint _all_zero(const unsigned char *data, uint64_t size):
    cdef uint64_t i
    for i in range(size):
        if data[i]:
            return False
    return True


# ----------------------------------------------------------------------------
# Record scanner
# ----------------------------------------------------------------------------

cdef class Scanner:
    """
    Parse the records of a buffer one at a time.

    Invalid records are skipped: the scanner moves to the next position
    where libmseed detects a record header. Every skip, truncated final
    record and nonzero trailing bytes are reported in ``messages``
    together with the messages of libmseed.
    """

    cdef const unsigned char[::1] _buffer
    cdef uint64_t _size
    cdef uint64_t _offset
    cdef uint32_t _flags
    cdef MS3Record *_msr
    cdef readonly uint64_t record_offset
    cdef readonly list messages

    def __cinit__(self, const unsigned char[::1] buffer, bint unpack,
                  bint validate_crc):
        self._buffer = buffer
        self._size = buffer.shape[0]
        self._offset = 0
        # The buffer holds the whole content: a final MiniSEED 2 record
        # without blockette 1000 takes the remaining length (as libmseed
        # does at the end of a file).
        self._flags = MSF_ATENDOFFILE
        if unpack:
            self._flags |= MSF_UNPACKDATA
        if validate_crc:
            self._flags |= MSF_VALIDATECRC
        self._msr = NULL
        self.record_offset = 0
        self.messages = []

    def __dealloc__(self):
        msr3_free(&self._msr)

    cdef const char *_pointer(self, uint64_t offset):
        return <const char *>&self._buffer[0] + offset

    cdef int64_t _record_length(self, uint64_t offset):
        """Return the length of a detected record, 0 if not known."""
        cdef uint8_t version
        cdef int64_t length = ms3_detect(
            self._pointer(offset), self._size - offset, &version)
        if length > 0 and <uint64_t>length <= self._size - offset:
            return length
        return 0

    cdef uint64_t _skip(self, uint64_t offset):
        """Return the number of bytes up to the next record header."""
        cdef uint8_t version
        cdef uint64_t position = offset + 1
        while self._size - position >= <uint64_t>MINRECLEN:
            if ms3_detect(self._pointer(position), self._size - position,
                          &version) >= 0:
                return position - offset
            position += 1
        return self._size - offset

    cdef bint next_record(self):
        """
        Parse the next valid record into the internal MS3Record.

        Return False at the end of the buffer.
        """
        cdef uint64_t offset
        cdef uint64_t skip
        cdef int status
        self.messages = []
        while self._size - self._offset >= <uint64_t>MINRECLEN:
            offset = self._offset
            log = _start_log()
            status = msr3_parse(self._pointer(offset), self._size - offset,
                                &self._msr, self._flags, 0)
            if status == MS_NOERROR:
                self.record_offset = offset
                self._offset = offset + <uint64_t>self._msr.reclen
                self.messages.extend(
                    (level, f"record at offset {offset}: {text}")
                    for level, text in log
                )
                return True
            if status > 0:
                self.messages.append((1, (
                    f"incomplete record at offset {offset} skipped: "
                    f"{self._size - offset} bytes, {status} more needed"
                )))
                self._offset = self._size
                return False
            # An invalid record of known length (e.g. a wrong CRC) is
            # skipped whole; otherwise up to the next record header.
            detail = "; ".join(text for _, text in log)
            detail = f": {detail}" if detail else ""
            skip = <uint64_t>self._record_length(offset)
            if skip:
                self.messages.append((1, (
                    f"invalid record at offset {offset} skipped "
                    f"({skip} bytes){detail}"
                )))
            else:
                skip = self._skip(offset)
                if not _all_zero(
                        <const unsigned char *>self._pointer(offset), skip):
                    self.messages.append((1, (
                        f"invalid data at offset {offset} skipped "
                        f"({skip} bytes){detail}"
                    )))
            self._offset = offset + skip
        if self._offset < self._size:
            if not _all_zero(
                    <const unsigned char *>self._pointer(self._offset),
                    self._size - self._offset):
                self.messages.append((1, (
                    f"{self._size - self._offset} trailing bytes at offset "
                    f"{self._offset} ignored"
                )))
            self._offset = self._size
        return False

    def next(self):
        """
        Return the header of the next record, or None at the end.

        The header is a tuple: offset, length, format version, source
        identifier, flags, start and end time (ns), rate (Hz), encoding,
        publication version, sample count, CRC, extra headers (bytes)
        and the raw record (bytes).
        """
        if not self.next_record():
            return None
        msr = self._msr
        return (
            self.record_offset,
            msr.reclen,
            msr.formatversion,
            _decode(msr.sid),
            msr.flags,
            msr.starttime,
            msr3_endtime(msr),
            msr3_sampratehz(msr),
            msr.encoding,
            msr.pubversion,
            msr.samplecnt,
            msr.crc,
            msr.extra[:msr.extralength] if msr.extralength else b"",
            self._pointer(self.record_offset)[:msr.reclen],
        )

    def data(self):
        """Return the unpacked samples of the current record."""
        return _samples(self._msr.datasamples, self._msr.numsamples,
                        self._msr.sampletype)


def unpack_record(const unsigned char[::1] record):
    """
    Decode the samples of one record.

    Returns
    -------
    tuple
        The samples (``array.array`` or ``bytes``, None if they cannot
        be decoded) and the libmseed messages.
    """
    cdef MS3Record *msr = NULL
    cdef int status
    if record.shape[0] == 0:
        return None, [(2, "empty record")]
    log = _start_log()
    try:
        status = msr3_parse(<const char *>&record[0], record.shape[0],
                            &msr, MSF_UNPACKDATA | MSF_ATENDOFFILE, 0)
        if status != MS_NOERROR:
            return None, log
        return _samples(msr.datasamples, msr.numsamples,
                        msr.sampletype), log
    finally:
        msr3_free(&msr)


# ----------------------------------------------------------------------------
# Trace list
# ----------------------------------------------------------------------------

cdef class TraceList:
    """libmseed trace list: records joined into contiguous segments."""

    cdef MS3TraceList *_mstl

    def __cinit__(self):
        self._mstl = mstl3_init(NULL)
        if self._mstl == NULL:
            raise MemoryError("cannot allocate the libmseed trace list")

    def __dealloc__(self):
        mstl3_free(&self._mstl, 0)

    def clear(self):
        """Remove all the traces."""
        mstl3_free(&self._mstl, 0)
        self._mstl = mstl3_init(NULL)
        if self._mstl == NULL:
            raise MemoryError("cannot allocate the libmseed trace list")

    def read(self, const unsigned char[::1] buffer, bint validate_crc):
        """
        Add the records of a buffer to the trace list.

        Records without samples are skipped.

        Returns
        -------
        tuple
            Number of records read and the messages.
        """
        cdef Scanner scanner = Scanner(buffer, True, validate_crc)
        cdef MS3Record *msr
        cdef int count = 0
        messages = []
        while scanner.next_record():
            messages.extend(scanner.messages)
            count += 1
            msr = scanner._msr
            if msr.numsamples <= 0:
                continue
            log = _start_log()
            if mstl3_addmsr_recordptr(self._mstl, msr, NULL, 0, 1, 0,
                                      NULL) == NULL:
                detail = "; ".join(text for _, text in log)
                messages.append((1, (
                    f"record at offset {scanner.record_offset} not added"
                    + (f": {detail}" if detail else "")
                )))
        messages.extend(scanner.messages)
        return count, messages

    def segments(self):
        """
        Return the segments as tuples.

        Each tuple holds: source identifier, publication version, start
        and end time (ns), rate (Hz), sample type and samples.
        """
        cdef MS3TraceID *trace = self._mstl.traces.next[0]
        cdef MS3TraceSeg *segment
        result = []
        while trace != NULL:
            sid = _decode(trace.sid)
            segment = trace.first
            while segment != NULL:
                result.append((
                    sid,
                    trace.pubversion,
                    segment.starttime,
                    segment.endtime,
                    segment.samprate,
                    chr(segment.sampletype) if segment.sampletype else "",
                    _samples(segment.datasamples, segment.numsamples,
                             segment.sampletype),
                ))
                segment = segment.next
            trace = trace.next[0]
        return result

    def count(self):
        """Return the number of segments."""
        cdef MS3TraceID *trace = self._mstl.traces.next[0]
        cdef MS3TraceSeg *segment
        cdef int total = 0
        while trace != NULL:
            segment = trace.first
            while segment != NULL:
                total += 1
                segment = segment.next
            trace = trace.next[0]
        return total


# ----------------------------------------------------------------------------
# Identifiers and times
# ----------------------------------------------------------------------------

def sid_to_codes(str sid):
    """
    Split an FDSN source identifier into its four codes.

    Returns
    -------
    tuple
        The codes (None on error) and the messages.
    """
    cdef char network[64]
    cdef char station[64]
    cdef char location[64]
    cdef char channel[64]
    encoded = sid.encode("ascii", "replace")
    if len(encoded) >= 64:
        return None, [(2, f"source identifier longer than 63 characters: "
                          f"{sid}")]
    memset(network, 0, 64)
    memset(station, 0, 64)
    memset(location, 0, 64)
    memset(channel, 0, 64)
    log = _start_log()
    if ms_sid2nslc_n(encoded, network, 64, station, 64, location, 64,
                     channel, 64) != 0:
        return None, log
    return (_decode(network), _decode(station), _decode(location),
            _decode(channel)), log


def codes_to_sid(str network, str station, str location, str channel):
    """
    Build an FDSN source identifier from four codes.

    Returns
    -------
    tuple
        The identifier (None on error) and the messages.
    """
    cdef char sid[64]
    log = _start_log()
    if ms_nslc2sid(sid, 64, 0, network.encode("ascii", "replace"),
                   station.encode("ascii", "replace"),
                   location.encode("ascii", "replace"),
                   channel.encode("ascii", "replace")) < 0:
        return None, log
    return _decode(sid), log


def ns_to_string(int64_t nstime):
    """
    Format a time in ns as ISO 8601 (UTC, ``Z``, ns or µs if needed).

    Returns
    -------
    tuple
        The string (None on error) and the messages.
    """
    cdef char text[64]
    log = _start_log()
    if ms_nstime2timestr_n(nstime, text, 64, ISOMONTHDAY_Z,
                           NANO_MICRO_NONE) == NULL:
        return None, log
    return _decode(text), log


def ns_from_string(str text):
    """
    Parse a time string into ns (formats of libmseed).

    Returns
    -------
    tuple
        The time (None on error) and the messages.
    """
    cdef int64_t nstime
    log = _start_log()
    nstime = ms_timestr2nstime(text.encode("ascii", "replace"))
    if nstime == NSTERROR:
        return None, log
    return nstime, log
