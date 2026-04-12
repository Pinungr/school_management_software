from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import time
import logging
import shutil
import subprocess
import webbrowser
from pathlib import Path

def load_env_file() -> None:
    """
    Very simple .env file parser to load environment variables.
    Checks:
    1. Current directory (relative to script/exe)
    2. _MEIPASS directory (for bundled PyInstaller files)
    """
    candidates = []
    
    # Current script directory
    script_dir = Path(sys.argv[0]).parent
    candidates.append(script_dir / ".env")
    
    # PyInstaller bundle directory
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(getattr(sys, "_MEIPASS")) / ".env")
        
    # Working directory
    candidates.append(Path(".env"))

    for env_path in candidates:
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            os.environ.setdefault(key.strip(), val.strip())
                # Stop at the first found .env file
                return
            except Exception:
                pass

try:
    import tkinter as tk
    from tkinter import messagebox
except ModuleNotFoundError:
    tk = None
    messagebox = None

import uvicorn

from main import app, startup_target_path
from school_admin.database import APP_DATA_DIR
from school_admin.licensing import (
    LicenseManager,
    LicenseInvalidError,
    LicenseExpiredError,
    LicenseMachineError,
    LicenseNetworkError,
)
from school_admin.licensing.dialogs import (
    show_license_dialog,
    show_license_success_dialog,
    show_license_error_dialog,
    show_license_expired_dialog,
    show_license_info_dialog,
)

WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_smoke_test() -> bool:
    return os.environ.get("SCHOOLFLOW_SMOKE_TEST") == "1"


def should_skip_browser() -> bool:
    return os.environ.get("SCHOOLFLOW_SKIP_BROWSER") == "1"


def find_available_port(start_port: int = 8765, max_tries: int = 40) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port was available for Pinaki.")


def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def show_error_dialog(title: str, message: str) -> None:
    if tk is None or messagebox is None:
        print(f"{title}: {message}", file=sys.stderr)
        return
    configure_tk_runtime()
    dialog_root = tk.Tk()
    dialog_root.withdraw()
    try:
        messagebox.showerror(title, message, parent=dialog_root)
    finally:
        dialog_root.destroy()


def show_fallback_window() -> bool:
    if tk is None:
        return False

    configure_tk_runtime()
    window = tk.Tk()
    window.title("Pinaki Browser Fallback")
    window.resizable(False, False)
    window.protocol("WM_DELETE_WINDOW", window.destroy)

    frame = tk.Frame(window, padx=20, pady=18)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text="Pinaki is running in your default browser.",
        font=("Segoe UI", 11, "bold"),
        anchor="w",
        justify="left",
    ).pack(fill="x")
    tk.Label(
        frame,
        text=(
            "Microsoft Edge or Google Chrome was not found for app-window mode.\n\n"
            "Keep this helper window open while you use Pinaki. Close it when you are done."
        ),
        justify="left",
        anchor="w",
        wraplength=360,
    ).pack(fill="x", pady=(10, 14))
    tk.Button(frame, text="Close Pinaki", width=18, command=window.destroy).pack(anchor="e")

    try:
        window.mainloop()
    finally:
        if window.winfo_exists():
            window.destroy()
    return True


def configure_tk_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return

    runtime_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    tcl_root = runtime_root / "tcl"
    tcl_library = tcl_root / "tcl8.6"
    tk_library = tcl_root / "tk8.6"

    if tcl_library.exists():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
    if tk_library.exists():
        os.environ.setdefault("TK_LIBRARY", str(tk_library))


def has_console_streams() -> bool:
    return sys.stdout is not None and sys.stderr is not None


def remove_path_safely(path: Path) -> None:
    if not path.exists():
        return

    def _retry_remove(func, target, _exc_info):
        try:
            os.chmod(target, 0o700)
        except OSError:
            pass
        func(target)

    for _ in range(5):
        try:
            shutil.rmtree(path, ignore_errors=False, onerror=_retry_remove)
        except OSError:
            pass
        if not path.exists():
            return
        time.sleep(0.1)


def legacy_browser_profile_dir() -> Path:
    return APP_DATA_DIR / "browser-profile"


def create_runtime_browser_profile() -> Path:
    remove_path_safely(legacy_browser_profile_dir())
    runtime_root = APP_DATA_DIR / "runtime-browser-profiles"
    runtime_root.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = runtime_root / f"pinaki-browser-{secrets.token_hex(6)}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate.resolve()
        except FileExistsError:
            continue


