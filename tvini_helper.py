#!/usr/bin/env python3
import subprocess
import threading
import platform
import sys
import os
import re
import stat
import json
import webbrowser
import ssl
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False

try:
    import customtkinter as ctk
except ImportError:
    print("Installing customtkinter...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
    import customtkinter as ctk

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw

# Update checker
VERSION = "2.0.0"
UPDATE_CHECK_URL = "https://tvini.io/ar/adb_update"

POLL_INTERVAL_MS = 2000
SYSTEM = platform.system()

if getattr(sys, 'frozen', False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")

# Colors
BG_DARK = "#0D0F12"
BG_CARD = "#161A1F"
BG_CARD_HOVER = "#1E2329"
BG_CARD_ACTIVE = "#252B33"
ACCENT = "#00D68F"
ACCENT_DIM = "#00A86E"
TEXT_PRIMARY = "#E8ECF1"
TEXT_SECONDARY = "#7A8494"
TEXT_MUTED = "#4A5568"
BORDER = "#2A3040"
RED = "#FF6B6B"
YELLOW = "#FFD93D"
BLUE = "#4DA6FF"

def _parse_version(version_str: str) -> tuple:
    try:
        parts = version_str.strip().split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)

def _check_for_update() -> dict | None:
    try:
        req = Request(UPDATE_CHECK_URL, headers={"User-Agent": "AndroidMirror"})

        if CERTIFI_AVAILABLE:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
        else:
            ssl_context = ssl.create_default_context()
        
        with urlopen(req, timeout=5, context=ssl_context) as response:
            data = json.loads(response.read().decode("utf-8"))

        latest_version = data.get("latest", "0.0.0")
        if _parse_version(latest_version) > _parse_version(VERSION):
            return data
    except (URLError, json.JSONDecodeError, Exception) as e:
        print(f"[Update Check Error] {type(e).__name__}: {e}")
    return None

class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, parent, metadata: dict):
        super().__init__(parent)
        
        self.title("Update Available")
        self.geometry("400x200")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.transient(parent)
        self.grab_set()

        note = metadata.get("note", "A new version is available.")
        url = metadata.get("url", "")
        latest = metadata.get("latest", "")
        ctk.CTkLabel(
            self, text="🔄",
            font=ctk.CTkFont(size=36),
        ).pack(pady=(20, 10))
        ctk.CTkLabel(
            self, text=note,
            font=ctk.CTkFont(size=14),
            text_color=TEXT_PRIMARY,
            wraplength=350,
        ).pack(pady=(0, 5))
        ctk.CTkLabel(
            self, text=f"Current: {VERSION}  →  Latest: {latest}",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 15))
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(0, 20))
        if url:
            ctk.CTkButton(
                btn_frame, text="Download Update",
                fg_color=ACCENT, hover_color=ACCENT_DIM,
                text_color=BG_DARK, font=ctk.CTkFont(size=13, weight="bold"),
                width=140, height=36,
                command=lambda: self._open_url(url),
            ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_frame, text="Later",
            fg_color="transparent", hover_color=BG_CARD_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=13),
            width=100, height=36,
            command=self.destroy,
        ).pack(side="left")

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 200) // 2
        self.geometry(f"400x200+{x}+{y}")

    def _open_url(self, url: str):
        webbrowser.open(url)
        self.destroy()

def _creation_flags():
    if SYSTEM == "Windows":
        return subprocess.CREATE_NO_WINDOW
    return 0

def _find_bundled_adb() -> str | None:
    if SYSTEM == "Windows":
        # scrcpy Windows zip bundles adb.exe alongside scrcpy.exe
        path = os.path.join(TOOLS_DIR, "windows", "scrcpy", "adb.exe")
        if os.path.isfile(path):
            return path
    else:
        print("OS is not Windows")
        return None
    return None

def _find_bundled_scrcpy() -> str | None:
    if SYSTEM == "Windows":
        path = os.path.join(TOOLS_DIR, "windows", "scrcpy", "scrcpy.exe")
        if os.path.isfile(path):
            return path
    else:
        print("OS is not Windows")
        return None
    return None

