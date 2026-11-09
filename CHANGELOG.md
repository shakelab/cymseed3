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
- `MiniSeed.add(codes, start_ns, rate, data, encoding=None,
  pubversion=1)` adds int16, int32, float32 or float64 buffers (NumPy
  arrays, `array.array`, `memoryview`), lists of numbers or text bytes;
  `MiniSeed.write(target=None, version=2, reclen=512, owrite=False)`
  packs all the segments into MiniSEED 2 or 3 bytes or a file, each
  source identifier with its own encoding (by default STEIM2, STEIM1 or
  int32 from the sample differences, 4 for float32, 5 for float64, 0
  for text).
- `pack_records(codes, start_ns, rate, data, ...)` packs one series
  into records with chosen record length, encoding, publication
  version, flags and extra headers (written as blockettes in
  MiniSEED 2), returned as `MSRecord` objects.
- `sid_to_codes`, `codes_to_sid`, `ns_to_string`, `ns_from_string`.
- `MiniSeedError` (a `ValueError`) and `MiniSeedWarning` (a
  `UserWarning`); the messages of libmseed are issued as warnings with
  the offset of the record.
- Tests against the libmseed file readers on the 46 libmseed test
  files, and round trips of all the encodings in MiniSEED 2 and 3.

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
  `cymseed3._libmseed`; Cython 3.1 or later is required to build it.
- License: GNU Lesser General Public License v3 or later (was GPL v3);
  `COPYING` and `COPYING.LESSER` replace `LICENSE`. The bundled
  libmseed keeps its Apache License 2.0.
- Packaging: metadata only in `pyproject.toml` (SPDX license
  expression `LGPL-3.0-or-later AND Apache-2.0`, license files),
  PEP 517 build (`pip install .` or `pip install -e ".[dev]"`),
  `setup.py` reduced to the extension, which compiles whichever
  `earthscope/libmseed-*` is bundled; Python 3.10 or later on Linux or
  macOS; the source distribution includes the tests and the libmseed
  test files; type information (`py.typed`).
- Continuous integration on Linux and macOS with Python 3.10-3.14, and
  a test of the source distribution.
- README rewritten for the new interface.

### Removed

- `MiniSeed.export_records` and `MiniSeed.import_record` (replaced by
  `MiniSeed.segments` and `MiniSeed.add`), `MiniSeed.numtraceids`,
  `MiniSeed.print`, the `convert_*` time functions, `example.py`,
  `install.sh`, `requirements.txt` and the archive of libmseed 3.1.3
  (`earthscope/libmseed-3.1.3.tar.gz`).

### Fixed

- Source identifiers with codes longer than 9 characters overflowed a
  stack buffer.
- The validation of MiniSEED 3 CRCs no longer writes into the input
  buffer (libmseed 3.1.3 zeroed the CRC field in place: a crash on
  read-only `mmap`).
- The last MiniSEED 2 record of a buffer without blockette 1000 is read
  (as libmseed does at the end of a file).
- Floating-point and int16 samples were written through an int32
  buffer (float values corrupted, reading beyond the buffer for
  float64); one integer encoding was used for the whole file.
- int16 encoding of values outside the int16 range (silently truncated
  by libmseed) is an error.
- Invalid start times produced unreadable files without error (times
  are now integer nanoseconds, checked before writing).
