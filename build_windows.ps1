Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $workspace

$pythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    "py -3",
    "python"
)

$pythonCommand = $null
foreach ($candidate in $pythonCandidates) {
    try {
        Invoke-Expression "$candidate --version" | Out-Null
        $pythonCommand = $candidate
        break
    } catch {
    }
}

if (-not $pythonCommand) {
    throw "Python was not found. Install Python 3.11+ or create a .venv first."
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    Invoke-Expression "$pythonCommand -m venv .venv"
    $pythonCommand = ".\.venv\Scripts\python.exe"
}

Write-Host "Installing dependencies..."
Invoke-Expression "$pythonCommand -m pip install --upgrade pip"
Invoke-Expression "$pythonCommand -m pip install -r requirements.txt pyinstaller"

if (-not (Test-Path "static\logo.ico")) {
    Write-Host "Custom icon not found. The installer will use the default icon."
}

Write-Host "Cleaning previous build output..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "installer_output") { Remove-Item -Recurse -Force "installer_output" }

Write-Host "Building executable with PyInstaller..."
Invoke-Expression "$pythonCommand -m PyInstaller --clean --noconfirm SchoolFlow.spec"

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    throw "Inno Setup was not found at '$iscc'. Install Inno Setup 6 and rerun."
}

Write-Host "Building installer..."
& $iscc "installer_script.iss"

Write-Host "Packaging complete. See .\installer_output"
