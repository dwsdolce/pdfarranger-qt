@echo off
REM Build the Windows application bundle and installer.
REM
REM   packaging\build_win.bat
REM
REM Produces:
REM   dist\pdfarranger-qt\          the PyInstaller bundle
REM   installer\PDF_Arranger_Qt_V<version>.exe
REM
REM Requires Inno Setup 6 (https://jrsoftware.org/isdl.php) and a venv with the
REM dev extra installed: pip install -e ".[dev]"

REM Run from the project root regardless of where this script is invoked from.
cd /d "%~dp0\.."

REM ===============================================
REM  Setup the correct python environment
REM ===============================================
echo Activating win virtual environment for Python
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Activating virtual environment failed
    exit /b 1
)

echo Running build for %PROCESSOR_ARCHITECTURE% architecture

REM ===============================================
REM Clean-up
REM ===============================================
REM build\mo is regenerated below; removing all of build\ keeps a stale
REM catalogue from a renamed language directory out of the bundle.
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM ===============================================
REM Compile the translation catalogues
REM ===============================================
python tools\build_mo.py
if errorlevel 1 (
    echo Compiling translations failed
    exit /b 1
)

REM ===============================================
REM Generate version_build from the git commit count
REM ===============================================
python tools\gen_version_build.py
if errorlevel 1 (
    echo Generating version_build failed
    exit /b 1
)

REM Writes pdfarranger_qt\version_build for the frozen app, and
REM build\installer_version for the Inno Setup script. The full version
REM (e.g. 0.1.0.37) matches what the spec file produces.
for /f %%v in ('python tools\gen_version_build.py --print') do set VERSION=%%v
if errorlevel 1 (
    echo Reading the version failed
    exit /b 1
)
echo Creating installer for version %VERSION%

REM ===============================================
REM Run pyinstaller
REM ===============================================
pyinstaller -y packaging\pdfarranger-qt.spec
if errorlevel 1 (
    echo Running pyinstaller failed
    exit /b 1
)

REM ===============================================
REM Prepare installer path
REM ===============================================
set "installer_file=%cd%\packaging\pdfarranger-qt.iss"
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not exist "%ISCC_PATH%" (
    echo Inno Setup 6 not found at %ISCC_PATH%
    echo Install it from https://jrsoftware.org/isdl.php
    exit /b 1
)

REM ===============================================
REM You must install Inno Setup 6 to build the installer
REM ===============================================
REM No /D argument: the script reads build\installer_version itself,
REM which is also what makes it work from Cygwin and Git Bash.
"%ISCC_PATH%" "%installer_file%"
if errorlevel 1 (
    echo Creating the installer failed
    exit /b 1
)

echo Installer created successfully: installer\PDF_Arranger_Qt_V%VERSION%.exe
