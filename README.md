# cymseed3

`cymseed3` reads and writes MiniSEED 2 and 3 in Python with
[libmseed](https://github.com/EarthScope/libmseed) (EarthScope), the
reference C library of the format, bundled in the package (currently
version 3.5.4).

- Reading of files, `bytes` and other buffers (e.g. SeedLink packets),
  without copies and in linear time; records joined into contiguous
  segments, or one record at a time with all its header fields.
- Writing of int16, int32, float32, float64 and text samples in every
  MiniSEED encoding (STEIM1, STEIM2, integers, floats, text), each
  channel with its own encoding.
- Samples as `array.array` in their native type, times as integer
  nanoseconds (the full precision of MiniSEED 3).
- No dependency besides the Python standard library; NumPy arrays are
  accepted and returned without copies.

cymseed3 is part of the [ShakeLab](https://github.com/shakelab/shakelab)
ecosystem, where it is the default MiniSEED backend, but it can be used
on its own.

## Installation

```bash
pip install cymseed3
```

Python 3.10 or later is required. Binary wheels are published for
Linux (x86_64 and aarch64, glibc and musl), macOS (Intel and Apple
Silicon) and Windows (64-bit), so no compiler is needed there. On
other platforms pip builds the package from source, which needs a C
compiler (on macOS, the Xcode command line tools:
`xcode-select --install`; on Windows, the Microsoft C++ Build Tools).

From the repository, for development:

```bash
git clone https://github.com/shakelab/cymseed3.git
cd cymseed3
pip install -e ".[dev]"
pytest
```

## Usage

### Reading segments

```python
from cymseed3 import MiniSeed, ns_to_string

ms = MiniSeed()
ms.read("day.mseed")             # path, bytes, buffer or binary file
for segment in ms.segments():    # sorted by source identifier and time
    print(segment.sid,           # "FDSN:IV_MODE__H_N_Z"
          segment.codes,         # ("IV", "MODE", "", "HNZ")
          ns_to_string(segment.start_ns),
          segment.rate,          # Hz
          len(segment.data))     # array.array('i', 'f' or 'd')

ms.segments("FDSN:IV_MODE__H_N_?")   # shell-style pattern
```

Invalid records, truncated records and the warnings of libmseed are
reported as `MiniSeedWarning` and the reading goes on.

### Reading records

```python
from cymseed3 import iter_records

for record in iter_records("day.mseed"):
    record.offset, record.reclen, record.format_version
    record.sid, record.start_ns, record.end_ns, record.rate
    record.encoding, record.pubversion, record.samplecnt
    record.flags          # MiniSEED 3 flags (bit 2: clock locked, ...)
    record.extra          # extra headers, e.g. {"FDSN": {"Time": ...}}
    record.raw            # bytes of the record
    record.data           # samples, decoded on first access
    record.info()         # printed summary
```

MiniSEED 2 fields without a direct MiniSEED 3 counterpart (sequence
number, data quality, activity, I/O and quality flags, blockettes) are
translated by libmseed into the FDSN extra headers. A SeedLink packet
is one record: `next(iter_records(packet))`.

### Writing

```python
import numpy as np
from cymseed3 import MiniSeed, ns_from_string

start = ns_from_string("2026-11-02T10:15:30.123456Z")

ms = MiniSeed()
ms.add(("IV", "MODE", "", "HNZ"), start, 100.0,
       np.arange(1000, dtype=np.int32))                 # STEIM2
ms.add(("IV", "MODE", "", "HNE"), start, 100.0,
       np.zeros(1000, dtype=np.float32))                # encoding 4
ms.add(("IV", "MODE", "", "HNN"), start, 100.0,
       [1, 2, 3], encoding=10)                          # STEIM1
ms.write("out.mseed", version=2, reclen=512)            # or bytes
```

`pack_records` packs one series into records with chosen record length,
encoding, publication version, flags and extra headers.

### With NumPy

```python
import numpy as np

data = np.frombuffer(segment.data, dtype=segment.data.typecode)
```

## License

cymseed3 is distributed under the GNU Lesser General Public License,
version 3 or later (`COPYING.LESSER`, with the GNU General Public
License in `COPYING`).

The bundled libmseed (`earthscope/libmseed-<version>`, unmodified) is
Copyright (C) Chad Trabant, EarthScope Data Services, and distributed
under the Apache License, Version 2.0
(`earthscope/libmseed-<version>/LICENSE`); its test files are used by
the tests of cymseed3.

## Contact

Issues and pull requests on
[GitHub](https://github.com/shakelab/cymseed3). Author: Valerio Poggi.
