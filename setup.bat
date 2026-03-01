@echo off
echo Setting up the SPADE Multi-Agent environment

:: 1. Create the virtual environment
IF NOT EXIST ".venv" (
    echo Creating virtual environment '.venv'...
    python -m venv .venv
) ELSE (
    echo Virtual environment '.venv' already exists.
)

:: 2. Activate the virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

:: 3. Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

:: 4. Install dependencies
IF EXIST "requirements.txt" (
    echo Installing dependencies...
    pip install -r requirements.txt
) ELSE (
    echo Warning:requirements.txt not found!
)

echo Setup complete!
echo Note: If your environment didn't stay activated, make sure you run: source .venv\Scripts\activate.bat
pause