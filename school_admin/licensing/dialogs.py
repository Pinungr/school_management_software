"""
License activation dialog - shown when starting Pinaki without a valid license
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    from tkinter import simpledialog
except ModuleNotFoundError:
    tk = None
    messagebox = None


WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _escape_ps_string(value: str) -> str:
    """Escape single quotes for PowerShell single-quoted strings."""
    return value.replace("'", "''")


def _prompt_key_with_powershell(title: str, message: str) -> str | None:
    """Prompt for activation key using a native Windows dialog."""
    if sys.platform != "win32":
        return None
    ps_title = _escape_ps_string(title)
    ps_message = _escape_ps_string(
        message + "\n\nKey format: PINAKI-XXXX-XXXX-XXXX-XXXX"
    )
    script = (
        "$null = Add-Type -AssemblyName Microsoft.VisualBasic;"
        f"$result = [Microsoft.VisualBasic.Interaction]::InputBox('{ps_message}', '{ps_title}', '');"
        "if ($null -eq $result) { '' } else { $result }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
            timeout=120,
        )
    except Exception:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def _show_message_with_powershell(title: str, message: str, is_error: bool) -> bool:
    """Display a native Windows message box when tkinter is unavailable."""
    if sys.platform != "win32":
        return False
    ps_title = _escape_ps_string(title)
    ps_message = _escape_ps_string(message)
    icon = "Error" if is_error else "Information"
    script = (
        "$null = Add-Type -AssemblyName System.Windows.Forms;"
        "[void][System.Windows.Forms.MessageBox]::Show("
        f"'{ps_message}', '{ps_title}', "
        "[System.Windows.Forms.MessageBoxButtons]::OK, "
        f"[System.Windows.Forms.MessageBoxIcon]::{icon})"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
            timeout=60,
        )
        return True
    except Exception:
        return False


def _read_key_from_console(message: str) -> str | None:
    """Read activation key from stdin when interactive input is available."""
    print(f"To activate: {message}")
    stdin = getattr(sys, "stdin", None)
    if stdin is None or not hasattr(stdin, "readline"):
        print("[X] No interactive input stream is available.")
        return None
    try:
        return input("Activation Key: ").strip()
    except (EOFError, RuntimeError, OSError):
        # Windowed builds may not have an attached stdin stream.
        print("[X] Could not read activation key from console input.")
        return None


def show_license_dialog(
    title: str = "Pinaki License Activation",
    message: str = "Enter your activation key to activate Pinaki"
) -> str | None:
    """
    Show a dialog to input activation key
    
    Returns:
        The entered key, or None if cancelled
    """
    if not tk:
        key = _prompt_key_with_powershell(title, message)
        if key:
            return key
        return _read_key_from_console(message)

    root = None
    try:
        root = tk.Tk()
        root.withdraw()  # Hide main window
        return simpledialog.askstring(
            title,
            message + "\n\nKey format: PINAKI-XXXX-XXXX-XXXX-XXXX",
            show=None,
        )
    except Exception:
        key = _prompt_key_with_powershell(title, message)
        if key:
            return key
        return _read_key_from_console(message)
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def show_license_success_dialog(username: str, expiry_date: str) -> None:
    """Show success message after activation"""
    if not tk:
        if _show_message_with_powershell(
            "License Activated",
            f"License activated successfully!\n\nUser: {username}\nExpires: {expiry_date}",
            is_error=False,
        ):
            return
        print(f"[OK] License activated for {username}")
        print(f"[OK] Expires: {expiry_date}")
        return

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "License Activated",
            f"License activated successfully!\n\n"
            f"User: {username}\n"
            f"Expires: {expiry_date}",
        )
    except Exception:
        _show_message_with_powershell(
            "License Activated",
            f"License activated successfully!\n\nUser: {username}\nExpires: {expiry_date}",
            is_error=False,
        )
        print(f"[OK] License activated for {username}")
        print(f"[OK] Expires: {expiry_date}")
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def show_license_error_dialog(error_message: str) -> None:
    """Show error message"""
    if not tk:
        if _show_message_with_powershell("License Error", error_message, is_error=True):
            return
        print(f"[X] License Error: {error_message}")
        return

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("License Error", error_message)
    except Exception:
        _show_message_with_powershell("License Error", error_message, is_error=True)
        print(f"[X] License Error: {error_message}")
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def show_license_expired_dialog() -> None:
    """Show license expired message"""
    if not tk:
        if _show_message_with_powershell(
            "License Expired",
            "Your Pinaki license has expired.\n\n"
            "Please contact your administrator to renew your license key.",
            is_error=True,
        ):
            return
        print("[X] Your license has expired. Please renew your license key.")
        return

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "License Expired",
            "Your Pinaki license has expired.\n\n"
            "Please contact your administrator to renew your license key.",
        )
    except Exception:
        _show_message_with_powershell(
            "License Expired",
            "Your Pinaki license has expired.\n\n"
            "Please contact your administrator to renew your license key.",
            is_error=True,
        )
        print("[X] Your license has expired. Please renew your license key.")
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def show_license_info_dialog(
    username: str,
    expiry_date: str,
    days_remaining: int,
    key: str
) -> None:
    """Show license information"""
    if not tk:
        if _show_message_with_powershell(
            "License Information",
            "License Information:\n\n"
            f"User: {username}\n"
            f"Expires: {expiry_date}\n"
            f"Days Remaining: {days_remaining}",
            is_error=False,
        ):
            return
        print(f"\nLicense Information:")
        print(f"  User: {username}")
        print(f"  Expires: {expiry_date}")
        print(f"  Days Remaining: {days_remaining}")
        return
    
    expiry_obj = datetime.fromisoformat(expiry_date)
    warning = ""
    if days_remaining <= 30:
        warning = f"\n[!] Your license expires in {days_remaining} days!"
    
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "License Information",
            f"License Information:\n\n"
            f"User: {username}\n"
            f"Expires: {expiry_obj.strftime('%Y-%m-%d')}\n"
            f"Days Remaining: {days_remaining}{warning}",
        )
    except Exception:
        _show_message_with_powershell(
            "License Information",
            "License Information:\n\n"
            f"User: {username}\n"
            f"Expires: {expiry_date}\n"
            f"Days Remaining: {days_remaining}",
            is_error=False,
        )
        print(f"\nLicense Information:")
        print(f"  User: {username}")
        print(f"  Expires: {expiry_date}")
        print(f"  Days Remaining: {days_remaining}")
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