def check_license() -> bool:
    """
    Check if Pinaki is licensed. Prompts user to activate if not licensed.
    
    Returns:
        True if licensed and valid, False if activation failed or cancelled
    """
    # Skip license check in smoke test or CI environments
    if is_smoke_test() or os.environ.get("CI") == "true":
        return True
    
    license_manager = LicenseManager(
        app_data_dir=APP_DATA_DIR,
        github_repo=os.environ.get("GITHUB_LICENSE_REPO", "pinaki-school/licenses"),
    )
    
    # Check if already licensed
    if license_manager.is_licensed():
        license_info = license_manager.get_license_status()
        days_remaining = license_manager.get_days_remaining()
        
        # Show warning if expiring soon
        if days_remaining and days_remaining <= 30 and license_info:
            show_license_info_dialog(
                username=license_info.get('username', 'Unknown'),
                expiry_date=license_info.get('expiry_date', 'Unknown'),
                days_remaining=days_remaining,
                key=license_info.get('key', '')
            )
        
        return True
    
    # Not licensed - prompt for activation
    print("\n" + "="*50)
    print("Pinaki License Required")
    print("="*50)
    print("This copy of Pinaki requires an activation key.")
    print("Please enter your activation key to continue.\n")
    
    max_retries = 3
    for attempt in range(max_retries):
        remaining = max_retries - attempt
        key = show_license_dialog(
            title="Pinaki License Activation",
            message=f"Enter your activation key (Attempt {attempt + 1}/{max_retries})\n\n"
                   f"Format: PINAKI-XXXX-XXXX-XXXX-XXXX"
        )
        
        if not key:
            # User cancelled
            print("[X] Activation cancelled. Cannot start Pinaki without a valid license.")
            show_license_error_dialog(
                "Activation Required\n\n"
                "Pinaki requires an activation key to run.\n"
                "Please contact your administrator for an activation key."
            )
            return False
        
        try:
            # Try to validate
            print(f"Validating activation key...")
            activation_username = (
                os.environ.get("PINAKI_LICENSE_USERNAME")
                or os.environ.get("USERNAME")
                or os.environ.get("USER")
                or "Local User"
            )
            license_info = license_manager.validate_key(key, username=activation_username)
            
            # Success!
            show_license_success_dialog(
                username=license_info.get('username', 'User'),
                expiry_date=license_info.get('expiry_date', 'Unknown')
            )
            print(f"✓ License activated successfully!")
            print(f"  User: {license_info.get('username')}")
            print(f"  Expires: {license_info.get('expiry_date')}")
            return True
            
        except LicenseExpiredError as e:
            show_license_error_dialog(str(e))
            print(f"✗ License expired: {e}")
            if remaining > 1:
                show_license_error_dialog(f"Please try again. ({remaining - 1} attempts remaining)")
            
        except LicenseInvalidError as e:
            show_license_error_dialog(str(e))
            print(f"✗ Invalid license: {e}")
            if remaining > 1:
                show_license_error_dialog(f"Please try again. ({remaining - 1} attempts remaining)")
            
        except LicenseMachineError as e:
            show_license_error_dialog(str(e))
            print(f"✗ Machine mismatch: {e}")
            return False
            
        except LicenseNetworkError as e:
            show_license_error_dialog(
                f"Could not verify license with GitHub:\n\n{e}\n\n"
                "Make sure you have internet connection and try again."
            )
            print(f"✗ Network error: {e}")
            if remaining > 1:
                show_license_error_dialog(f"Please try again. ({remaining - 1} attempts remaining)")
    
    # All retries failed
    print("✗ Maximum activation attempts exceeded. Cannot start Pinaki.")
    show_license_error_dialog(
        "Activation Failed\n\n"
        "Could not activate Pinaki after 3 attempts.\n"
        "Please contact your administrator."
    )
    return False


