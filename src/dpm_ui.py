import customtkinter as ctk
import serial
import serial.tools.list_ports
import threading
import queue
import math
from collections import deque
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import os
import ctypes
from ctypes import wintypes
import configparser
import sys
from pathlib import Path

# Base design dimensions (original geometry)
BASE_WIDTH = 920
BASE_HEIGHT = 980

class PowerMeterApp(ctk.CTk):
    def __init__(self):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SpikePowerMeter.DesktopApp"
            )
        except (AttributeError, OSError):
            pass

        super().__init__()
        self.title("Spike Power Meter")
        settings_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
        self._settings_path = settings_dir / "dpm_ui.ini"
        settings = self._load_window_settings()
        self._last_port = settings["last_port"]
        self.autoconnect_var = ctk.BooleanVar(value=settings["autoconnect"])
        self._normal_size = (settings["width"], settings["height"])
        self.geometry(f'{settings["width"]}x{settings["height"]}')
        ctk.set_appearance_mode("dark")

        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "DellPowerMeter.ico",
            )
            self.iconbitmap(icon_path)
        except Exception as e:
            print(f"Icon error: {e}")

        # --- 1. FONT LOADING ---
        self.font_name = "Arial"
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            font_path = os.path.join(script_dir, "digital-7.ttf")
            if os.path.exists(font_path):
                ctk.FontManager.load_font(font_path)
                self.font_name = "Digital-7"
            else:
                print(f"Font file not found at: {font_path}")
        except Exception as e:
            print(f"Font error: {e}")

        # Data & Control State
        self.is_held = False
        self.sources = [self._new_source(), self._new_source()]
        self.history_v, self.history_i, self.history_p = self.sources[0]["history"]
        self.active_source = settings["active_source"] if settings["second_enabled"] else 0
        self._serial_events = queue.Queue(maxsize=1000)
        self.second_enabled_var = ctk.BooleanVar(value=settings["second_enabled"])
        self.source_ports = [ctk.StringVar(value=settings["last_port"] or "Select Port"),
                             ctk.StringVar(value=settings["second_port"] or "Select Port")]
        self.source_names = [ctk.StringVar(value=settings["first_name"]),
                             ctk.StringVar(value=settings["second_name"])]

        # Scaling state
        self._scalable_labels = []   # (widget, font_name, base_size, style)
        self._scalable_pack = []     # (widget, {base pack kwargs})
        self._quadrant_refs = []     # (slot_labels, unit_lbl, header_lbl, quadrant_frame)
        self._resize_after_id = None
        self._last_scale = 0.0
        self._layout_base_width = BASE_WIDTH

        # --- 2. UI LAYOUT ---
        self.conn_frame = ctk.CTkFrame(
            self, fg_color="#20262e", corner_radius=12,
            border_width=1, border_color="#343e49")
        self.conn_frame.pack(fill="x", padx=20, pady=(12, 4))
        self._scalable_pack.append((self.conn_frame, {"fill": "x", "padx": 20, "pady": (12, 4)}))
        self.conn_frame.grid_columnconfigure(0, weight=1)
        self._connections_expanded = not bool(settings["last_port"])

        header = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="POWER SOURCE", anchor="w", height=16,
                     font=("Arial", 10, "bold"), text_color="#94a5b5").grid(
                         row=0, column=0, sticky="w")
        self.source_title = ctk.CTkLabel(header, anchor="w", height=28,
                                        font=("Arial", 18, "bold"), text_color="#edf4fa")
        self.source_title.grid(row=1, column=0, sticky="ew")
        self.connection_summary = ctk.CTkLabel(header, anchor="w", height=18,
                                              font=("Arial", 11))
        self.connection_summary.grid(row=2, column=0, sticky="w")
        self.active_connect_btn = ctk.CTkButton(
            header, width=100, height=32, corner_radius=7,
            command=lambda: self.toggle_connection(self.active_source))
        self.active_connect_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        self.manage_btn = ctk.CTkButton(
            header, text="Manage devices", width=100, height=24,
            fg_color="transparent", hover_color="#303c49", text_color="#a9c9e2",
            font=("Arial", 11), command=self._toggle_connection_details)
        self.manage_btn.grid(row=2, column=1, padx=(12, 0))

        self.display_row = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        self.display_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.display_row.grid_columnconfigure((0, 1), weight=1, uniform="sources")
        self.source_buttons = []
        for index in range(2):
            button = ctk.CTkButton(
                self.display_row, width=100, height=36, corner_radius=7, border_width=1,
                command=lambda i=index: self._select_source(i))
            button.grid(row=0, column=index, sticky="ew", padx=4)
            self.source_buttons.append(button)

        self.connection_details = ctk.CTkFrame(
            self.conn_frame, fg_color="#191f26", corner_radius=8)
        self.connection_details.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.connection_details.grid_columnconfigure(0, weight=1)
        caption = ctk.CTkFrame(self.connection_details, fg_color="transparent")
        caption.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ctk.CTkLabel(caption, text="Device connections", font=("Arial", 12, "bold"),
                     text_color="#d1dce6").pack(side="left")
        self.refresh_btn = ctk.CTkButton(
            caption, text="Refresh ports", width=85, height=24,
            fg_color="transparent", hover_color="#303c49", text_color="#a9c9e2",
            command=self.refresh_ports)
        self.refresh_btn.pack(side="right")
        self.device_rows = []
        port_menus, connect_buttons, status_labels = [], [], []
        for index in range(2):
            row = ctk.CTkFrame(self.connection_details, fg_color="transparent")
            row.grid(row=index + 1, column=0, sticky="ew", padx=12, pady=5)
            row.grid_columnconfigure(1, weight=1)
            self.device_rows.append(row)
            status = ctk.CTkLabel(row, text="\u25cf", width=16, font=("Arial", 14))
            status.grid(row=0, column=0, padx=(0, 6))
            status_labels.append(status)
            entry = ctk.CTkEntry(
                row, textvariable=self.source_names[index], width=100, height=32,
                fg_color="#252e38", border_color="#3a4856", border_width=1,
                corner_radius=6)
            entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
            entry.bind("<FocusOut>", self._names_changed)
            entry.bind("<Return>", self._names_changed)
            menu = ctk.CTkOptionMenu(
                row, variable=self.source_ports[index], values=self.get_ports(), width=100,
                height=32, fg_color="#303e4c", button_color="#3a4b5c",
                button_hover_color="#485f73", corner_radius=6)
            menu.grid(row=0, column=2, padx=(0, 8))
            port_menus.append(menu)
            button = ctk.CTkButton(row, width=90, height=32, corner_radius=6,
                                   command=lambda i=index: self.toggle_connection(i))
            button.grid(row=0, column=3)
            connect_buttons.append(button)
        self.port_var = self.source_ports[0]
        self.port_menu, self.second_port_menu = port_menus
        self.connect_btn, self.second_connect_btn = connect_buttons
        self.status_dot, self.second_status = status_labels
        self.second_row = self.device_rows[1]
        footer = ctk.CTkFrame(self.connection_details, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 12))
        self.autoconnect_checkbox = ctk.CTkSwitch(
            footer, text="Connect on startup", variable=self.autoconnect_var,
            command=self._save_settings, progress_color="#387faa",
            switch_width=32, switch_height=18, font=("Arial", 11))
        self.autoconnect_checkbox.pack(side="left")
        self.second_device_btn = ctk.CTkButton(
            footer, width=140, height=26, fg_color="transparent", hover_color="#303c49",
            text_color="#a9c9e2", font=("Arial", 11), command=self._change_second_device)
        self.second_device_btn.pack(side="right")
        self._update_source_controls()

        # --- 3. RECREATED DIGITAL DISPLAY ---
        lcd_blue_bg = "#82caff"
        lcd_text_color = "#001e3c"
        self.display_container = ctk.CTkFrame(self, fg_color="#333", border_width=4, border_color="#555")
        self.display_container.pack(fill="x", padx=20, pady=10)
        self._scalable_pack.append((self.display_container, {"fill": "x", "padx": 20, "pady": 10}))

        self.lcd_frame = ctk.CTkFrame(self.display_container, fg_color=lcd_blue_bg, corner_radius=0)
        self.lcd_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self._scalable_pack.append((self.lcd_frame, {"fill": "both", "expand": True, "padx": 5, "pady": 5}))
        self.lcd_frame.grid_columnconfigure((0, 1), weight=1)
        self.lcd_frame.grid_rowconfigure((0, 1), weight=1)

        self.v_slots = self.create_lcd_quadrant(0, 0, "VOLTAGE", 5, "V", lcd_text_color, dot_idx=2)
        self.i_slots = self.create_lcd_quadrant(0, 1, "CURRENT", 5, "A", lcd_text_color, dot_idx=2)
        self.p_slots = self.create_lcd_quadrant(1, 0, "POWER", 5, "W", lcd_text_color, dot_idx=3)
        self.max_slots = self.create_lcd_quadrant(1, 1, "MAX CURRENT", 5, "MAX", lcd_text_color, dot_idx=2)

        self.update_slots(self.v_slots, "00.00")
        self.update_slots(self.i_slots, "00.00")
        self.update_slots(self.p_slots, "000.0")
        self.update_slots(self.max_slots, "00.00")

        # --- 4. CONTROLS & GRAPH ---
        self.ctrl_frame = ctk.CTkFrame(self)
        self.ctrl_frame.pack(fill="x", padx=10, pady=5)
        self._scalable_pack.append((self.ctrl_frame, {"fill": "x", "padx": 10, "pady": 5}))

        self.show_v = ctk.BooleanVar(value=False)
        self.show_i = ctk.BooleanVar(value=True)
        self.show_p = ctk.BooleanVar(value=False)

        sw_v = ctk.CTkSwitch(self.ctrl_frame, text="Show V", variable=self.show_v, progress_color="cyan")
        sw_v.pack(side="left", padx=10)
        self._scalable_pack.append((sw_v, {"side": "left", "padx": 10}))

        sw_i = ctk.CTkSwitch(self.ctrl_frame, text="Show I", variable=self.show_i, progress_color="lightgreen")
        sw_i.pack(side="left", padx=10)
        self._scalable_pack.append((sw_i, {"side": "left", "padx": 10}))

        sw_p = ctk.CTkSwitch(self.ctrl_frame, text="Show W", variable=self.show_p, progress_color="orange")
        sw_p.pack(side="left", padx=10)
        self._scalable_pack.append((sw_p, {"side": "left", "padx": 10}))

        self.reset_btn = ctk.CTkButton(self.ctrl_frame, text="RESET MAX", fg_color="#922b21", command=self.reset_max)
        self.reset_btn.pack(side="right", padx=10)
        self._scalable_pack.append((self.reset_btn, {"side": "right", "padx": 10}))

        self.hold_btn = ctk.CTkButton(self.ctrl_frame, text="HOLD GRAPH", fg_color="#5d6d7e", command=self.toggle_hold)
        self.hold_btn.pack(side="right", padx=10)
        self._scalable_pack.append((self.hold_btn, {"side": "right", "padx": 10}))

        # Construct the embedded figure directly: pyplot.subplots() also creates
        # a separate Tk window/manager, which can keep the event loop alive.
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor('#1a1a1a')
        self.ax.set_facecolor('#1a1a1a')
        self.line_v, = self.ax.plot(range(50), list(self.history_v), color='cyan', visible=False)
        self.line_i, = self.ax.plot(range(50), list(self.history_i), color='lightgreen', visible=True)
        self.line_p, = self.ax.plot(range(50), list(self.history_p), color='orange', visible=False)
        self.ax.tick_params(colors='white')
        self.ax.grid(True, color='#333333')
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=5)
        self._scalable_pack.append((self.canvas.get_tk_widget(), {"fill": "both", "expand": True, "padx": 10, "pady": 5}))

        self.raw_data_lbl = ctk.CTkLabel(self, text="Ready", font=("Courier", 12))
        self.raw_data_lbl.pack(pady=5)
        self._scalable_pack.append((self.raw_data_lbl, {"pady": 5}))
        self._scalable_labels.append((self.raw_data_lbl, "Courier", 12, ""))

        # Measure the natural layout before applying responsive scaling. Font
        # metrics (including the fallback font) can require more than 920 units.
        self.update_idletasks()
        widget_scale = self.lcd_frame._get_widget_scaling()
        self._layout_base_width = max(
            BASE_WIDTH,
            self.display_container.winfo_reqwidth() / widget_scale + 40 + 24,
        )

        # Bind resize event and fit the initial display even at 100% DPI.
        self._restore_position(settings["x"], settings["y"])
        self.bind("<Configure>", self._on_resize)
        self._resize_after_id = self.after(100, self._apply_scale)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if settings["maximized"]:
            self.state("zoomed")
        self.after(50, self._drain_serial_events)
        if self.autoconnect_var.get():
            self.after(250, self._autoconnect)

    def _load_window_settings(self):
        defaults = {"width": BASE_WIDTH, "height": BASE_HEIGHT, "maximized": False,
                    "x": None, "y": None, "last_port": "", "autoconnect": False,
                    "second_enabled": False, "second_port": "", "first_name": "Device 1",
                    "second_name": "Device 2", "active_source": 0}
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read_string(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, configparser.Error):
            return defaults
        for key in defaults:
            section = "window" if key in ("width", "height", "x", "y", "maximized") else "connection"
            try:
                if key in ("maximized", "autoconnect", "second_enabled"):
                    defaults[key] = config.getboolean(section, key, fallback=defaults[key])
                elif key in ("last_port", "second_port", "first_name", "second_name"):
                    defaults[key] = config.get(section, key, fallback=defaults[key]).strip()
                elif key == "active_source":
                    defaults[key] = 1 if config.getint(section, key, fallback=0) == 1 else 0
                else:
                    value = config.getint(section, key, fallback=defaults[key])
                    if key in ("x", "y") or 100 <= value <= 20000:
                        defaults[key] = value
            except (ValueError, configparser.Error):
                pass
        return defaults

    def _window_rect(self):
        if sys.platform == "win32":
            rect = wintypes.RECT()
            hwnd = wintypes.HWND(int(self.frame(), 0))
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return rect.left, rect.top, rect.right, rect.bottom
        x, y = self.winfo_x(), self.winfo_y()
        return x, y, x + self.winfo_width(), y + self.winfo_height()

    def _monitor_work_areas(self):
        areas = []
        if sys.platform == "win32":
            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            callback_type = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
            )

            @callback_type
            def collect(monitor, dc, rect, data):
                info = MonitorInfo()
                info.cbSize = ctypes.sizeof(info)
                if ctypes.windll.user32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
                    work = info.rcWork
                    area = (work.left, work.top, work.right, work.bottom)
                    if info.dwFlags & 1:  # Primary monitor is the safe fallback.
                        areas.insert(0, area)
                    else:
                        areas.append(area)
                return True

            ctypes.windll.user32.EnumDisplayMonitors(None, None, collect, 0)
        return areas or [(0, 0, self.winfo_screenwidth(), self.winfo_screenheight())]

    def _restore_position(self, x, y):
        areas = self._monitor_work_areas()
        left, top, right, bottom = self._window_rect()
        width, height = right - left, bottom - top
        # Require the whole frame to fit, including the title bar and borders.
        if x is None or y is None or not any(
            l <= x and t <= y and x + width <= r and y + height <= b
            for l, t, r, b in areas
        ):
            l, t, r, b = areas[0]
            scale = self._get_window_scaling()
            border_w = width - self.winfo_width()
            border_h = height - self.winfo_height()
            self._normal_size = (
                min(self._normal_size[0], int((r - l - border_w - 40) / scale)),
                min(self._normal_size[1], int((b - t - border_h - 40) / scale)),
            )
            self.geometry(f"{self._normal_size[0]}x{self._normal_size[1]}")
            self.update_idletasks()
            x, y = l + 20, t + 20
        if sys.platform == "win32":
            # Native coordinates support monitors left of/above the primary.
            ctypes.windll.user32.SetWindowPos(
                wintypes.HWND(int(self.frame(), 0)), None, x, y, 0, 0, 0x0015,
            )  # NOSIZE | NOZORDER | NOACTIVATE
        else:
            self.tk.call("wm", "geometry", self._w, f"+{x}+{y}")
        self._normal_position = (x, y)

    def _remember_normal_size(self):
        if self.state() == "normal" and self.winfo_width() > 1 and self.winfo_height() > 1:
            # Persist logical dimensions so reopening at another DPI scales once.
            dpi_scale = self._get_window_scaling()
            self._normal_size = (round(self.winfo_width() / dpi_scale),
                                 round(self.winfo_height() / dpi_scale))
            self._normal_position = self._window_rect()[:2]

    def _save_settings(self):
        self._remember_normal_size()
        settings = {"width": self._normal_size[0], "height": self._normal_size[1],
                    "x": self._normal_position[0], "y": self._normal_position[1],
                    "maximized": self.state() == "zoomed"}
        try:
            config = configparser.ConfigParser(interpolation=None)
            config["window"] = {key: str(value) for key, value in settings.items()}
            config["connection"] = {
                "last_port": self.source_ports[0].get(),
                "autoconnect": str(self.autoconnect_var.get()),
                "second_enabled": str(self.second_enabled_var.get()),
                "second_port": self.source_ports[1].get(),
                "first_name": self.source_names[0].get(),
                "second_name": self.source_names[1].get(),
                "active_source": str(self.active_source),
            }
            temporary_path = self._settings_path.with_suffix(".tmp")
            with temporary_path.open("w", encoding="utf-8") as settings_file:
                config.write(settings_file)
            temporary_path.replace(self._settings_path)
        except OSError as e:
            print(f"Could not save settings: {e}")

    def _on_close(self):
        self._save_settings()
        try:
            for index in range(2):
                self._disconnect_source(index)
        except (OSError, serial.SerialException) as e:
            print(f"Could not close serial port: {e}")
        finally:
            # Explicitly stop the event loop, even if resource cleanup fails.
            self.quit()
            self.destroy()

    def _on_resize(self, event):
        if event.widget is not self:
            return
        self._remember_normal_size()
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(100, self._apply_scale)

    def _scaled_pad(self, base_val, scale):
        """Scale a padding value (int or tuple) proportionally."""
        if isinstance(base_val, tuple):
            return tuple(max(0, int(v * scale)) for v in base_val)
        return max(0, int(base_val * scale))

    def _apply_scale(self):
        self._resize_after_id = None
        w = self.winfo_width()
        h = self.winfo_height()
        # Tk reports physical pixels, while CTk geometry and font sizes use
        # logical units. Remove CTk's current monitor/window scaling here so
        # its automatic font scaling does not apply the DPI factor twice.
        window_scale = self._get_window_scaling()
        scale = min(w / window_scale / self._layout_base_width,
                    h / window_scale / BASE_HEIGHT)
        if abs(scale - self._last_scale) < 0.005:
            return
        self._last_scale = scale

        # --- Scale fonts ---
        digit_size    = max(10, int(110 * scale))
        unit_size     = max(8,  int(30  * scale))
        label_size    = max(8,  int(24  * scale))
        unit_pady_top = max(5,  int(45  * scale))
        unit_padx     = max(2,  int(10  * scale))

        for slot_list, unit_lbl, header_lbl, quad_frame in self._quadrant_refs:
            for lbl in slot_list:
                lbl.configure(font=(self.font_name, digit_size))
                if lbl.cget("width") != 0:
                    lbl.configure(width=max(10, int(65 * scale)))
            unit_lbl.configure(font=("Arial", unit_size, "bold"))
            unit_lbl.pack(side="left", padx=unit_padx, pady=(unit_pady_top, 0))
            header_lbl.configure(font=("Arial", label_size, "bold"))
            # Scale the quadrant grid cell padding
            quad_frame.grid(
                row=quad_frame.grid_info()["row"],
                column=quad_frame.grid_info()["column"], sticky="nsew",
                padx=max(2, int(20 * scale)),
                pady=max(2, int(20 * scale))
            )

        # --- Scale generic label fonts ---
        for widget, fname, base_size, style in self._scalable_labels:
            new_size = max(8, int(base_size * scale))
            font_spec = (fname, new_size, style) if style else (fname, new_size)
            widget.configure(font=font_spec)

        # --- Scale all tracked pack padding ---
        for widget, base_kwargs in self._scalable_pack:
            new_kwargs = {}
            for k, v in base_kwargs.items():
                if k in ("padx", "pady"):
                    new_kwargs[k] = self._scaled_pad(v, scale)
                else:
                    new_kwargs[k] = v
            widget.pack(**new_kwargs)

        # FigureCanvasTkAgg resizes the figure and its backing image together
        # when Tk allocates the canvas. Resizing only the figure here leaves
        # stale pixels (including old axes) in the larger backing image.
        self.canvas.draw_idle()

    def create_lcd_quadrant(self, r, c, label_text, num_slots, unit_text, color, dot_idx):
        f = ctk.CTkFrame(self.lcd_frame, fg_color="transparent")
        f.grid(row=r, column=c, sticky="nsew", padx=20, pady=20)

        top_row = ctk.CTkFrame(f, fg_color="transparent")
        top_row.pack()

        slots_container = ctk.CTkFrame(top_row, fg_color="transparent")
        slots_container.pack(side="left")

        labels = []
        for i in range(num_slots):
            is_dot = (i == dot_idx)
            w = 0 if is_dot else 65
            lbl = ctk.CTkLabel(slots_container, text="-", font=(self.font_name, 110), text_color=color, width=w)
            lbl.pack(side="left")
            labels.append(lbl)

        u_lbl = ctk.CTkLabel(top_row, text=unit_text, font=("Arial", 30, "bold"), text_color=color)
        u_lbl.pack(side="left", padx=10, pady=(45, 0))

        l_lbl = ctk.CTkLabel(f, text=label_text, font=("Arial", 24, "bold"), text_color=color)
        l_lbl.pack()

        self._quadrant_refs.append((labels, u_lbl, l_lbl, f))
        return labels

    def update_slots(self, slots_list, value_str):
        value_str = str(value_str).replace("-", "0")
        for i, char in enumerate(value_str):
            if i < len(slots_list):
                slots_list[i].configure(text=char)

    @staticmethod
    def _new_source():
        return {"serial": None, "stop": None, "generation": 0,
                "history": [deque([0.0] * 50, maxlen=50) for _ in range(3)],
                "latest": (0.0, 0.0, 0.0), "max": 0.0, "raw": "Ready"}

    def _source_labels(self):
        count = 2 if self.second_enabled_var.get() else 1
        return [f"{i + 1}: {self.source_names[i].get().strip() or f'Device {i + 1}'}"
                for i in range(count)]

    def _names_changed(self, event=None):
        self._update_source_controls()
        self._save_settings()

    def _update_source_controls(self):
        dual = self.second_enabled_var.get()
        if dual:
            self.display_row.grid()
            self.second_row.grid()
        else:
            self.display_row.grid_remove()
            self.second_row.grid_remove()
        if self._connections_expanded:
            self.connection_details.grid()
        else:
            self.connection_details.grid_remove()
        self.manage_btn.configure(text="Done" if self._connections_expanded else "Manage devices")
        self.second_device_btn.configure(text="Remove second device" if dual else "+ Add second device")
        for index, button in enumerate(self.source_buttons):
            selected = index == self.active_source
            name = self.source_names[index].get().strip() or f"Device {index + 1}"
            button.configure(
                text=("\u2713  " if selected else "") + name,
                fg_color="#254c68" if selected else "#252e38",
                hover_color="#315f80" if selected else "#303e4c",
                border_color="#70b9e8" if selected else "#3a4856",
                text_color="#edf7ff" if selected else "#a5b5c3")
        for index, menu, button, status in [
                (0, self.port_menu, self.connect_btn, self.status_dot),
                (1, self.second_port_menu, self.second_connect_btn, self.second_status)]:
            connected = self.sources[index]["serial"] is not None
            enabled = index == 0 or dual
            menu.configure(state="normal" if enabled and not connected else "disabled")
            style = dict(text="Disconnect" if connected else "Connect",
                         fg_color="#303e4c" if connected else "#287cae",
                         hover_color="#435467" if connected else "#3494cd",
                         text_color="#edf4fa")
            button.configure(state="normal" if enabled else "disabled", **style)
            status.configure(text_color="#66c9a1" if connected else "#778795")
            if index == self.active_source:
                self.active_connect_btn.configure(**style)
        source = self.sources[self.active_source]
        name = self.source_names[self.active_source].get().strip() or f"Device {self.active_source + 1}"
        self.source_title.configure(text=name)
        connected = source["serial"] is not None
        port = self.source_ports[self.active_source].get()
        error = source["raw"].startswith(("Cannot connect", "Disconnected:", port + " is already"))
        state = "Connected" if connected else "Connection failed" if error else "Not connected"
        detail = f"  /  {port}" if port not in ("", "Select Port", "No Ports Found") else ""
        self.connection_summary.configure(
            text=f"\u25cf  {state}{detail}",
            text_color="#66c9a1" if connected else "#e0b47b" if error else "#94a5b5")

    def _toggle_connection_details(self):
        self._connections_expanded = not self._connections_expanded
        self._update_source_controls()
        self._save_settings()

    def _change_second_device(self):
        self.second_enabled_var.set(not self.second_enabled_var.get())
        self._toggle_second()

    def _toggle_second(self):
        if not self.second_enabled_var.get():
            self._disconnect_source(1)
            self.active_source = 0
        self._update_source_controls()
        self._render_source()
        self._save_settings()
        if self.second_enabled_var.get() and self.autoconnect_var.get():
            self._autoconnect()

    def _select_source(self, index):
        self.active_source = index
        self._update_source_controls()
        self._render_source()
        self._save_settings()

    def reset_max(self):
        self.sources[self.active_source]["max"] = 0.0
        self._render_source()

    def toggle_hold(self):
        self.is_held = not self.is_held
        self.hold_btn.configure(
            text="RESUME" if self.is_held else "HOLD GRAPH",
            fg_color="orange" if self.is_held else "#5d6d7e"
        )

    def get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()] or ["No Ports Found"]

    def refresh_ports(self):
        # Keep saved assignments when a device is absent; never substitute another meter.
        ports = self.get_ports()
        self.port_menu.configure(values=ports)
        self.second_port_menu.configure(values=ports)
        self._autoconnect()

    def _autoconnect(self):
        if not self.autoconnect_var.get():
            return
        for index in range(2 if self.second_enabled_var.get() else 1):
            if self.sources[index]["serial"] is None:
                self.toggle_connection(index)
        # If the remembered display is absent, show the connected device.
        if self.sources[self.active_source]["serial"] is None:
            for index, source in enumerate(self.sources):
                if source["serial"] is not None:
                    self.active_source = index
                    self._update_source_controls()
                    self._render_source()
                    break

    def toggle_connection(self, index=0):
        source = self.sources[index]
        if source["serial"] is not None:
            self._disconnect_source(index)
        elif index == 0 or self.second_enabled_var.get():
            port = self.source_ports[index].get()
            if port in ("", "No Ports Found", "Select Port"):
                return
            if any(other["serial"] is not None and other["serial"].port.lower() == port.lower()
                   for other in self.sources):
                source["raw"] = f"{port} is already connected as the other source."
            else:
                try:
                    connection = serial.Serial(port, 115200, timeout=0.1)
                    source["serial"] = connection
                    source["generation"] += 1
                    source["stop"] = threading.Event()
                    source["raw"] = f"Connected to {port}; waiting for data"
                    if index == 0:
                        self._last_port = port
                    threading.Thread(target=self.listen_serial,
                                     args=(index, connection, source["stop"], source["generation"]),
                                     daemon=True).start()
                except (OSError, serial.SerialException) as error:
                    source["raw"] = f"Cannot connect to {port}: {error}"
        self._update_source_controls()
        self._render_source()
        self._save_settings()

    def _disconnect_source(self, index):
        source = self.sources[index]
        connection = source["serial"]
        source["serial"] = None
        source["generation"] += 1
        if source["stop"] is not None:
            source["stop"].set()
        if connection is not None:
            try:
                connection.close()
            except (OSError, serial.SerialException):
                pass
        source["raw"] = "Disconnected"

    def listen_serial(self, index, connection, stop, generation):
        # Workers only touch their own connection and queue; Tk stays on the main thread.
        pending = b""
        while not stop.is_set():
            try:
                chunk = connection.read_until(b"\n")
                pending += chunk
                if not pending.endswith(b"\n"):
                    if len(pending) > 4096:
                        pending = b""
                    continue
                line = pending.decode("utf-8", errors="ignore").strip()
                pending = b""
                if line:
                    self._queue_serial_event((index, generation, "data", line), stop)
            except (OSError, serial.SerialException) as error:
                self._queue_serial_event((index, generation, "error", str(error)), stop)
                break

    def _queue_serial_event(self, event, stop):
        while not stop.is_set():
            try:
                self._serial_events.put(event, timeout=0.1)
                return
            except queue.Full:
                continue

    def _drain_serial_events(self):
        changed = False
        for _ in range(200):
            try:
                index, generation, kind, value = self._serial_events.get_nowait()
            except queue.Empty:
                break
            source = self.sources[index]
            if source["generation"] != generation:
                continue
            if kind == "error":
                self._disconnect_source(index)
                source["raw"] = f"Disconnected: {value}"
                self._update_source_controls()
            else:
                source["raw"] = value
                parts = value.split(",")
                if len(parts) >= 3:
                    self.process_data(*parts[:3], index=index)
            changed = changed or index == self.active_source
        if changed:
            self._render_source()
        self.after(50, self._drain_serial_events)

    def process_data(self, v_str, i_str, p_str, index=None):
        try:
            values = float(v_str), float(i_str), float(p_str)
        except ValueError:
            return
        if not all(math.isfinite(value) for value in values):
            return
        source = self.sources[self.active_source if index is None else index]
        source["latest"] = values
        source["max"] = max(source["max"], values[1])
        if not self.is_held:
            for history, value in zip(source["history"], values):
                history.append(value)

    def _render_source(self):
        source = self.sources[self.active_source]
        v, i, p = source["latest"]
        self.update_slots(self.v_slots, f"{v:05.2f}")
        self.update_slots(self.i_slots, f"{i:05.2f}")
        self.update_slots(self.p_slots, f"{p:05.1f}")
        self.update_slots(self.max_slots, f"{source['max']:05.2f}")
        self.raw_data_lbl.configure(text=f"{self._source_labels()[self.active_source]}: {source['raw']}")
        visible_data = []
        for line, visible, history in zip(
                (self.line_v, self.line_i, self.line_p),
                (self.show_v, self.show_i, self.show_p), source["history"]):
            line.set_visible(visible.get())
            line.set_ydata(list(history))
            if visible.get():
                visible_data.extend(history)
        self.ax.relim()
        self.ax.set_ylim(0, max(visible_data) * 1.1 if visible_data and max(visible_data) > 0 else 10)
        self.canvas.draw_idle()

if __name__ == "__main__":
    app = PowerMeterApp()
    app.mainloop()
