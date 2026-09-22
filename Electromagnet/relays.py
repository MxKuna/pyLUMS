"""
Two-channel relay bank with integrated temperature readout (Arduino Mega).

Firmware protocol (ASCII, newline terminated, 9600 baud):
    Host -> MCU : "PING\n"   handshake query
                  "T\n"      advance the relay state machine
    MCU  -> Host: "ACK_RELAY_CONTROLLER"  handshake response
                  "TEMP:<value>"  or  "TEMP:ERR"
                  "STATE:<0|1|2>"         0 = both off, 1 = relay 1, 2 = relay 2

Telemetry is emitted asynchronously by the firmware; the worker drains the
stream in a background thread and exposes only cached values, so that neither
status() nor any remote call blocks the ZeroMQ event loop.
"""

import threading
from time import sleep, time

import serial
import serial.tools.list_ports
from devices.zeromq_device import (
    DeviceOverZeroMQ,
    DeviceWorker,
    include_remote_methods,
    remote,
)
from PyQt6 import QtCore, QtWidgets

# Protocol constants
HANDSHAKE_QUERY = b"PING\n"
HANDSHAKE_RESPONSE = "ACK_RELAY_CONTROLLER"
CMD_TOGGLE = b"T\n"

# Relay state machine codes reported by the firmware
STATE_ALL_OFF = 0
STATE_RELAY_1 = 1
STATE_RELAY_2 = 2


