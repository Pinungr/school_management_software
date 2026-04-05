# Packaging SchoolFlow for Windows

This project is set up to package the offline FastAPI app as a desktop-style Windows application.

## What the packaging flow does

1. `launcher.py` starts the local FastAPI server in the background.
2. It opens the browser automatically to the local app.
3. PyInstaller bundles the launcher, backend, templates, and static assets.
4. Inno Setup wraps the bundled app into a normal Windows installer.

## Files used

- `launcher.py`: desktop launcher entry point
- `SchoolFlow.spec`: PyInstaller configuration
- `installer_script.iss`: Inno Setup installer definition
- `build_windows.ps1`: repeatable build script

## Build steps

1. Install Python 3.11 or newer.
2. Open PowerShell in the project folder.
3. Run:

```powershell
.\build_windows.ps1
```

## Expected output

- Bundled app folder: `dist\SchoolFlow`
- Installer: `installer_output\SchoolFlow-Setup.exe`

## Notes

- The packaged app stores its SQLite database under the current user's local app data folder.
- Templates and static assets are bundled into the executable distribution.
- If you want a custom Windows icon in the installer and executable, add `static\logo.ico` before building.
