@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "APP_NAME=Pinaki"
set "LOCAL_APP_ROOT=%LOCALAPPDATA%\%APP_NAME%"
set "LEGACY_LOCAL_APP_ROOT=%LOCALAPPDATA%\SchoolFlow"
set "DEV_DATA_DIR=%SCRIPT_DIR%\data"
set "DEV_DB=%DEV_DATA_DIR%\school.db"

echo.
echo [Pinaki Reset] Stopping any running Pinaki process...
powershell -NoProfile -Command "$scriptDir=[System.IO.Path]::GetFullPath('%SCRIPT_DIR%'); $appDataDir=[System.IO.Path]::GetFullPath('%LOCAL_APP_ROOT%'); $legacyAppDataDir=[System.IO.Path]::GetFullPath('%LEGACY_LOCAL_APP_ROOT%'); $matches=Get-CimInstance Win32_Process | Where-Object { $name=if ($_.Name) { $_.Name } else { '' }; $commandLine=if ($_.CommandLine) { $_.CommandLine } else { '' }; $executablePath=if ($_.ExecutablePath) { $_.ExecutablePath } else { '' }; $isPinakiExe=($name -ieq 'Pinaki.exe') -or ($executablePath -like '*\Pinaki.exe'); $isLegacyExe=($name -ieq 'SchoolFlow.exe') -or ($executablePath -like '*\SchoolFlow.exe'); $isRepoRun=($commandLine -like ('*' + $scriptDir + '*')) -and ($commandLine -match 'launcher\.py|main\.py|uvicorn'); $isInstalledRun=($commandLine -like ('*' + $appDataDir + '*')) -or ($commandLine -like ('*' + $legacyAppDataDir + '*')); $isPinakiExe -or $isLegacyExe -or $isRepoRun -or $isInstalledRun }; if ($matches) { $matches | ForEach-Object { Write-Host 'Stopping process' $_.ProcessId '->' $_.Name; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host 'No matching Pinaki process found.' }"

echo.
echo [Pinaki Reset] Removing Pinaki app data and caches...
powershell -NoProfile -Command "$scriptDir=[System.IO.Path]::GetFullPath('%SCRIPT_DIR%'); $devDataDir=[System.IO.Path]::GetFullPath('%DEV_DATA_DIR%'); $devDb=[System.IO.Path]::GetFullPath('%DEV_DB%'); $localAppRoot=[System.IO.Path]::GetFullPath('%LOCAL_APP_ROOT%'); $legacyLocalAppRoot=[System.IO.Path]::GetFullPath('%LEGACY_LOCAL_APP_ROOT%'); function Remove-IfExists { param([string]$TargetPath,[string]$Label) if (Test-Path -LiteralPath $TargetPath) { Remove-Item -LiteralPath $TargetPath -Recurse -Force -ErrorAction SilentlyContinue; Write-Host ('Removed ' + $Label + ': ' + $TargetPath) } else { Write-Host ('No ' + $Label + ' found at ' + $TargetPath) } }; Remove-IfExists -TargetPath $devDb -Label 'development database file'; if (Test-Path -LiteralPath $devDataDir) { Get-ChildItem -LiteralPath $devDataDir -Force -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }; Write-Host ('Cleared development data folder: ' + $devDataDir) } else { Write-Host ('No development data folder found at ' + $devDataDir) }; Remove-IfExists -TargetPath $localAppRoot -Label 'installed app data'; Remove-IfExists -TargetPath $legacyLocalAppRoot -Label 'legacy installed app data'; $cacheDirs=Get-ChildItem -LiteralPath $scriptDir -Directory -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike ($scriptDir + '\.venv*') -and ( $_.Name -eq '__pycache__' -or $_.Name -eq '.pytest_cache' ) }; if ($cacheDirs) { foreach ($dir in $cacheDirs) { Remove-Item -LiteralPath $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue; Write-Host ('Removed cache folder: ' + $dir.FullName) } } else { Write-Host 'No repo cache folders found.' }; $dbArtifacts=Get-ChildItem -LiteralPath $scriptDir -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike ($scriptDir + '\.venv*') -and ( $_.Name -like '*.db-wal' -or $_.Name -like '*.db-shm' -or $_.Name -like '*.db-journal' ) }; if ($dbArtifacts) { foreach ($file in $dbArtifacts) { Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue; Write-Host ('Removed database sidecar: ' + $file.FullName) } } else { Write-Host 'No database sidecar files found.' }"

if not exist "%DEV_DATA_DIR%" mkdir "%DEV_DATA_DIR%" >nul 2>&1

echo.
echo [Pinaki Reset] Resetting setup flag...
python -c "from school_admin.database import SessionLocal, get_settings; session = SessionLocal(); settings = get_settings(session); settings and setattr(settings, 'setup_completed', False) if settings else None; session.commit(); session.close(); print('[OK] Setup flag reset - setup screen will show on next run')" 2>nul || echo [Warning] Could not reset setup flag, but database was cleared.

echo.
echo [Pinaki Reset] Reset complete.
echo Run Pinaki again and it should return to the one-time setup screen.
pause
