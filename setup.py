from setuptools import setup, Extension
from Cython.Build import cythonize
import os

# Directory of the C library
libmseed_dir = os.path.join('earthscope', 'libmseed-3.1.3')

# Read the README file for the long description
long_description = ""
if os.path.exists('README.md'):
    with open('README.md', 'r') as f:
        long_description = f.read()

# List of C source files for libmseed
libmseed_sources = [
    os.path.join(libmseed_dir, 'crc32c.c'),
    os.path.join(libmseed_dir, 'extraheaders.c'),
    os.path.join(libmseed_dir, 'fileutils.c'),
    os.path.join(libmseed_dir, 'genutils.c'),
    os.path.join(libmseed_dir, 'gmtime64.c'),
    os.path.join(libmseed_dir, 'logging.c'),
    os.path.join(libmseed_dir, 'lookup.c'),
    os.path.join(libmseed_dir, 'msio.c'),
    os.path.join(libmseed_dir, 'msrutils.c'),
    os.path.join(libmseed_dir, 'pack.c'),
    os.path.join(libmseed_dir, 'packdata.c'),
    os.path.join(libmseed_dir, 'parseutils.c'),
    os.path.join(libmseed_dir, 'selection.c'),
    os.path.join(libmseed_dir, 'tracelist.c'),
    os.path.join(libmseed_dir, 'unpack.c'),
    os.path.join(libmseed_dir, 'unpackdata.c'),
    os.path.join(libmseed_dir, 'yyjson.c'),
]

# Compiler and linker flags
extra_compile_args = ['-std=c99', '-O2', '-Wall', '-DLIBMSEED_STATIC']
extra_link_args = ['-lm']

# Include directories
include_dirs = [libmseed_dir]

# Define the extension module
ext_modules = [
    Extension(
        name="cymseed3",
        sources=["cymseed3.pyx"] + libmseed_sources,
        include_dirs=include_dirs,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
    )
]

setup(
    name="cymseed3",
    version="0.1.5",
    description="A Python package for reading and writing miniseed files using libmseed 3.",
    long_description=long_description,
    long_description_content_type='text/markdown',
    author="Valerio Poggi",
    author_email="vpoggi@ogs.it",
    url="https://github.com/shakelab/cymseed3",
    license="GPLv3",
    ext_modules=cythonize(ext_modules),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: C",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering"
    ],
    python_requires='>=3.6',
    setup_requires=[
        'setuptools>=42',
        'cython>=0.29',
    ],
    install_requires=[
        # Add other dependencies your package might have
    ],
    keywords='miniseed libmseed seismic data processing',
    zip_safe=False
)