def count_browser_app_processes(browser_executable: str, target_url: str) -> int:
    browser_name = Path(browser_executable).name
    script = f"""
$matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {{
        $_.Name -eq '{browser_name}' -and
        $_.CommandLine -like '*--app={target_url}*'
    }}
@($matches).Count
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        creationflags=WINDOWS_NO_WINDOW,
    )
    if result.returncode != 0:
        return 0
    output = result.stdout.strip()
    try:
        return int(output or "0")
    except ValueError:
        return 0


def wait_for_browser_window(
    browser_executable: str,
    target_url: str,
    timeout: float = 15.0,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if count_browser_app_processes(browser_executable, target_url) > 0:
            return True
        time.sleep(0.25)
    return False


def wait_for_browser_window_to_close(
    browser_executable: str,
    target_url: str,
    poll_interval: float = 0.5,
) -> None:
    while count_browser_app_processes(browser_executable, target_url) > 0:
        time.sleep(poll_interval)


def find_browser_executable() -> str | None:
    candidates = [
        shutil.which("msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


class DesktopLauncher:
    def __init__(self) -> None:
        self.port = find_available_port()
        self.url = f"http://127.0.0.1:{self.port}"
        uvicorn_config = self.build_uvicorn_config()
        self.server = uvicorn.Server(uvicorn_config)
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.browser_process: subprocess.Popen[str] | None = None
        self.browser_profile_path = create_runtime_browser_profile()

    def build_uvicorn_config(self) -> uvicorn.Config:
        config_kwargs = {
            "host": "127.0.0.1",
            "port": self.port,
            "log_level": "warning",
        }
        if has_console_streams():
            return uvicorn.Config(app, **config_kwargs)

        logging.basicConfig(level=logging.WARNING)
        config_kwargs.update(
            {
                "log_config": None,
                "access_log": False,
                "use_colors": False,
            }
        )
        return uvicorn.Config(app, **config_kwargs)

    def start(self) -> int:
        print("Pinaki Desktop")
        print("==============")
        print("Starting local server...")
        try:
            self.server_thread.start()
        except Exception as exc:
            show_error_dialog(
                "Pinaki Startup Error",
                f"Pinaki could not start the local server.\n\n{exc}",
            )
            return 1

        if not wait_for_server(self.port):
            print("")
            print("The local server did not start correctly.")
            print("Close this window and launch Pinaki again.")
            self.shutdown()
            show_error_dialog(
                "Pinaki Startup Error",
                "The local Pinaki server did not start correctly.\n\n"
                "Close this window and launch Pinaki again.",
            )
            return 1

        print(f"Running locally at {self.url}")

        if is_smoke_test():
            print("Smoke test startup succeeded.")
            self.shutdown()
            return 0

        if should_skip_browser():
            print("Browser launch skipped for this run.")
            return 0

        print("Opening Pinaki application window...")
        try:
            self.open_app_window()
            return 0
        except Exception as exc:
            self.shutdown()
            show_error_dialog(
                "Pinaki Window Error",
                f"Pinaki could not open its application window.\n\n{exc}",
            )
            return 1

    def open_app_window(self) -> None:
        target_url = f"{self.url}{startup_target_path()}"
        browser_executable = find_browser_executable()

        if browser_executable:
            args = [
                browser_executable,
                f"--app={target_url}",
                "--new-window",
                "--window-size=1400,900",
                "--no-first-run",
                "--disable-session-crashed-bubble",
                "--disable-application-cache",
                "--aggressive-cache-discard",
                "--disk-cache-size=1",
                "--media-cache-size=1",
                "--disable-features=Translate,msImplicitSignin",
                f"--user-data-dir={self.browser_profile_path}",
            ]
            self.browser_process = subprocess.Popen(args)
            opened = wait_for_browser_window(browser_executable, target_url)
            if not opened:
                if self.browser_process.poll() is not None:
                    raise RuntimeError("The desktop browser window did not stay open.")
                raise RuntimeError("Pinaki could not detect the browser app window.")
            wait_for_browser_window_to_close(browser_executable, target_url)
            self.shutdown()
            return

        webbrowser.open(target_url, new=2)
        self.keep_running_in_browser_fallback()

    def keep_running_in_browser_fallback(self) -> None:
        if show_fallback_window():
            self.shutdown()
            return

        print("")
        print("Pinaki opened in your default browser because Microsoft Edge or Google Chrome")
        print("was not found for app-window mode.")
        print("Press Ctrl+C in this window when you are done.")
        try:
            while self.server_thread.is_alive() and not self.server.should_exit:
                self.server_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.server.should_exit = True
        if self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        remove_path_safely(self.browser_profile_path)


def main() -> int:
    # Load environment variables from .env if present
    load_env_file()
    
    # Check license before starting
    if not check_license():
        return 1
    
    return DesktopLauncher().start()


if __name__ == "__main__":
    raise SystemExit(main())
