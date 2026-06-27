"""
投研系统启动器
双击运行：自动启动 Streamlit 服务并打开浏览器
"""
import subprocess
import webbrowser
import time
import sys
import shutil
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
import urllib.request


APP_TITLE  = "📡 半导体供应链投研系统"
APP_PORT   = 8501
APP_URL    = f"http://localhost:{APP_PORT}"
BG_COLOR   = "#0d1117"
FG_COLOR   = "#e6edf3"
ACCENT     = "#238636"
ACCENT_ERR = "#da3633"


def find_python() -> str:
    """Find a usable Python executable that has Streamlit installed.

    When frozen by PyInstaller, sys.executable IS the .exe launcher —
    never use it as the Python interpreter; look in PATH instead.
    """
    frozen = getattr(sys, "frozen", False)

    candidates: list[str] = []
    if not frozen:
        # Running as a plain .py script — current interpreter is fine
        candidates.append(sys.executable)

    # Search PATH for python / python3 / py (Windows launcher)
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)

    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            subprocess.check_output(
                [candidate, "-c", "import streamlit"],
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if sys.platform == "win32" else 0),
            )
            return candidate
        except Exception:
            continue

    # Last resort — return whatever python is on PATH
    return shutil.which("python") or "python"


def wait_for_server(timeout: int = 30) -> bool:
    """Poll until Streamlit responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


class LauncherUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(False, False)
        self.root.geometry("420x200")
        # Center on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - 420) // 2
        y  = (sh - 200) // 2
        self.root.geometry(f"420x200+{x}+{y}")

        # Title label
        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        tk.Label(self.root, text=APP_TITLE, font=title_font,
                 bg=BG_COLOR, fg=FG_COLOR).pack(pady=(18, 4))

        # Status label
        self.status_var = tk.StringVar(value="正在启动服务…")
        status_font = tkfont.Font(family="Segoe UI", size=10)
        self.status_lbl = tk.Label(
            self.root, textvariable=self.status_var,
            font=status_font, bg=BG_COLOR, fg="#8b949e",
        )
        self.status_lbl.pack(pady=4)

        # Progress / dots animation
        self.dot_var = tk.StringVar(value="●  ○  ○")
        dot_font = tkfont.Font(family="Segoe UI", size=14)
        self.dot_lbl = tk.Label(
            self.root, textvariable=self.dot_var,
            font=dot_font, bg=BG_COLOR, fg=ACCENT,
        )
        self.dot_lbl.pack(pady=6)

        # Open browser button (hidden until ready)
        btn_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.open_btn = tk.Button(
            self.root, text="🌐 打开浏览器",
            font=btn_font, bg=ACCENT, fg="white",
            activebackground="#2ea043", activeforeground="white",
            bd=0, padx=16, pady=6, cursor="hand2",
            command=self._open_browser,
        )
        # Start background work
        self.proc: subprocess.Popen | None = None
        self._dot_step = 0
        self._animate()
        threading.Thread(target=self._start_server, daemon=True).start()

    def _animate(self):
        frames = ["●  ○  ○", "○  ●  ○", "○  ○  ●"]
        self.dot_var.set(frames[self._dot_step % 3])
        self._dot_step += 1
        if self.proc is None or self.proc.poll() is None:
            # keep animating while process is running or not yet started
            pass
        self._anim_id = self.root.after(400, self._animate)

    def _start_server(self):
        # When frozen by PyInstaller, __file__ points inside the temp extract
        # dir — use sys.executable's parent to get the real .exe folder.
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).parent
        python  = find_python()

        app_file = app_dir / "app.py"
        if not app_file.exists():
            self.root.after(0, lambda: (
                self.status_var.set(f"找不到 app.py\n路径：{app_dir}"),
                self.status_lbl.config(fg=ACCENT_ERR),
                self.dot_var.set("⚠ 路径错误"),
                self.dot_lbl.config(fg=ACCENT_ERR),
            ))
            return

        self.proc = subprocess.Popen(
            [python, "-m", "streamlit", "run",
             str(app_file),
             f"--server.port={APP_PORT}",
             "--server.headless=true",
             "--browser.gatherUsageStats=false"],
            cwd=str(app_dir),
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if sys.platform == "win32" else 0),
        )
        ok = wait_for_server(timeout=40)
        if ok:
            self.root.after(0, self._on_ready)
        else:
            self.root.after(0, self._on_error)

    def _on_ready(self):
        self.status_var.set(f"服务就绪 → {APP_URL}")
        self.status_lbl.config(fg=ACCENT)
        self.dot_lbl.config(fg=ACCENT, font=tkfont.Font(family="Segoe UI", size=11))
        self.dot_var.set("✅ 启动成功！")
        self.open_btn.pack(pady=8)
        webbrowser.open(APP_URL)

    def _on_error(self):
        self.status_var.set("启动超时，请手动访问 " + APP_URL)
        self.status_lbl.config(fg=ACCENT_ERR)
        self.dot_var.set("⚠ 超时")
        self.dot_lbl.config(fg=ACCENT_ERR)

    def _open_browser(self):
        webbrowser.open(APP_URL)

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.root.destroy()


if __name__ == "__main__":
    LauncherUI().run()
