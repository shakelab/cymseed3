# Changelog

All notable changes to cymseed3 are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Version 0.2.0 rewrites the interface; it is not compatible with 0.1.x.

### Added

- `MiniSeed.read(source, validate_crc=True)` reads paths (through
  `mmap`), `bytes`, `bytearray`, `memoryview`, `mmap`, other contiguous
  byte buffers and binary files, without copying the input; reading
  time is linear in the size of the input.
- `MiniSeed.segments(pattern=None)` returns `Segment` objects (source
  identifier, publication version, start and end time in ns, rate,
  sample type, samples); `MiniSeed.sids()`, `len()`, `clear()`,
  `info()`.
- `iter_records(source, unpack=False, validate_crc=True)` returns the
  records one at a time as `MSRecord` objects (offset, length, format
  version, header fields, MiniSEED 3 flags, CRC, extra headers as a
  dictionary, raw bytes, samples decoded on request, `info()`).
- `sid_to_codes`, `codes_to_sid`, `ns_to_string`, `ns_from_string`.
- `MiniSeedError` (a `ValueError`) and `MiniSeedWarning` (a
  `UserWarning`); the messages of libmseed are issued as warnings with
  the offset of the record.
- Tests against the libmseed file readers on the 46 libmseed test
  files.

### Changed

- The bundled libmseed is updated from 3.1.3 to 3.5.4 (fixes in
  MiniSEED 2 time encoding when writing, blockette 1001 and 100,
  robustness of the parser); the C sources are compiled with the
  default C standard of the compiler, as by libmseed (`-std=c99` hid
  `ftello`/`fseeko`).
- Samples are returned as `array.array` in their native type (int32,
  float32, float64) and text as `bytes`, instead of Python lists.
- Times are integer nanoseconds instead of ISO strings with
  microseconds.
- Text and detection records no longer stop the reading: text records
  give `bytes`, records without samples are skipped (they are still
  returned by `iter_records`).
- Invalid data, truncated records and nonzero trailing bytes are
  skipped with a warning instead of printing to the terminal.
- The package is now `cymseed3` with the private extension
  `cymseed3._libmseed`; Cython 3 is required to build it.

### Removed

- `MiniSeed.export_records`, `MiniSeed.import_record`, `MiniSeed.write`
  (writing returns in the next block with `MiniSeed.add`,
  `MiniSeed.write` and `pack_records`), `MiniSeed.numtraceids`,
  `MiniSeed.print`, the `convert_*` time functions and `example.py`.

### Fixed

- Source identifiers with codes longer than 9 characters overflowed a
  stack buffer.
- The validation of MiniSEED 3 CRCs no longer writes into the input
  buffer (libmseed 3.1.3 zeroed the CRC field in place: a crash on
  read-only `mmap`).
- The last MiniSEED 2 record of a buffer without blockette 1000 is read
  (as libmseed does at the end of a file).
