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
Build of the cymseed3 extension (metadata in pyproject.toml).

The extension compiles the Cython binding together with the C sources
of the bundled libmseed (earthscope/libmseed-<version>), which is used
unmodified.
"""

from __future__ import annotations

import glob
import os

from Cython.Build import cythonize
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

# Bundled libmseed: exactly one version in earthscope/.
(LIBMSEED_DIR,) = [
    path for path in glob.glob(os.path.join("earthscope", "libmseed-*"))
    if os.path.isdir(path)
]

# C sources of the library (test programs and examples excluded).
LIBMSEED_SOURCES = sorted(glob.glob(os.path.join(LIBMSEED_DIR, "*.c")))

extension = Extension(
    name="cymseed3._libmseed",
    sources=[os.path.join("cymseed3", "_libmseed.pyx"), *LIBMSEED_SOURCES],
    include_dirs=[LIBMSEED_DIR],
    define_macros=[("LIBMSEED_STATIC", None)],
)


class BuildExt(build_ext):
    """
    Build the extension with the options of the compiler in use.

    MSVC (Windows) takes its own option syntax and needs no math
    library; GCC and Clang (Linux, macOS, MinGW) link libm.
    """

    def build_extensions(self):
        msvc = self.compiler.compiler_type == "msvc"
        for ext in self.extensions:
            if msvc:
                ext.extra_compile_args = ["/O2", "/W3"]
                # As in libmseed's Makefile.win: no warnings for the
                # standard C functions that MSVC considers unsafe.
                ext.define_macros.append(("_CRT_SECURE_NO_WARNINGS", None))
            else:
                ext.extra_compile_args = ["-O2", "-Wall"]
                ext.libraries.append("m")
        super().build_extensions()


setup(
    cmdclass={"build_ext": BuildExt},
    ext_modules=cythonize(
        [extension],
        compiler_directives={"language_level": "3"},
    ),
)
