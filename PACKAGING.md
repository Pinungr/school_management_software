# Packaging Pinaki for Windows

This project is set up to package the offline FastAPI app as a native desktop application.

## What the packaging flow does

1. `launcher.py` starts the local FastAPI server in the background.
2. It opens the application in a dedicated Edge or Chrome app window so the full web UI renders correctly.
3. The packaged launcher keeps the application available while that app window is open.
4. PyInstaller bundles the launcher, backend, templates, and static assets.
5. Inno Setup wraps the bundled app into a normal Windows installer.
6. The packaged executable runs as a windowed app, so users do not see a separate console window.

## Files used

- `launcher.py`: desktop launcher entry point
- `Pinaki.spec`: PyInstaller configuration
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

- Bundled app folder: `dist\Pinaki`
- Installer: `installer_output\Pinaki-Setup.exe`

## Notes

- The packaged app stores its SQLite database under the current user's local app data folder.
- Templates and static assets are bundled into the executable distribution.
- The installed app runs fully offline on the target PC. It opens in an Edge or Chrome app window for modern CSS support.
- Keep the Pinaki application window open while using the app. Closing that window stops the local server.
- Startup and window errors are shown as desktop dialog boxes in the packaged app.
- The packaged app icon comes from `static\app_icon.ico`, and the browser/tab icon comes from `static\app_icon.png`.