class RelayWorker(DeviceWorker):
    def __init__(
        self,
        *args,
        vid=[0x2341, 0x2A03, 0x1A86, 0x0403],
        pid=[0x0010, 0x0042, 0x0043, 0x7523, 0x6001],
        com=None,
        baud=9600,
        switch_delay=0.5,
        temp_timeout=5.0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.baud = baud
        self.com = com
        self.vid = vid
        self.pid = pid
        self.comp = None

        self._connected = False
        self._command_lock = threading.Lock()

        # Duration for which further commands are inhibited after a switch
        self.switch_delay = switch_delay
        self._switch_lockout_until = 0.0

        # Age after which a cached temperature is considered stale
        self.temp_timeout = temp_timeout
        self._last_temp_time = 0.0

        # Status caching for non-blocking access
        self._cached_status = {
            "state": None,
            "relay1": None,
            "relay2": None,
            "temperature": None,
            "temp_error": False,
        }
        self._monitor_active = False
        self._monitor_thread = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _handshake(self, device, timeout=2.0):
        """Open the port, absorb the auto-reset and verify the firmware identity."""
        comp = serial.Serial(device, self.baud, timeout=0.2)
        try:
            comp.reset_input_buffer()
            comp.reset_output_buffer()

            # The Mega resets when DTR is asserted; the bootloader must expire
            # before the sketch is able to answer.
            sleep(2.0)
            comp.reset_input_buffer()

            comp.write(HANDSHAKE_QUERY)
            comp.flush()

            start_time = time()
            while time() - start_time < timeout:
                if comp.in_waiting > 0:
                    line = comp.readline().decode("utf-8", errors="ignore").strip()
                    # Leftover telemetry may precede the acknowledgement.
                    if line == HANDSHAKE_RESPONSE:
                        return comp
                else:
                    sleep(0.01)
        except Exception as e:
            print(f"Handshake error on {device}: {e}")

        comp.close()
        return None

    def init_device(self):
        ports = list(serial.tools.list_ports.comports())

        if self.com is not None:
            candidates = [p for p in ports if p.device == self.com]
        else:
            # Ports matching the known identifiers are probed first; the
            # remainder are probed afterwards because CH340/FTDI clones of the
            # Mega enumerate with foreign VID/PID pairs.
            matching = [p for p in ports if p.vid in self.vid and p.pid in self.pid]
            candidates = matching + [p for p in ports if p not in matching]

        for port in candidates:
            print(f"Probing: {port.device} - {port.description}")
            comp = self._handshake(port.device)
            if comp is not None:
                self.comp = comp
                self.com = port.device
                self._connected = True
                print(f"Relay controller connected on {self.com}")
                break
        else:
            self._connected = False
            print(
                "Device may not be connected.\nInitialization function found no "
                f"port answering the handshake '{HANDSHAKE_RESPONSE}'. Verify "
                "that the Arduino Mega is attached and that the correct sketch "
                "is flashed."
            )
            return

        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_active = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self._monitor_thread.start()

    def close_device(self):
        self._monitor_active = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1.0)
            self._monitor_thread = None

        with self._command_lock:
            if self.comp is not None and self.comp.is_open:
                try:
                    self.comp.close()
                except Exception as e:
                    print(f"Error closing port: {e}")
            self.comp = None
            self._connected = False

        try:
            super().close_device()
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Background telemetry acquisition
    # ------------------------------------------------------------------

    def _parse_line(self, line):
        """Translate one telemetry line into a cache update."""
        if line.startswith("TEMP:"):
            val = line.split(":", 1)[1].strip()
            if val == "ERR":
                self._cached_status["temperature"] = None
                self._cached_status["temp_error"] = True
            else:
                try:
                    self._cached_status["temperature"] = float(val)
                    self._cached_status["temp_error"] = False
                except ValueError:
                    self._cached_status["temp_error"] = True
            self._last_temp_time = time()

        elif line.startswith("STATE:"):
            val = line.split(":", 1)[1].strip()
            try:
                state = int(val)
            except ValueError:
                return
            if state in (STATE_ALL_OFF, STATE_RELAY_1, STATE_RELAY_2):
                self._cached_status["state"] = state
                self._cached_status["relay1"] = state == STATE_RELAY_1
                self._cached_status["relay2"] = state == STATE_RELAY_2

    def _monitor_loop(self):
        """Drain the asynchronous telemetry stream without blocking the UI."""
        while self._monitor_active:
            if not self._connected:
                sleep(1)
                continue

            try:
                with self._command_lock:
                    # Bounded drain: the firmware emits at a fixed rate, so the
                    # backlog is short. The bound guards against a device that
                    # floods the link.
                    for _ in range(64):
                        if self.comp is None or self.comp.in_waiting <= 0:
                            break
                        line = (
                            self.comp.readline()
                            .decode("utf-8", errors="ignore")
                            .strip()
                        )
                        if line:
                            self._parse_line(line)

                # Invalidate a temperature that has stopped being refreshed.
                if (
                    self._last_temp_time
                    and time() - self._last_temp_time > self.temp_timeout
                ):
                    self._cached_status["temperature"] = None

            except (serial.SerialException, OSError) as e:
                print(f"Serial link lost: {e}")
                self._connected = False
            except Exception as e:
                print(f"Monitor error: {e}")

            sleep(0.05)

    # ------------------------------------------------------------------
    # Status and remote interface
    # ------------------------------------------------------------------

    def status(self):
        """Non-blocking status check returning cached data."""
        d = super().status()
        d["connected"] = self._connected

        if not self._connected:
            d.update(
                {
                    "state": None,
                    "relay1": None,
                    "relay2": None,
                    "temperature": None,
                    "temp_error": False,
                    "switching": False,
                }
            )
            return d

        d.update(self._cached_status)
        d["switching"] = time() < self._switch_lockout_until
        return d

    @remote
    def toggle(self):
        """Advance the relay state machine by one step (0 -> 1 -> 2 -> 0)."""
        if not self._connected:
            print("Device not connected")
            return False

        if time() < self._switch_lockout_until:
            # Contacts are still settling; re-entrant commands are discarded.
            return False

        with self._command_lock:
            try:
                self.comp.write(CMD_TOGGLE)
                self.comp.flush()
                self._switch_lockout_until = time() + self.switch_delay
                return True
            except Exception as e:
                print(f"Error sending toggle command: {e}")
                return False

    @remote
    def state(self):
        """Return the relay state machine code, or None if unknown."""
        return self._cached_status.get("state")

    @remote
    def relay_state(self, ax):
        """Return the closed/open condition of relay `ax` (1 or 2)."""
        if ax not in (1, 2):
            print(f"Invalid relay index: {ax}")
            return False
        return bool(self._cached_status.get(f"relay{ax}"))

    @remote
    def temperature(self):
        """Return the most recent temperature in °C, or None if unavailable."""
        return self._cached_status.get("temperature")

    @remote
    def is_switching(self):
        return time() < self._switch_lockout_until

    @remote
    def update_settings(self, **kwargs):
        if "switch_delay" in kwargs:
            self.switch_delay = float(kwargs["switch_delay"])
        if "temp_timeout" in kwargs:
            self.temp_timeout = float(kwargs["temp_timeout"])
        print(f"Updated relay settings: {kwargs}")

    @remote
    def get_settings(self):
        return {
            "switch_delay": self.switch_delay,
            "temp_timeout": self.temp_timeout,
            "com": self.com,
            "baud": self.baud,
        }

    @remote
    def get_connected(self):
        return self._connected


