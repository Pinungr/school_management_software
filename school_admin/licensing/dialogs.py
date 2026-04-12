"""
License activation dialog - shown when starting Pinaki without a valid license
"""

from __future__ import annotations

import sys
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    from tkinter import simpledialog
except ModuleNotFoundError:
    tk = None
    messagebox = None


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
        print(f"To activate: {message}")
        return input("Activation Key: ").strip()
    
    root = tk.Tk()
    root.withdraw()  # Hide main window
    
    # Use simpledialog for key input
    key = simpledialog.askstring(
        title,
        message + "\n\nKey format: PINAKI-XXXX-XXXX-XXXX-XXXX",
        show=None
    )
    root.destroy()
    
    return key


def show_license_success_dialog(username: str, expiry_date: str) -> None:
    """Show success message after activation"""
    if not tk:
        print(f"✓ License activated for {username}")
        print(f"✓ Expires: {expiry_date}")
        return
    
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "License Activated",
        f"License activated successfully!\n\n"
        f"User: {username}\n"
        f"Expires: {expiry_date}"
    )
    root.destroy()


def show_license_error_dialog(error_message: str) -> None:
    """Show error message"""
    if not tk:
        print(f"✗ License Error: {error_message}")
        return
    
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("License Error", error_message)
    root.destroy()


def show_license_expired_dialog() -> None:
    """Show license expired message"""
    if not tk:
        print("✗ Your license has expired. Please renew your license key.")
        return
    
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "License Expired",
        "Your Pinaki license has expired.\n\n"
        "Please contact your administrator to renew your license key."
    )
    root.destroy()


def show_license_info_dialog(
    username: str,
    expiry_date: str,
    days_remaining: int,
    key: str
) -> None:
    """Show license information"""
    if not tk:
        print(f"\nLicense Information:")
        print(f"  User: {username}")
        print(f"  Expires: {expiry_date}")
        print(f"  Days Remaining: {days_remaining}")
        return
    
    expiry_obj = datetime.fromisoformat(expiry_date)
    warning = ""
    if days_remaining <= 30:
        warning = f"\n⚠ Your license expires in {days_remaining} days!"
    
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "License Information",
        f"License Information:\n\n"
        f"User: {username}\n"
        f"Expires: {expiry_obj.strftime('%Y-%m-%d')}\n"
        f"Days Remaining: {days_remaining}{warning}"
    )
    root.destroy()
