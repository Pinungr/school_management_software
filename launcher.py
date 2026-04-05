from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from tkinter import BOTH, LEFT, RIGHT, Button, Frame, Label, Tk, messagebox

import uvicorn

from main import app, startup_target_path
from school_admin.database import APP_DATA_DIR


def find_available_port(start_port: int = 8765, max_tries: int = 40) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port was available for SchoolFlow.")


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


class DesktopLauncher:
    def __init__(self) -> None:
        self.port = find_available_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.browser_opened = False
        self.root = self._build_window()

    def _build_window(self) -> Tk:
        root = Tk()
        root.title("SchoolFlow Desktop")
        root.geometry("520x320")
        root.minsize(520, 320)
        root.configure(bg="#f4f7fb")
        root.protocol("WM_DELETE_WINDOW", self.shutdown)

        shell = Frame(root, bg="#f4f7fb", padx=22, pady=22)
        shell.pack(fill=BOTH, expand=True)

        hero = Frame(shell, bg="#ffffff", highlightbackground="#dfe7f3", highlightthickness=1)
        hero.pack(fill=BOTH, expand=True)

        Label(
            hero,
            text="SchoolFlow",
            bg="#ffffff",
            fg="#162235",
            font=("Segoe UI", 22, "bold"),
            pady=18,
        ).pack()
        Label(
            hero,
            text="Your offline school management workspace is launching.",
            bg="#ffffff",
            fg="#66758b",
            font=("Segoe UI", 11),
        ).pack()

        self.status_label = Label(
            hero,
            text="Starting local server...",
            bg="#ffffff",
            fg="#2563eb",
            font=("Segoe UI", 10, "bold"),
            pady=18,
        )
        self.status_label.pack()

        Label(
            hero,
            text="This window keeps the desktop app running. You can reopen the browser any time.",
            bg="#ffffff",
            fg="#66758b",
            font=("Segoe UI", 10),
            wraplength=420,
            justify=LEFT,
            padx=24,
        ).pack()

        actions = Frame(hero, bg="#ffffff", pady=22)
        actions.pack(fill="x")

        Button(
            actions,
            text="Open SchoolFlow",
            command=self.open_browser,
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1746a2",
            activeforeground="#ffffff",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 10, "bold"),
        ).pack(side=LEFT, padx=(24, 8))

        Button(
            actions,
            text="Open Data Folder",
            command=self.open_data_folder,
            bg="#eef3fb",
            fg="#162235",
            activebackground="#dfe7f3",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 10),
        ).pack(side=LEFT)

        Button(
            actions,
            text="Exit",
            command=self.shutdown,
            bg="#ffffff",
            fg="#dc4c64",
            activebackground="#fff1f3",
            relief="flat",
            padx=14,
            pady=10,
            font=("Segoe UI", 10),
        ).pack(side=RIGHT, padx=(8, 24))

        return root

    def start(self) -> None:
        self.server_thread.start()
        threading.Thread(target=self._complete_startup, daemon=True).start()
        self.root.mainloop()

    def _complete_startup(self) -> None:
        if wait_for_server(self.port):
            self.root.after(0, self._set_ready_state)
            self.open_browser()
        else:
            self.root.after(0, self._set_error_state)

    def _set_ready_state(self) -> None:
        self.status_label.configure(text=f"Running locally at {self.url}", fg="#198754")

    def _set_error_state(self) -> None:
        self.status_label.configure(
            text="The local server did not start correctly. Please restart the app.",
            fg="#dc4c64",
        )
        messagebox.showerror(
            "SchoolFlow",
            "The desktop app could not start the local server. Please close the app and try again.",
        )

    def open_browser(self) -> None:
        webbrowser.open(f"{self.url}{startup_target_path()}", new=2)
        self.browser_opened = True

    def open_data_folder(self) -> None:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(APP_DATA_DIR)  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        self.server.should_exit = True
        self.root.after(200, self.root.destroy)


if __name__ == "__main__":
    DesktopLauncher().start()