@include_remote_methods(RelayWorker)
class Relay(DeviceOverZeroMQ):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.relay_labels = {}

    # ------------------------------------------------------------------
    # Indicator styling
    # ------------------------------------------------------------------

    _INDICATOR_STYLE = (
        "background-color: {bg}; color: white; font-size: 14px; "
        "font-weight: bold; border-radius: 5px; padding: 6px;"
    )

    def _style_indicator(self, label, index, condition):
        """condition: True = energised, False = released, 'busy', None = unknown."""
        if condition is True:
            bg, text = "#4CAF50", "ON"
        elif condition is False:
            bg, text = "#F44336", "OFF"
        elif condition == "busy":
            bg, text = "#FF9800", "· · ·"
        else:
            bg, text = "#9E9E9E", "---"

        label.setStyleSheet(self._INDICATOR_STYLE.format(bg=bg))
        label.setText(f"Relay {index}: {text}")

    def _toggle_clicked(self):
        try:
            self.toggle()
        except Exception as e:
            print(f"Error issuing toggle command: {e}")

    # ------------------------------------------------------------------
    # Dock construction
    # ------------------------------------------------------------------

    def createDock(self, parentWidget, menu=None):
        self.dock = QtWidgets.QDockWidget("Relay Controller", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        widget.setLayout(layout)

        # --- Temperature readout ---
        self.temp_label = QtWidgets.QLabel("Temperature: --.- °C")
        self.temp_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.temp_label.setStyleSheet(
            "background-color: #2196F3; color: white; font-size: 18px; "
            "font-weight: bold; border-radius: 6px; padding: 8px;"
        )
        self.temp_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self.temp_label, 1)

        # --- Relay indicators ---
        indicator_layout = QtWidgets.QHBoxLayout()
        indicator_layout.setSpacing(4)

        for index in (1, 2):
            label = QtWidgets.QLabel()
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            self._style_indicator(label, index, None)
            self.relay_labels[index] = label
            indicator_layout.addWidget(label)

        layout.addLayout(indicator_layout, 1)

        # --- Control button ---
        self.toggle_btn = QtWidgets.QPushButton("Switch Relays")
        self.toggle_btn.setEnabled(False)
        self.toggle_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: 2px solid #1976D2;
                border-radius: 4px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #9E9E9E;
                border: 2px solid #757575;
                color: #E0E0E0;
            }
        """)
        self.toggle_btn.clicked.connect(self._toggle_clicked)
        layout.addWidget(self.toggle_btn, 1)

        self.dock.setWidget(widget)
        self.dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.TopDockWidgetArea
            | QtCore.Qt.DockWidgetArea.BottomDockWidgetArea
        )
        parentWidget.addDockWidget(
            QtCore.Qt.DockWidgetArea.TopDockWidgetArea, self.dock
        )
        if menu:
            menu.addAction(self.dock.toggleViewAction())

        self.createListenerThread(self.update_ui)

    # ------------------------------------------------------------------
    # Listener callback
    # ------------------------------------------------------------------

    def update_ui(self, status):
        try:
            if not status.get("connected", False):
                self.temp_label.setText("Temperature: --.- °C")
                self.toggle_btn.setEnabled(False)
                self.toggle_btn.setText("Disconnected")
                for index in (1, 2):
                    self._style_indicator(self.relay_labels[index], index, None)
                return

            switching = status.get("switching", False)

            # Temperature
            if status.get("temp_error", False):
                self.temp_label.setText("Temperature: Sensor Error")
            else:
                temp = status.get("temperature")
                if temp is None:
                    self.temp_label.setText("Temperature: --.- °C")
                else:
                    self.temp_label.setText(f"Temperature: {temp:.1f} °C")

            # Relay indicators; the transient is shown while the contacts settle
            for index in (1, 2):
                condition = "busy" if switching else status.get(f"relay{index}")
                self._style_indicator(self.relay_labels[index], index, condition)

            # Control button
            self.toggle_btn.setEnabled(not switching)
            self.toggle_btn.setText("Switching…" if switching else "Switch Relays")

        except Exception as e:
            print(f"Error updating relay UI: {e}")
