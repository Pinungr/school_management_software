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

if (-not (Test-Path "static\app_icon.ico")) {
    Write-Host "Custom icon not found. The installer will use the default icon."
}

Write-Host "Cleaning previous build output..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue }
if (Test-Path "build_pkg") { Remove-Item -Recurse -Force "build_pkg" -ErrorAction SilentlyContinue }
if (Test-Path "dist_pkg") { Remove-Item -Recurse -Force "dist_pkg" -ErrorAction SilentlyContinue }
if (Test-Path "installer_output") { Remove-Item -Recurse -Force "installer_output" -ErrorAction SilentlyContinue }

if (-not (Test-Path ".env")) {
    throw "Missing .env. Create .env with GITHUB_LICENSE_REPO and GITHUB_LICENSE_TOKEN before building."
}

$envValues = @{}
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        return
    }
    $parts = $line.Split("=", 2)
    $key = $parts[0].Trim([char]0xFEFF).Trim()
    $value = $parts[1].Trim()
    $envValues[$key] = $value
}

if (-not $envValues.ContainsKey("GITHUB_LICENSE_REPO") -or -not $envValues["GITHUB_LICENSE_REPO"]) {
    throw ".env is missing GITHUB_LICENSE_REPO."
}
if (-not $envValues.ContainsKey("GITHUB_LICENSE_TOKEN") -or -not $envValues["GITHUB_LICENSE_TOKEN"]) {
    throw ".env is missing GITHUB_LICENSE_TOKEN."
}

Write-Host "Using licensing config from .env for installer build..."

Write-Host "Building executable with PyInstaller..."
Invoke-Expression "$pythonCommand -m PyInstaller --clean --noconfirm --workpath build_pkg --distpath dist_pkg Pinaki.spec"

# Ensure .env is in the dist folder for the installer to pick it up
if (Test-Path ".env") {
    Copy-Item ".env" "dist_pkg\Pinaki\.env" -Force
}

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    throw "Inno Setup was not found at '$iscc'. Install Inno Setup 6 and rerun."
}

Write-Host "Building installer..."
& $iscc "installer_script.iss"

Write-Host "Packaging complete. See .\installer_output"
