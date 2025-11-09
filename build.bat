@echo off
REM Build script for Windows
REM This script creates a standalone executable using PyInstaller

echo ================================================
echo Building ppxai executable...
echo ================================================

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install/upgrade dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Clean previous builds
echo Cleaning previous builds...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Build with PyInstaller
echo Building executable...
pyinstaller ppxai.spec

REM Check if build was successful
if exist "dist\ppxai.exe" (
    echo.
    echo ================================================
    echo Build successful!
    echo ================================================
    echo Executable location: dist\ppxai.exe
    echo.
    echo To run:
    echo   dist\ppxai.exe
    echo.
    echo Remember to create a .env file with your PERPLEXITY_API_KEY
    echo ================================================
) else (
    echo Build failed!
    exit /b 1
)
