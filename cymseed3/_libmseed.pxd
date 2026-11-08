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
# cython: language_level=3
#
# Declarations of the libmseed interface used by cymseed3. Only the
# structure members read or written by the binding are declared; the
# layout comes from libmseed.h.

from libc.stdint cimport (
    int8_t, int16_t, int32_t, int64_t, uint8_t, uint16_t, uint32_t,
    uint64_t,
)

cdef extern from "libmseed.h" nogil:

    ctypedef int64_t nstime_t

    # -- constants ------------------------------------------------------

    const char *LIBMSEED_VERSION
    int MINRECLEN
    int LM_SIDLEN
    nstime_t NSTERROR

    int MS_NOERROR
    int MS_GENERROR

    uint32_t MSF_UNPACKDATA
    uint32_t MSF_VALIDATECRC
    uint32_t MSF_ATENDOFFILE

    ctypedef enum ms_timeformat_t:
        ISOMONTHDAY_Z

    ctypedef enum ms_subseconds_t:
        NANO_MICRO_NONE

    # -- structures -----------------------------------------------------

    ctypedef struct MS3Record:
        const char *record
        int32_t reclen
        char sid[64]
        uint8_t formatversion
        uint8_t flags
        nstime_t starttime
        double samprate
        int16_t encoding
        uint8_t pubversion
        int64_t samplecnt
        uint32_t crc
        uint16_t extralength
        uint32_t datalength
        char *extra
        void *datasamples
        uint64_t datasize
        int64_t numsamples
        char sampletype

    ctypedef struct MS3TraceSeg:
        nstime_t starttime
        nstime_t endtime
        double samprate
        int64_t samplecnt
        void *datasamples
        uint64_t datasize
        int64_t numsamples
        char sampletype
        MS3TraceSeg *next

    ctypedef struct MS3TraceID:
        char sid[64]
        uint8_t pubversion
        MS3TraceSeg *first
        MS3TraceID *next[8]

    ctypedef struct MS3TraceList:
        uint32_t numtraceids
        MS3TraceID traces

    ctypedef struct MS3Tolerance:
        pass

    # -- records --------------------------------------------------------

    MS3Record *msr3_init(MS3Record *msr)
    void msr3_free(MS3Record **ppmsr)
    int msr3_parse(const char *record, uint64_t recbuflen,
                   MS3Record **ppmsr, uint32_t flags, int8_t verbose)
    int64_t ms3_detect(const char *record, uint64_t recbuflen,
                       uint8_t *formatversion)
    double msr3_sampratehz(const MS3Record *msr)
    nstime_t msr3_endtime(const MS3Record *msr)

    # -- trace lists ----------------------------------------------------

    MS3TraceList *mstl3_init(MS3TraceList *mstl)
    void mstl3_free(MS3TraceList **ppmstl, int8_t freeprvtptr)
    MS3TraceSeg *mstl3_addmsr_recordptr(
        MS3TraceList *mstl, const MS3Record *msr, void *pprecptr,
        int8_t splitversion, int8_t autoheal, uint32_t flags,
        const MS3Tolerance *tolerance)

    # -- identifiers and times ------------------------------------------

    int ms_sid2nslc_n(const char *sid, char *net, size_t netsize, char *sta,
                      size_t stasize, char *loc, size_t locsize, char *chan,
                      size_t chansize)
    int ms_nslc2sid(char *sid, int sidlen, uint16_t flags, const char *net,
                    const char *sta, const char *loc, const char *chan)
    char *ms_nstime2timestr_n(nstime_t nstime, char *timestr,
                              size_t timestrsize,
                              ms_timeformat_t timeformat,
                              ms_subseconds_t subsecond)
    nstime_t ms_timestr2nstime(const char *timestr)

    # -- logging --------------------------------------------------------

    void ms_rloginit(void (*log_print)(const char *), const char *logprefix,
                     void (*diag_print)(const char *), const char *errprefix,
                     int maxmessages)
