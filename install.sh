#!/bin/bash

# Function to display usage instructions
usage() {
    echo "Usage: $0"
    exit 1
}

# Ensure the script is run from the project root directory
if [ ! -f "setup.py" ]; then
    echo "Error: setup.py not found in the current directory."
    usage
fi

# Upgrade pip, install Cython, setuptools, and wheel
pip3 install --upgrade pip
pip3 install --upgrade cython setuptools wheel

# Compile Cython extensions and install locally in editable mode
python3 setup.py build_ext --inplace
pip3 install -e .

echo "Local installation completed."