def _ensure_executable(path: str):
    st = os.stat(path)
    if not (st.st_mode & stat.S_IEXEC):
        os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

def _build_env(adb_path: str, scrcpy_path: str) -> dict:
    env = os.environ.copy()
    adb_dir = os.path.dirname(adb_path)
    env["ADB"] = adb_path
    scrcpy_dir = os.path.dirname(scrcpy_path)
    extra_path = os.pathsep.join([scrcpy_dir, adb_dir])
    env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
    return env

def get_adb_devices(adb_path: str) -> list[dict]:
    try:
        result = subprocess.run(
            [adb_path, "devices", "-l"],
            capture_output=True, text=True, timeout=5,
            creationflags=_creation_flags(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    devices = []
    for line in result.stdout.strip().splitlines()[1:]:
        line = line.strip()
        if not line or "offline" in line:
            continue

        parts = line.split()
        serial = parts[0]
        status = parts[1] if len(parts) > 1 else "unknown"

        if status not in ("device", "unauthorized"):
            continue

        info = {"serial": serial, "status": status}

        for part in parts[2:]:
            if ":" in part:
                k, v = part.split(":", 1)
                info[k] = v

        if status == "device":
            info["model"] = _adb_prop(adb_path, serial, "ro.product.model") or info.get("model", serial)
            info["manufacturer"] = _adb_prop(adb_path, serial, "ro.product.manufacturer") or ""
            info["android_version"] = _adb_prop(adb_path, serial, "ro.build.version.release") or ""
            info["sdk"] = _adb_prop(adb_path, serial, "ro.build.version.sdk") or ""
            info["resolution"] = _get_resolution(adb_path, serial)
            info["battery"] = _get_battery(adb_path, serial)
        devices.append(info)

    return devices

def _adb_prop(adb: str, serial: str, prop: str) -> str:
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "getprop", prop],
            capture_output=True, text=True, timeout=3,
            creationflags=_creation_flags(),
        )
        return r.stdout.strip()
    except Exception:
        return ""

def _get_resolution(adb: str, serial: str) -> str:
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "wm", "size"],
            capture_output=True, text=True, timeout=3,
            creationflags=_creation_flags(),
        )
        m = re.search(r"(\d+x\d+)", r.stdout)
        return m.group(1) if m else ""
    except Exception:
        return ""

def _get_battery(adb: str, serial: str) -> int | None:
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "dumpsys", "battery"],
            capture_output=True, text=True, timeout=3,
            creationflags=_creation_flags(),
        )
        m = re.search(r"level:\s*(\d+)", r.stdout)
        return int(m.group(1)) if m else None
    except Exception:
        return None

