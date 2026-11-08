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
MiniSEED 2 and 3 reading and writing based on libmseed.

See :mod:`cymseed3.miniseed` for the interface.
"""

from __future__ import annotations

from cymseed3.miniseed import (
    LIBMSEED_VERSION,
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

__all__ = [
    "LIBMSEED_VERSION",
    "MSRecord",
    "MiniSeed",
    "MiniSeedError",
    "MiniSeedWarning",
    "Segment",
    "__version__",
    "codes_to_sid",
    "iter_records",
    "ns_from_string",
    "ns_to_string",
    "sid_to_codes",
]

__version__ = "0.2.0.dev0"
