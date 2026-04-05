from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn

from main import app, startup_target_path
from school_admin.database import APP_DATA_DIR


def should_skip_browser() -> bool:
    return os.environ.get("SCHOOLFLOW_SKIP_BROWSER") == "1"


def is_smoke_test() -> bool:
    return os.environ.get("SCHOOLFLOW_SMOKE_TEST") == "1"


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

    def start(self) -> int:
        print("SchoolFlow Desktop")
        print("==================")
        print("Starting local server...")
        self.server_thread.start()

        if not wait_for_server(self.port):
            print("")
            print("The local server did not start correctly.")
            print("Close this window and launch SchoolFlow again.")
            self.shutdown()
            return 1

        print(f"Running locally at {self.url}")
        if should_skip_browser():
            print("Browser launch skipped for this run.")
        else:
            print("Opening your browser...")
            self.open_browser()

        if is_smoke_test():
            print("Smoke test startup succeeded.")
            self.shutdown()
            return 0

        print("")
        print("Keep this window open while using SchoolFlow.")
        print("Commands: press Enter to reopen the browser, type 'data' to open the data folder,")
        print("type 'exit' to close SchoolFlow.")

        try:
            while True:
                command = input("> ").strip().lower()
                if command in {"", "open"}:
                    self.open_browser()
                    continue
                if command == "data":
                    self.open_data_folder()
                    continue
                if command in {"exit", "quit", "q"}:
                    break
                print("Unknown command. Use Enter, 'data', or 'exit'.")
        except (EOFError, KeyboardInterrupt):
            print("")
        finally:
            print("Shutting down SchoolFlow...")
            self.shutdown()
        return 0

    def open_browser(self) -> None:
        webbrowser.open(f"{self.url}{startup_target_path()}", new=2)

    def open_data_folder(self) -> None:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(APP_DATA_DIR)  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        self.server.should_exit = True
        if self.server_thread.is_alive():
            self.server_thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(DesktopLauncher().start())
