# 🔌 Spike Power Meter Digitizer (USB-C Pro Upgrade)

This is the USB-C upgraded version of my Dell power meter. You can build this [Dell/Alienware Laptop Power Meter Box](https://www.thingiverse.com/thing:7031863) by printing following the build list. This project replaces standard analog readouts with an **ESP32-C3** and an **INA226** high-side sensor, streaming live power data over **USB-C** to a custom Python dashboard.

## ✨ Features

- **Dual-Jack Support:** Compatible with 7.4mm and 4.5mm Dell/Alienware barrel chargers.
- **High Precision:** Uses the **INA226** via I2C with a **0.002 Ohm shunt** for accurate high-current readings (up to 25A).
- **Digital-7 Dashboard:** A custom Python UI built with `customtkinter` that mimics the classic blue LCD 7-segment display.
- **Live Graphing:** Real-time visual tracking of Voltage (V), Amps (I), and Watts (W).
- **Max Current Hold:** Automatically captures and holds peak amperage for diagnostic review.

---

## 🛠️ Hardware Setup

### Components

- **Microcontroller:** [ESP32-C3](https://amzn.to/4cqRlRE)
- **Sensor/Shunt:** [INA226 High-Side Current Sensor with R002 (0.002 Ohm)](https://amzn.to/4tzMGDz)
- **Enclosure:** [3D Printed Case via Thingiverse](https://www.thingiverse.com/thing:7031863)

### Wiring (ESP32-C3)

| INA226 Pin | ESP32-C3 Pin |
| :--------- | :----------- |
| VCC        | 5V           |
| GND        | GND          |
| SDA        | GPIO 8       |
| SCL        | GPIO 9       |

---

## 🚀 Quick Start Guide

### 1. Firmware Installation (PlatformIO)

Create a `platformio.ini` with the following configuration:

```ini
[env:esp32-c3-devkitm-1]
platform = espressif32
board = esp32-c3-devkitm-1
framework = arduino
monitor_speed = 115200
lib_deps = robtillaart/INA226 @ ^0.6.0
```

Flash the provided .cpp firmware to your ESP32-C3 via USB-C.

### 2. Python Dashboard Setup

Ensure you have Python 3.9+ installed, then:

## Clone the repository

git clone https://github.com
cd Dell-Power-Meter-PC-Connect

## Install dependencies

```
pip install -r requirements.txt
```

### 3. Running the App

Ensure the digital-7.ttf font file is in the project root, then run:

```
python dpm_ui.py
```

### 4. Building a standalone Windows executable

From PowerShell in the project root, run:

```powershell
.\build-exe.ps1
```

The single-file, windowed application is written to `dist\Spike Power Meter.exe`.
It embeds Python, the Python packages, CustomTkinter assets, and the Digital-7
font, so the target Windows computer does not need Python or supporting files.
The build also places `dpm_ui.ini` beside the executable to store the window
size, screen position, maximized state, both device COM ports, friendly names, selected display source,
and the Autoconnect checkbox setting. A saved position that no longer fits on
a connected monitor is reset to a safe location on the primary monitor.
Enable Autoconnect to try the saved COM ports for enabled devices at startup.
Each connection is independent, so a missing second device does not prevent the
first from connecting. Refresh retries disconnected sources when Autoconnect is enabled.
Existing settings are preserved when rebuilding;
on the first build, settings are copied from `src/dpm_ui.ini` if available.
Keep the executable in a writable folder so it can save settings when closed.
Local INI settings and the generated `dist` directory are excluded from Git.
The dashboard uses built-in defaults when no INI file exists.

1.  Select the COM Port for your device.
2.  Click Connect.
3.  Use the toggle switches to view live plots for Voltage, Current, or Power.

---

## 📊 Data Protocol

The ESP32 sends a comma-separated string every 250ms via Serial:
Voltage,Current_A,Power_W,Shunt_mV

---

## 🤝 Credits

- Original Case Design: [Thingiverse #7031863](https://www.thingiverse.com/thing:7031863)
- Firmware & Software: [Nathan Morgan (Parts-People.com)]

### Connection controls

The connection card shows the active meter name, status, and Connect/Disconnect
button. Click **Manage devices** to edit its friendly name and COM port on one
line. Enable **Connect on startup** to reconnect automatically. Click **Done**
to close the settings panel; connections remain open.

A single-device setup has no source selector or second-device row. Under Manage
devices, click **+ Add second device** to configure another meter. Two source
buttons then appear below the connection summary. Click either name to switch
the LCD and graph; the selected source is highlighted and checked. Use
**Remove second device** to disconnect it and return to the single-device view.
Previously configured two-device setups are restored on launch, with settings
collapsed.

Each device has its own graph history and maximum current. RESET MAX applies
to the displayed device; HOLD GRAPH pauses graph history for both devices.
Names, ports, the optional second-device setting, and the display selection are
saved automatically. With Connect on startup enabled, if the selected source is
absent at startup, the dashboard displays the source that successfully connected.
Saved COM assignments are retained when a device is absent; Refresh ports does
not substitute another port. If Windows assigns a different COM port, select
that port manually.
