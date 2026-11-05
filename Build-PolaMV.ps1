$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv }
& '.venv/Scripts/python.exe' -m pip install --no-cache-dir -r requirements.txt pyinstaller pytest
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& '.venv/Scripts/python.exe' -m pytest -q tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build/pyinstaller-cache'
& '.venv/Scripts/python.exe' -m PyInstaller --noconfirm PolaMV.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
& '.venv/Scripts/python.exe' tools/package_offline.py
if ($LASTEXITCODE -ne 0) { throw 'Offline archive failed' }
