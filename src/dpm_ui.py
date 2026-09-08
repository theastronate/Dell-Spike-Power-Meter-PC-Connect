import customtkinter as ctk
import serial
import serial.tools.list_ports
import threading
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import os
import ctypes
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
        self.history_v = deque([0.0]*50, maxlen=50)
        self.history_i = deque([0.0]*50, maxlen=50)
        self.history_p = deque([0.0]*50, maxlen=50)
        self.max_current = 0.0
        self.ser = None
        self.running = False
        self.is_held = False

        # Scaling state
        self._scalable_labels = []   # (widget, font_name, base_size, style)
        self._scalable_pack = []     # (widget, {base pack kwargs})
        self._quadrant_refs = []     # (slot_labels, unit_lbl, header_lbl, quadrant_frame)
        self._resize_after_id = None
        self._last_scale = 0.0
        self._layout_base_width = BASE_WIDTH

        # --- 2. UI LAYOUT ---
        self.conn_frame = ctk.CTkFrame(self)
        self.conn_frame.pack(fill="x", padx=10, pady=5)
        self._scalable_pack.append((self.conn_frame, {"fill": "x", "padx": 10, "pady": 5}))

        self.port_var = ctk.StringVar(value="Select Port")
        self.port_menu = ctk.CTkOptionMenu(self.conn_frame, variable=self.port_var, values=self.get_ports())
        self.port_menu.pack(side="left", padx=10, pady=10)
        self._scalable_pack.append((self.port_menu, {"side": "left", "padx": 10, "pady": 10}))

        self.refresh_btn = ctk.CTkButton(self.conn_frame, text="Refresh", width=60, command=self.refresh_ports)
        self.refresh_btn.pack(side="left", padx=5)
        self._scalable_pack.append((self.refresh_btn, {"side": "left", "padx": 5}))

        self.connect_btn = ctk.CTkButton(self.conn_frame, text="Connect", fg_color="green", command=self.toggle_connection)
        self.connect_btn.pack(side="left", padx=10)
        self._scalable_pack.append((self.connect_btn, {"side": "left", "padx": 10}))

        self.status_dot = ctk.CTkLabel(self.conn_frame, text="●", text_color="red", font=("Arial", 24))
        self.status_dot.pack(side="right", padx=10)
        self._scalable_pack.append((self.status_dot, {"side": "right", "padx": 10}))
        self._scalable_labels.append((self.status_dot, "Arial", 24, ""))

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

        self.fig, self.ax = plt.subplots(figsize=(5, 3), dpi=100)
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
        self.bind("<Configure>", self._on_resize)
        self._resize_after_id = self.after(100, self._apply_scale)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if settings["maximized"]:
            self.state("zoomed")

    def _load_window_settings(self):
        defaults = {"width": BASE_WIDTH, "height": BASE_HEIGHT, "maximized": False}
        try:
            config = configparser.ConfigParser()
            config.read_string(self._settings_path.read_text(encoding="utf-8"))
            settings = config["window"]
            for key in ("width", "height"):
                value = settings.getint(key)
                if value is None or not 100 <= value <= 20000:
                    return defaults
            return {"width": settings.getint("width"), "height": settings.getint("height"),
                    "maximized": settings.getboolean("maximized", fallback=False)}
        except (OSError, ValueError, KeyError, configparser.Error):
            return defaults

    def _remember_normal_size(self):
        if self.state() == "normal" and self.winfo_width() > 1 and self.winfo_height() > 1:
            # Persist logical dimensions so reopening at another DPI scales once.
            dpi_scale = self._get_window_scaling()
            self._normal_size = (round(self.winfo_width() / dpi_scale),
                                 round(self.winfo_height() / dpi_scale))

    def _on_close(self):
        self._remember_normal_size()
        settings = {"width": self._normal_size[0], "height": self._normal_size[1],
                    "maximized": self.state() == "zoomed"}
        try:
            config = configparser.ConfigParser()
            config["window"] = {key: str(value) for key, value in settings.items()}
            temporary_path = self._settings_path.with_suffix(".tmp")
            with temporary_path.open("w", encoding="utf-8") as settings_file:
                config.write(settings_file)
            temporary_path.replace(self._settings_path)
        except OSError as e:
            print(f"Could not save window settings: {e}")
        self.running = False
        if self.ser:
            self.ser.close()
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        plt.close(self.fig)
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

        # --- Resize matplotlib figure proportionally ---
        fig_w = max(2, (w - 20) / 100)
        fig_h = max(1.5, (h * 0.30) / 100)
        self.fig.set_size_inches(fig_w, fig_h)
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

    def reset_max(self):
        self.max_current = 0.0
        self.update_slots(self.max_slots, "00.00")

    def toggle_hold(self):
        self.is_held = not self.is_held
        self.hold_btn.configure(
            text="RESUME" if self.is_held else "HOLD GRAPH",
            fg_color="orange" if self.is_held else "#5d6d7e"
        )

    def get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()] or ["No Ports Found"]

    def refresh_ports(self):
        new_ports = self.get_ports()
        self.port_menu.configure(values=new_ports)
        if new_ports:
            self.port_var.set(new_ports[0])

    def toggle_connection(self):
        if not self.running:
            port = self.port_var.get()
            if port in ["No Ports Found", "Select Port"]:
                return
            try:
                self.ser = serial.Serial(port, 115200, timeout=0.1)
                self.running = True
                self.connect_btn.configure(text="Disconnect", fg_color="red")
                self.status_dot.configure(text_color="green")
                threading.Thread(target=self.listen_serial, daemon=True).start()
            except Exception as e:
                self.raw_data_lbl.configure(text=f"Error: {e}")
        else:
            self.running = False
            if self.ser:
                self.ser.close()
            self.connect_btn.configure(text="Connect", fg_color="green")
            self.status_dot.configure(text_color="red")

    def listen_serial(self):
        while self.running:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self.after(0, lambda l=line: self.raw_data_lbl.configure(text=l))
                        parts = line.split(',')
                        if len(parts) >= 3:
                            self.after(0, self.process_data, parts[0], parts[1], parts[2])
            except:
                break

    def process_data(self, v_str, i_str, p_str):
        try:
            v, i, p = float(v_str), float(i_str), float(p_str)
            self.update_slots(self.v_slots, f"{v:05.2f}")
            self.update_slots(self.i_slots, f"{i:05.2f}")
            self.update_slots(self.p_slots, f"{p:05.1f}")

            if i > self.max_current:
                self.max_current = i
                self.update_slots(self.max_slots, f"{self.max_current:05.2f}")

            if self.is_held:
                return

            self.history_v.append(v)
            self.history_i.append(i)
            self.history_p.append(p)

            self.line_v.set_visible(self.show_v.get())
            self.line_i.set_visible(self.show_i.get())
            self.line_p.set_visible(self.show_p.get())

            if self.show_v.get(): self.line_v.set_ydata(list(self.history_v))
            if self.show_i.get(): self.line_i.set_ydata(list(self.history_i))
            if self.show_p.get(): self.line_p.set_ydata(list(self.history_p))

            self.ax.relim()
            visible_data = []
            if self.show_v.get(): visible_data.extend(list(self.history_v))
            if self.show_i.get(): visible_data.extend(list(self.history_i))
            if self.show_p.get(): visible_data.extend(list(self.history_p))

            if visible_data and max(visible_data) > 0:
                self.ax.set_ylim(0, max(visible_data) * 1.1)
            else:
                self.ax.set_ylim(0, 10)

            self.canvas.draw_idle()
        except:
            pass

if __name__ == "__main__":
    app = PowerMeterApp()
    app.mainloop()