class DeviceCard(ctk.CTkFrame):
    def __init__(self, master, device: dict, on_click):
        super().__init__(
            master,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
            cursor="hand2",
        )

        self.device = device
        self.on_click = on_click
        self._is_mirroring = False

        self.grid_columnconfigure(1, weight=1)

        icon_frame = ctk.CTkFrame(self, fg_color=ACCENT_DIM, corner_radius=10, width=48, height=48)
        icon_frame.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16, sticky="ns")
        icon_frame.grid_propagate(False)
        icon_label = ctk.CTkLabel(icon_frame, text="📱", font=ctk.CTkFont(size=22))
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

        manufacturer = device.get("manufacturer", "").capitalize()
        model = device.get("model", device["serial"])
        display_name = f"{manufacturer} {model}".strip() if manufacturer else model

        name_label = ctk.CTkLabel(
            self, text=display_name,
            font=ctk.CTkFont(
                family="Segoe UI" if SYSTEM == "Windows" else "SF Pro Display",
                size=15, weight="bold"
            ),
            text_color=TEXT_PRIMARY, anchor="w",
        )
        name_label.grid(row=0, column=1, sticky="sw", padx=(0, 16), pady=(16, 0))

        sub_parts = []
        if device.get("android_version"):
            sub_parts.append(f"Android {device['android_version']}")
        if device.get("resolution"):
            sub_parts.append(device["resolution"])
        sub_parts.append(device["serial"])
        sub_text = "  ·  ".join(sub_parts)

        sub_label = ctk.CTkLabel(
            self, text=sub_text,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY, anchor="w",
        )
        sub_label.grid(row=1, column=1, sticky="nw", padx=(0, 16), pady=(2, 16))

        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.grid(row=0, column=2, rowspan=2, padx=(0, 16), pady=16, sticky="e")

        if device["status"] == "unauthorized":
            status_label = ctk.CTkLabel(
                right_frame, text="⚠ Unauthorized",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=YELLOW,
            )
            status_label.pack(anchor="e")
            hint = ctk.CTkLabel(
                right_frame, text="Allow USB debugging",
                font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
            )
            hint.pack(anchor="e")
        else:
            battery = device.get("battery")
            if battery is not None:
                bat_color = ACCENT if battery > 30 else (YELLOW if battery > 15 else RED)
                bat_label = ctk.CTkLabel(
                    right_frame, text=f"🔋 {battery}%",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=bat_color,
                )
                bat_label.pack(anchor="e")

            mirror_label = ctk.CTkLabel(
                right_frame, text="Click to mirror →",
                font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
            )
            mirror_label.pack(anchor="e", pady=(2, 0))

        self.bind("<Button-1>", self._handle_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        for child in self.winfo_children():
            child.bind("<Button-1>", self._handle_click)
            self._bind_recursive(child)

    def _bind_recursive(self, widget):
        for child in widget.winfo_children():
            child.bind("<Button-1>", self._handle_click)
            child.bind("<Enter>", lambda e: self._on_enter(e))
            child.bind("<Leave>", lambda e: self._on_leave(e))
            self._bind_recursive(child)

    def _on_enter(self, event):
        if not self._is_mirroring:
            self.configure(fg_color=BG_CARD_HOVER, border_color=ACCENT_DIM)

    def _on_leave(self, event):
        if not self._is_mirroring:
            self.configure(fg_color=BG_CARD, border_color=BORDER)

    def _handle_click(self, event):
        if self.device["status"] == "unauthorized":
            return
        if not self._is_mirroring:
            self._is_mirroring = True
            self.configure(fg_color=BG_CARD_ACTIVE, border_color=ACCENT)
            self.on_click(self.device, self)

    def reset_state(self):
        self._is_mirroring = False
        self.configure(fg_color=BG_CARD, border_color=BORDER)

class StatusBadge(ctk.CTkFrame):
    def __init__(self, master, text="", color=TEXT_MUTED):
        super().__init__(master, fg_color="transparent")
        self.dot = ctk.CTkFrame(self, width=8, height=8, corner_radius=4, fg_color=color)
        self.dot.pack(side="left", padx=(0, 6))
        self.label = ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY)
        self.label.pack(side="left")

    def update_status(self, text: str, color: str):
        self.label.configure(text=text)
        self.dot.configure(fg_color=color)

class AndroidMirrorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Android Mirror & APK Installer")
        self.geometry("580x650")
        self.minsize(480, 400)
        self.configure(fg_color=BG_DARK)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.adb_path = _find_bundled_adb()
        self.scrcpy_path = _find_bundled_scrcpy()

        if self.adb_path and self.scrcpy_path:
            self.tool_env = _build_env(self.adb_path, self.scrcpy_path)
        else:
            self.tool_env = os.environ.copy()

        self.current_devices: list[dict] = []
        self.device_cards: list[DeviceCard] = []
        self.active_mirrors: dict[str, subprocess.Popen] = {}
        self._poll_job = None
        self._build_ui()
        self._start_polling()

        threading.Thread(target=self._check_update_async, daemon=True).start()

    def _check_update_async(self):
        metadata = _check_for_update()
        if metadata:
            self.after(500, lambda: self._show_update_dialog(metadata))
    
    def _show_update_dialog(self, metadata: dict):
        UpdateDialog(self, metadata)

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))
        title = ctk.CTkLabel(
            header, text="Android Mirror & APK Installer",
            font=ctk.CTkFont(
                family="Segoe UI" if SYSTEM == "Windows" else "SF Pro Display",
                size=26, weight="bold"
            ),
            text_color=TEXT_PRIMARY,
        )
        title.pack(side="left")

        refresh_btn = ctk.CTkButton(
            header, text="⟳  Refresh", width=90, height=32,
            fg_color="transparent", hover_color=BG_CARD_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=12),
            command=self._refresh_devices,
        )
        refresh_btn.pack(side="right")

        if SYSTEM == "Windows" and self._find_zadig():
            zadig_btn = ctk.CTkButton(
                header, text="🔧 USB Driver", width=110, height=32,
                fg_color="transparent", hover_color=BG_CARD_HOVER,
                border_width=1, border_color=BORDER,
                text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=12),
                command=self._show_zadig_menu,
            )
            zadig_btn.pack(side="right", padx=(0, 8))

        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.pack(fill="x", padx=24, pady=(12, 0))

        self.adb_badge = StatusBadge(status_frame, text="ADB", color=TEXT_MUTED)
        self.adb_badge.pack(side="left", padx=(0, 16))

        self.scrcpy_badge = StatusBadge(status_frame, text="scrcpy", color=TEXT_MUTED)
        self.scrcpy_badge.pack(side="left", padx=(0, 16))

        self.device_count_label = ctk.CTkLabel(
            status_frame, text="", font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        )
        self.device_count_label.pack(side="right")
        version_label = ctk.CTkLabel(
            status_frame, text=f"v{VERSION}",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        )
        version_label.pack(side="right", padx=(0, 16))
        self._update_tool_status()
        sep = ctk.CTkFrame(self, fg_color=BORDER, height=1)
        sep.pack(fill="x", padx=24, pady=(16, 0))

        self.scroll_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=BG_CARD,
            scrollbar_button_hover_color=BG_CARD_HOVER,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=24, pady=(16, 8))
        self.empty_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self._build_empty_state()
        self.apk_status_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=8, height=36)
        self.apk_status_frame.pack(fill="x", padx=24, pady=(0, 16))
        self.apk_status_frame.pack_propagate(False)
        
        self.apk_status_label = ctk.CTkLabel(
            self.apk_status_frame, text="",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        )
        self.apk_status_label.pack(expand=True)

    def _build_empty_state(self):
        for w in self.empty_frame.winfo_children():
            w.destroy()

        if not self.adb_path:
            icon, title, desc = "⚙", "ADB Not Found", self._missing_adb_message()
            show_zadig = False
        elif not self.scrcpy_path:
            icon, title, desc = "🖥", "scrcpy Not Found", self._missing_scrcpy_message()
            show_zadig = False
        else:
            icon = "📲"
            title = "No Devices Connected"
            desc = (
                "Connect your Android device via USB and\n"
                "enable USB Debugging in Developer Options."
            )
            show_zadig = SYSTEM == "Windows"

        ctk.CTkLabel(
            self.empty_frame, text=icon,
            font=ctk.CTkFont(size=48), text_color=TEXT_MUTED,
        ).pack(pady=(60, 12))

        ctk.CTkLabel(
            self.empty_frame, text=title,
            font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            self.empty_frame, text=desc,
            font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
            justify="center",
        ).pack()

        # Zadig, Za-Done
        if show_zadig and self._find_zadig():
            zadig_frame = ctk.CTkFrame(self.empty_frame, fg_color="transparent")
            zadig_frame.pack(pady=(20, 0))
            
            ctk.CTkLabel(
                zadig_frame, text="Device not detected? Try fixing the USB driver:",
                font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
            ).pack(pady=(0, 8))
            
            btn_frame = ctk.CTkFrame(zadig_frame, fg_color="transparent")
            btn_frame.pack()

            ctk.CTkButton(
                btn_frame, text="⚡ Install USB Driver",
                fg_color=BLUE, hover_color="#3D8AD9",
                text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=12, weight="bold"),
                width=140, height=32,
                command=lambda: self._launch_zadig(install=True),
            ).pack(side="left", padx=(0, 8))

            if self._is_windows_11():
                ctk.CTkButton(
                    btn_frame, text="↩ Restore Default Driver",
                    fg_color="transparent", hover_color=BG_CARD_HOVER,
                    border_width=1, border_color=BORDER,
                    text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=12),
                    width=160, height=32,
                    command=lambda: self._launch_zadig(install=False),
                ).pack(side="left")

    def _missing_adb_message(self) -> str:
        if SYSTEM == "Windows":
            expected = os.path.join("tools", "windows", "scrcpy", "adb.exe")
        else:
            expected = os.path.join("tools", "macos", "platform-tools", "adb")
        return (
            f"Expected at:\n{expected}\n\n"
            "See README.md for setup instructions."
        )

    def _missing_scrcpy_message(self) -> str:
        if SYSTEM == "Windows":
            expected = os.path.join("tools", "windows", "scrcpy", "scrcpy.exe")
        else:
            expected = os.path.join("tools", "macos", "scrcpy", "scrcpy")
        return (
            f"Expected at:\n{expected}\n\n"
            "See README.md for setup instructions."
        )

    def _find_zadig(self) -> str | None:
        if SYSTEM != "Windows":
            return None
        path = os.path.join(TOOLS_DIR, "windows", "zadig-2.9.exe")
        if os.path.isfile(path):
            return path
        path = os.path.join(TOOLS_DIR, "windows", "zadig.exe")
        if os.path.isfile(path):
            return path
        return None

    def _is_windows_11(self) -> bool:
        if SYSTEM != "Windows":
            return False
        try:
            version = platform.version()
            build = int(version.split('.')[2]) if len(version.split('.')) > 2 else 0
            return build >= 22000
        except:
            return False

    def _launch_zadig(self, install: bool = True):
        zadig_path = self._find_zadig()
        if not zadig_path:
            self._show_toast("Zadig not found in tools/windows/", RED)
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("USB Driver Setup")
        dialog.geometry("450x280")
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG_DARK)
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 280) // 2
        dialog.geometry(f"450x280+{x}+{y}")
        
        ctk.CTkLabel(
            dialog, text="🔧",
            font=ctk.CTkFont(size=36),
        ).pack(pady=(20, 10))

        if install:
            title = "Install WinUSB Driver"
            instructions = (
                "Zadig will open. Follow these steps:\n\n"
                "1. Select your Android device from the dropdown\n"
                "   (Look for 'Android' or your phone model)\n"
                "2. Select 'WinUSB' as the target driver\n"
                "3. Click 'Replace Driver' or 'Install Driver'\n"
                "4. Wait for installation to complete\n"
                "5. Reconnect your device"
            )
        else:
            title = "Restore Default Driver"
            instructions = (
                "To restore the original Windows driver:\n\n"
                "1. In Zadig, go to Options → List All Devices\n"
                "2. Select your Android device\n"
                "3. Select 'USB Serial (CDC)' or original driver\n"
                "4. Click 'Reinstall Driver'\n"
                "5. Reconnect your device"
            )

        ctk.CTkLabel(
            dialog, text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            dialog, text=instructions,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            justify="left",
        ).pack(padx=30, pady=(0, 15))
        
        def open_zadig():
            dialog.destroy()
            try:
                if SYSTEM == "Windows":
                    import ctypes
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", zadig_path, None, None, 1
                    )
                else:
                    subprocess.Popen([zadig_path])
                self._show_toast("Zadig launched — follow the instructions", BLUE)
            except Exception as e:
                self._show_toast(f"Failed to launch Zadig: {e}", RED)
        
        ctk.CTkButton(
            dialog, text="Open Zadig",
            fg_color=BLUE, hover_color="#3D8AD9",
            text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=13, weight="bold"),
            width=120, height=36,
            command=open_zadig,
        ).pack()

    def _show_zadig_menu(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("USB Driver Options")
        dialog.geometry("320x200")
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG_DARK)
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 320) // 2
        y = (dialog.winfo_screenheight() - 200) // 2
        dialog.geometry(f"320x200+{x}+{y}")
        
        ctk.CTkLabel(
            dialog, text="🔧 USB Driver Options",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(20, 5))
        
        win11_text = " (Windows 11)" if self._is_windows_11() else ""
        ctk.CTkLabel(
            dialog, text=f"Choose an action{win11_text}:",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 15))

        ctk.CTkButton(
            dialog, text="⚡ Install WinUSB Driver",
            fg_color=BLUE, hover_color="#3D8AD9",
            text_color=TEXT_PRIMARY, font=ctk.CTkFont(size=13, weight="bold"),
            width=220, height=36,
            command=lambda: [dialog.destroy(), self._launch_zadig(install=True)],
        ).pack(pady=(0, 8))

        restore_color = YELLOW if self._is_windows_11() else "transparent"
        restore_text_color = BG_DARK if self._is_windows_11() else TEXT_SECONDARY
        ctk.CTkButton(
            dialog, text="↩ Restore Default Driver",
            fg_color=restore_color, hover_color="#E5C235" if self._is_windows_11() else BG_CARD_HOVER,
            border_width=0 if self._is_windows_11() else 1, border_color=BORDER,
            text_color=restore_text_color, font=ctk.CTkFont(size=13),
            width=220, height=36,
            command=lambda: [dialog.destroy(), self._launch_zadig(install=False)],
        ).pack(pady=(0, 8))

        ctk.CTkButton(
            dialog, text="Cancel",
            fg_color="transparent", hover_color=BG_CARD_HOVER,
            border_width=1, border_color=BORDER,
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=12),
            width=100, height=28,
            command=dialog.destroy,
        ).pack()

    def _update_tool_status(self):
        if self.adb_path:
            self.adb_badge.update_status("ADB ✓", ACCENT)
        else:
            self.adb_badge.update_status("ADB ✗", RED)

        if self.scrcpy_path:
            self.scrcpy_badge.update_status("scrcpy ✓", ACCENT)
        else:
            self.scrcpy_badge.update_status("scrcpy ✗", RED)

    def _start_polling(self):
        self._refresh_devices()
        self._poll_job = self.after(POLL_INTERVAL_MS, self._start_polling)

    def _refresh_devices(self):
        if not self.adb_path:
            self.adb_path = _find_bundled_adb()
        if not self.scrcpy_path:
            self.scrcpy_path = _find_bundled_scrcpy()
        if self.adb_path and self.scrcpy_path:
            self.tool_env = _build_env(self.adb_path, self.scrcpy_path)
        self._update_tool_status()

        if not self.adb_path:
            self._show_empty()
            return
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        devices = get_adb_devices(self.adb_path)
        self.after(0, lambda: self._update_device_list(devices))

    def _update_device_list(self, devices: list[dict]):
        current_serials = {d["serial"] for d in self.current_devices}
        new_serials = {d["serial"] for d in devices}

        if current_serials == new_serials and len(devices) == len(self.current_devices):
            self._update_count(len(devices))
            return

        self.current_devices = devices
        self._update_count(len(devices))

        for card in self.device_cards:
            card.destroy()
        self.device_cards.clear()

        if not devices:
            self._show_empty()
            return

        self.empty_frame.pack_forget()

        for device in devices:
            card = DeviceCard(self.scroll_frame, device, self._on_device_click)
            card.pack(fill="x", pady=(0, 8))
            self.device_cards.append(card)

    def _update_count(self, count: int):
        if count == 0:
            self.device_count_label.configure(text="")
        elif count == 1:
            self.device_count_label.configure(text="1 device", text_color=ACCENT)
        else:
            self.device_count_label.configure(text=f"{count} devices", text_color=ACCENT)

    def _show_empty(self):
        for card in self.device_cards:
            card.destroy()
        self.device_cards.clear()
        self._build_empty_state()
        self.empty_frame.pack(fill="both", expand=True)

    def _on_device_click(self, device: dict, card: DeviceCard):
        serial = device["serial"]
        if not self.scrcpy_path:
            self._show_toast("scrcpy not found — see README for setup.", RED)
            card.reset_state()
            return

        if serial in self.active_mirrors:
            proc = self.active_mirrors[serial]
            if proc.poll() is None:
                self._show_toast(f"Already mirroring {device.get('model', serial)}", YELLOW)
                card.reset_state()
                return
            else:
                del self.active_mirrors[serial]

        self._show_toast(f"Launching mirror for {device.get('model', serial)}…", ACCENT)

        def launch():
            try:
                cmd = [
                    self.scrcpy_path,
                    "-s", serial,
                    "--window-title", f"Mirror: {device.get('model', serial)}",
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self.tool_env,
                    creationflags=_creation_flags(),
                )
                self.active_mirrors[serial] = proc
                
                def monitor_output(stream):
                    try:
                        for line in iter(stream.readline, b''):
                            line = line.decode('utf-8', errors='replace').strip()
                            if not line:
                                continue
                            print(f"[scrcpy] {line}")  # Debug output
                            line_lower = line.lower()
                            if "installing" in line_lower or "install " in line_lower:
                                self.after(0, lambda: self._update_apk_status("Installing...", YELLOW))
                            elif "success" in line_lower:
                                self.after(0, lambda: self._update_apk_status("Success!", ACCENT))
                                self.after(0, lambda: self._show_install_popup(True))
                                self.after(3000, lambda: self._update_apk_status("", TEXT_MUTED))
                            elif "failure" in line_lower or "failed" in line_lower or "error" in line_lower:
                                self.after(0, lambda: self._update_apk_status("Failed!", RED))
                                self.after(0, lambda: self._show_install_popup(False))
                                self.after(3000, lambda: self._update_apk_status("", TEXT_MUTED))
                    except:
                        pass

                stdout_thread = threading.Thread(target=monitor_output, args=(proc.stdout,), daemon=True)
                stderr_thread = threading.Thread(target=monitor_output, args=(proc.stderr,), daemon=True)
                stdout_thread.start()
                stderr_thread.start()

                proc.wait()
            except Exception as e:
                self.after(0, lambda: self._show_toast(f"Error: {e}", RED))
            finally:
                self.active_mirrors.pop(serial, None)
                self.after(0, card.reset_state)

        threading.Thread(target=launch, daemon=True).start()

    def _update_apk_status(self, message: str, color: str):
        self.apk_status_label.configure(text=message, text_color=color)

    def _show_install_popup(self, success: bool):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Installation Completed")
        dialog.geometry("280x120")
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG_DARK)
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 280) // 2
        y = (dialog.winfo_screenheight() - 120) // 2
        dialog.geometry(f"280x120+{x}+{y}")
        
        if success:
            icon = "✓"
            message = "Success!"
            color = ACCENT
        else:
            icon = "✗"
            message = "Failed!"
            color = RED

        msg_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        msg_frame.pack(pady=(25, 15))
        
        ctk.CTkLabel(
            msg_frame, text=icon,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=color,
        ).pack(side="left", padx=(0, 8))
        
        ctk.CTkLabel(
            msg_frame, text=message,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=color,
        ).pack(side="left")

        ctk.CTkButton(
            dialog, text="OK",
            fg_color=color, hover_color=ACCENT_DIM if success else "#CC5555",
            text_color=BG_DARK if success else TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            width=100, height=32,
            command=dialog.destroy,
        ).pack()

    def _show_toast(self, message: str, color: str = TEXT_SECONDARY):
        toast = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=8, border_width=1, border_color=color)
        toast.place(relx=0.5, rely=0.95, anchor="center")
        ctk.CTkLabel(
            toast, text=message, font=ctk.CTkFont(size=13), text_color=color,
        ).pack(padx=16, pady=8)
        self.after(3000, toast.destroy)

    def destroy(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
        for serial, proc in self.active_mirrors.items():
            if proc.poll() is None:
                proc.terminate()
        super().destroy()

if __name__ == "__main__":
    app = AndroidMirrorApp()
    app.mainloop()
