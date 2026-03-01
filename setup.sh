#!/bin/bash

echo "Setting up the SPADE Multi-Agent environment"

# 1. Create the virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment '.venv'..."
    python3 -m venv .venv
else
    echo "Virtual environment '.venv' already exists."
fi

# 2. Activate the virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# 3. Upgrade pip to avoid installation warnings
echo "Upgrading pip..."
pip install --upgrade pip

# 4. Install dependencies from requirements.txt
if [ -f "requirements.txt" ]; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found!"
fi

echo "Setup complete!"
echo "To activate this environment in the future, run: source .venv/bin/activate"
echo "Note: If your environment didn't stay activated, make sure you run: source .venv/bin/activate"