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
from PyQt5 import QtCore, QtWidgets


class ShutterWorker(DeviceWorker):
    def __init__(
        self, *args, vid=0x0483, pid=[0x374B, 0x438], com=None, baud=115200, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.baud = baud
        self.com = com
        self.vid = vid
        self.pid = pid
        self._connected = False
        self._command_lock = threading.Lock()

        # Protocol constants
        self.PKT_START = 0xAA
        self.PKT_END = 0x55
        self.MAX_PACKET_SIZE = 32

        # Command codes
        self.CMD_PING = 0x01
        self.CMD_SET_SERVO = 0x02
        self.CMD_GET_SERVO = 0x03
        self.CMD_GET_ALL = 0x04
        self.CMD_MOVE_STEPPED = 0x05
        self.CMD_STOP_MOVE = 0x06
        self.CMD_GET_MOVE_STATUS = 0x07

        # Response codes
        self.RESP_OK = 0x00
        self.RESP_ERROR = 0xFF

        # Settings (can be updated from UI)
        self.servo_settings = {
            i: {
                "closed_pw": 1000,
                "open_pw": 1500,
                "step_deg": 1.0,
                "step_delay_ms": 15,
                "name": f"Servo {i + 1}",
            }
            for i in range(4)
        }

        # Background polling for status
        self._status_cache = {}
        self._cache_lock = threading.Lock()
        self._polling_thread = None
        self._polling_active = False
        self._polling_interval = 0.2  # Poll every 200ms

    def _calculate_checksum(self, length, cmd, data):
        """Calculate XOR checksum"""
        checksum = length ^ cmd
        for byte in data:
            checksum ^= byte
        return checksum

    def _send_packet(self, cmd, data):
        """Send a packet with proper framing and checksum"""
        packet = bytearray()
        packet.append(self.PKT_START)
        packet.append(len(data))
        packet.append(cmd)
        packet.extend(data)
        checksum = self._calculate_checksum(len(data), cmd, data)
        packet.append(checksum)
        packet.append(self.PKT_END)

        self.comp.write(bytes(packet))
        self.comp.flush()

    def _receive_packet(self, timeout=0.1):
        """Receive and validate a packet"""
        start_time = time()

        while time() - start_time < timeout:
            if self.comp.in_waiting > 0:
                byte = self.comp.read(1)
                if byte[0] == self.PKT_START:
                    break
        else:
            return None

        start_time = time()
        while self.comp.in_waiting < 1 and time() - start_time < timeout:
            sleep(0.001)
        if self.comp.in_waiting < 1:
            return None

        length = self.comp.read(1)[0]
        if length > self.MAX_PACKET_SIZE:
            return None

        start_time = time()
        while self.comp.in_waiting < 1 and time() - start_time < timeout:
            sleep(0.001)
        if self.comp.in_waiting < 1:
            return None

        cmd = self.comp.read(1)[0]

        start_time = time()
        while self.comp.in_waiting < length and time() - start_time < timeout:
            sleep(0.001)
        if self.comp.in_waiting < length:
            return None

        data = self.comp.read(length)

        start_time = time()
        while self.comp.in_waiting < 2 and time() - start_time < timeout:
            sleep(0.001)
        if self.comp.in_waiting < 2:
            return None

        checksum = self.comp.read(1)[0]
        end_marker = self.comp.read(1)[0]

        if end_marker != self.PKT_END:
            return None

        expected_checksum = self._calculate_checksum(length, cmd, data)
        if checksum != expected_checksum:
            return None

        return {"cmd": cmd, "data": data, "length": length}

    def _background_polling_loop(self):
        """Background thread that continuously polls servo positions"""
        while self._polling_active:
            if not self._connected:
                sleep(0.5)
                continue

            try:
                with self._command_lock:
                    self.comp.reset_input_buffer()
                    self._send_packet(self.CMD_GET_ALL, b"")
                    pkt = self._receive_packet(timeout=0.15)

                    if pkt and pkt["cmd"] == self.CMD_GET_ALL and pkt["length"] == 8:
                        # Update cache
                        cache_update = {}
                        for i in range(4):
                            pw = (pkt["data"][i * 2] << 8) | pkt["data"][i * 2 + 1]
                            settings = self.servo_settings[i]
                            mid_point = (
                                settings["closed_pw"] + settings["open_pw"]
                            ) / 2
                            cache_update[f"open{i + 1}"] = pw > mid_point
                            cache_update[f"position{i + 1}"] = pw

                        with self._cache_lock:
                            self._status_cache.update(cache_update)
            except Exception as e:
                print(f"Background polling error: {e}")

            sleep(self._polling_interval)

    def _start_background_polling(self):
        """Start the background polling thread"""
        if self._polling_thread is None or not self._polling_thread.is_alive():
            self._polling_active = True
            self._polling_thread = threading.Thread(
                target=self._background_polling_loop,
                daemon=True,
                name="ServoStatusPoller",
            )
            self._polling_thread.start()
            print("Background servo polling started")

    def _stop_background_polling(self):
        """Stop the background polling thread"""
        self._polling_active = False
        if self._polling_thread and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=1.0)
        print("Background servo polling stopped")

    def init_device(self):
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            if port.vid == self.vid and port.pid in self.pid:
                self.com = port.device
                try:
                    self.comp = serial.Serial(self.com, self.baud, timeout=0.5)
                    print(f"Connecting to: {self.comp.name}")

                    self.comp.reset_input_buffer()
                    self.comp.reset_output_buffer()

                    sleep(2)

                    pkt = self._receive_packet(timeout=0.5)
                    if pkt and pkt["cmd"] == 0xFF:
                        print("Received initialization packet")
                        self._connected = True
                    else:
                        with self._command_lock:
                            self._send_packet(self.CMD_PING, b"")
                            pkt = self._receive_packet()
                            if pkt and pkt["cmd"] == self.CMD_PING:
                                print("Device connected ✅")
                                self._connected = True
                            else:
                                print("Ping failed")

                    # Start background polling if connected
                    if self._connected:
                        self._start_background_polling()

                except Exception as e:
                    print(f"Error initializing device: {e}")
                    self._connected = False
        else:
            if not self._connected:
                print(
                    "Device may not be connected.\nInitialization function can't find Nucleo L432KC / F303K8 with VID: 0x0483 and PID: 0x374B at any COM port."
                )

    def status(self):
        """Non-blocking status method that returns cached values"""
        d = super().status()

        if not self._connected:
            return d

        # Return cached values - no blocking serial communication
        with self._cache_lock:
            d.update(self._status_cache.copy())

        return d

    def _state_internal(self, servo_idx):
        """Internal state query without extra locking (0-indexed)"""
        try:
            self.comp.reset_input_buffer()
            data = bytes([servo_idx])
            self._send_packet(self.CMD_GET_SERVO, data)
            pkt = self._receive_packet()

            if pkt and pkt["cmd"] == self.CMD_GET_SERVO and pkt["length"] == 3:
                pw = (pkt["data"][1] << 8) | pkt["data"][2]
                settings = self.servo_settings[servo_idx]
                mid_point = (settings["closed_pw"] + settings["open_pw"]) / 2
                return pw > mid_point
        except Exception as e:
            print(f"Error querying servo {servo_idx}: {e}")
        return False

    @remote
    def state(self, ax):
        """Get state of servo (1-indexed for API compatibility)"""
        if not self._connected:
            return False

        with self._command_lock:
            return self._state_internal(ax - 1)

    @remote
    def move_immediate(self, action, *axes):
        """Move servo immediately to position"""
        if not self._connected:
            print("Device not connected")
            return

        if not axes:
            axes = [1, 2, 3, 4]

        for ax in axes:
            servo_idx = ax - 1
            settings = self.servo_settings[servo_idx]

            if action == "open":
                target_pw = settings["open_pw"]
            elif action == "close":
                target_pw = settings["closed_pw"]
            else:
                print(f"Unknown action: {action}")
                continue

            with self._command_lock:
                data = bytearray()
                data.append(servo_idx)
                data.append((target_pw >> 8) & 0xFF)
                data.append(target_pw & 0xFF)

                self._send_packet(self.CMD_SET_SERVO, bytes(data))
                pkt = self._receive_packet()

                if pkt and pkt["cmd"] == self.CMD_SET_SERVO:
                    if pkt["data"][0] == self.RESP_OK:
                        print(f"Servo {ax} moved to {action}")
                    else:
                        print(f"Error moving servo {ax}")

    @remote
    def move_stepped(self, action, *axes):
        """Move servo with stepped motion"""
        if not self._connected:
            print("Device not connected")
            return

        if not axes:
            axes = [1, 2, 3, 4]

        for ax in axes:
            servo_idx = ax - 1
            settings = self.servo_settings[servo_idx]

            if action == "open":
                target_pw = settings["open_pw"]
            elif action == "close":
                target_pw = settings["closed_pw"]
            else:
                print(f"Unknown action: {action}")
                continue

            with self._command_lock:
                data = bytearray()
                data.append(servo_idx)
                data.append((target_pw >> 8) & 0xFF)
                data.append(target_pw & 0xFF)

                step_deg_int = int(settings["step_deg"] * 10)
                data.append(step_deg_int)

                delay_ms = settings["step_delay_ms"]
                data.append((delay_ms >> 8) & 0xFF)
                data.append(delay_ms & 0xFF)

                self._send_packet(self.CMD_MOVE_STEPPED, bytes(data))
                pkt = self._receive_packet()

                if pkt and pkt["cmd"] == self.CMD_MOVE_STEPPED:
                    if pkt["data"][0] == self.RESP_OK:
                        print(f"Servo {ax} started stepped move to {action}")
                    else:
                        print(f"Error starting stepped move for servo {ax}")

    @remote
    def stop_move(self, *axes):
        """Stop stepped motion on specified servos"""
        if not self._connected:
            print("Device not connected")
            return

        if not axes:
            axes = [1, 2, 3, 4]

        for ax in axes:
            servo_idx = ax - 1

            with self._command_lock:
                data = bytes([servo_idx])
                self._send_packet(self.CMD_STOP_MOVE, data)
                pkt = self._receive_packet()

                if pkt and pkt["cmd"] == self.CMD_STOP_MOVE:
                    if pkt["data"][0] == self.RESP_OK:
                        print(f"Servo {ax} motion stopped")
                    else:
                        print(f"Error stopping servo {ax}")

    @remote
    def update_settings(
        self,
        servo_idx,
        closed_pw=None,
        open_pw=None,
        step_deg=None,
        step_delay_ms=None,
        name=None,
    ):
        """Update settings for a specific servo (0-indexed)"""
        if servo_idx not in self.servo_settings:
            print(f"Invalid servo index: {servo_idx}")
            return

        if closed_pw is not None:
            self.servo_settings[servo_idx]["closed_pw"] = closed_pw
        if open_pw is not None:
            self.servo_settings[servo_idx]["open_pw"] = open_pw
        if step_deg is not None:
            self.servo_settings[servo_idx]["step_deg"] = step_deg
        if step_delay_ms is not None:
            self.servo_settings[servo_idx]["step_delay_ms"] = step_delay_ms
        if name is not None:
            self.servo_settings[servo_idx]["name"] = name

        print(f"Updated settings for servo {servo_idx + 1}")

    @remote
    def get_settings(self, servo_idx):
        """Get settings for a specific servo (0-indexed)"""
        if servo_idx in self.servo_settings:
            return self.servo_settings[servo_idx].copy()
        return {}

    def close_device(self):
        """Clean shutdown of the device"""
        self._stop_background_polling()

        if hasattr(self, "comp") and self.comp and self.comp.is_open:
            try:
                self.comp.close()
                print("Serial connection closed")
            except Exception as e:
                print(f"Error closing serial connection: {e}")

        self._connected = False

    def __del__(self):
        """Ensure cleanup on deletion"""
        self.close_device()


@include_remote_methods
class ServoShutter(DeviceOverZeroMQ):
    gui_allowed = True

    def __init__(self, *args, **kwargs):
        super().__init__(ShutterWorker, *args, **kwargs)

    def _generate_func(self, ax):
        def func(checked):
            if checked:
                self.move_stepped("open", ax)
            else:
                self.move_stepped("close", ax)

        return func

    def update_ui(self, new_status):
        """Update UI based on status"""
        try:
            for axis in [1, 2, 3, 4]:
                key = f"open{axis}"
                if key in new_status:
                    self.buttons[axis].blockSignals(True)
                    self.buttons[axis].setChecked(new_status[key])
                    self.buttons[axis].setText("OPEN" if new_status[key] else "CLOSED")
                    self.buttons[axis].blockSignals(False)
        except Exception as e:
            print(f"Error updating UI: {e}")

    def _show_help_dialog(self):
        """Show API usage help dialog"""
        help_text = """
<h3>ServoShutter Remote API</h3>

<p><b>Available methods:</b></p>

<p><code>move_immediate(action, *axes)</code><br>
Move servos immediately without stepping<br>
Examples:<br>
&nbsp;&nbsp;<code>device.move_immediate('open', 1, 2)</code><br>
&nbsp;&nbsp;<code>device.move_immediate('close')</code> # all servos</p>

<p><code>move_stepped(action, *axes)</code><br>
Move servos with smooth stepped motion<br>
Examples:<br>
&nbsp;&nbsp;<code>device.move_stepped('open', 3)</code><br>
&nbsp;&nbsp;<code>device.move_stepped('close', 1, 2, 3, 4)</code></p>

<p><code>stop_move(*axes)</code><br>
Stop ongoing stepped motion<br>
Example:<br>
&nbsp;&nbsp;<code>device.stop_move(1, 2)</code></p>

<p><code>state(axis)</code><br>
Get current state of a servo (True=open, False=closed)<br>
Example:<br>
&nbsp;&nbsp;<code>is_open = device.state(1)</code></p>

<p><code>update_settings(servo_idx, **kwargs)</code><br>
Update servo settings (servo_idx is 0-indexed)<br>
Example:<br>
&nbsp;&nbsp;<code>device.update_settings(0, closed_pw=1000, open_pw=2000)</code></p>

<p><b>Parameters:</b></p>
<ul>
<li><code>action</code>: 'open' or 'close'</li>
<li><code>axes</code>: Servo numbers (1-4), omit for all servos</li>
</ul>
        """

        dialog = QtWidgets.QDialog(self.dock)
        dialog.setWindowTitle("API Help")
        dialog.setMinimumWidth(500)

        layout = QtWidgets.QVBoxLayout()
        text_browser = QtWidgets.QTextBrowser()
        text_browser.setHtml(help_text)
        text_browser.setOpenExternalLinks(True)
        layout.addWidget(text_browser)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)

        dialog.setLayout(layout)
        dialog.exec_()

    def _update_settings_from_ui(self):
        """Update settings from UI controls"""
        try:
            servo_idx = self.current_servo_idx
            closed_pw = int(self.closed_pw_spinbox.value())
            open_pw = int(self.open_pw_spinbox.value())
            step_deg = float(self.step_deg_spinbox.value())
            step_delay = int(self.step_delay_spinbox.value())
            name = self.name_input.text().strip()

            if not name:
                name = f"Servo {servo_idx + 1}"

            self.update_settings(
                servo_idx,
                closed_pw=closed_pw,
                open_pw=open_pw,
                step_deg=step_deg,
                step_delay_ms=step_delay,
                name=name,
            )

            # Update the label in control tab
            self.servo_labels[servo_idx + 1].setText(name)
        except Exception as e:
            print(f"Error updating settings: {e}")

    def _load_settings_to_ui(self):
        """Load current settings into UI"""
        try:
            servo_idx = self.current_servo_idx
            settings = self.get_settings(servo_idx)
            self.closed_pw_spinbox.setValue(settings["closed_pw"])
            self.open_pw_spinbox.setValue(settings["open_pw"])
            self.step_deg_spinbox.setValue(settings["step_deg"])
            self.step_delay_spinbox.setValue(settings["step_delay_ms"])
            self.name_input.setText(settings.get("name", f"Servo {servo_idx + 1}"))
        except Exception as e:
            print(f"Error loading settings: {e}")

    def _switch_servo(self, servo_idx):
        """Switch to settings for a different servo"""
        self.current_servo_idx = servo_idx
        self._load_settings_to_ui()

    def createDock(self, parentWidget, menu=None):
        self.dock = QtWidgets.QDockWidget("ServoShutter", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        main_layout = QtWidgets.QVBoxLayout()
        widget.setLayout(main_layout)

        # Header
        header_layout = QtWidgets.QHBoxLayout()
        header_label = QtWidgets.QLabel("<b>Servo Shutter Control</b>")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        help_btn = QtWidgets.QPushButton("?")
        help_btn.setFixedSize(25, 25)
        help_btn.setStyleSheet("""
            QPushButton {
                border-radius: 12px;
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        help_btn.clicked.connect(self._show_help_dialog)
        help_btn.setToolTip("API Help")
        header_layout.addWidget(help_btn)

        main_layout.addLayout(header_layout)

        # Tab widget
        tabs = QtWidgets.QTabWidget()
        main_layout.addWidget(tabs)

        # Control tab
        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setContentsMargins(5, 5, 5, 5)
        control_layout.setSpacing(5)
        control_widget.setLayout(control_layout)

        self.buttons = {}
        self.servo_labels = {}

        # Create vertical lever-style buttons
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        for axis in [1, 2, 3, 4]:
            servo_layout = QtWidgets.QVBoxLayout()
            servo_layout.setAlignment(QtCore.Qt.AlignCenter)
            servo_layout.setSpacing(5)
            servo_layout.setContentsMargins(0, 0, 0, 0)

            label = QtWidgets.QLabel(f"Servo {axis}")
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setStyleSheet("font-weight: bold; font-size: 13px;")
            self.servo_labels[axis] = label
            servo_layout.addWidget(label)

            button = QtWidgets.QPushButton()
            button.setCheckable(True)
            button.clicked.connect(self._generate_func(axis))
            button.setMinimumSize(50, 120)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )

            # Vertical lever style
            button.setStyleSheet("""
                QPushButton {
                    border: 2px solid #666;
                    border-radius: 8px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f44336, stop:0.5 #d32f2f, stop:1 #b71c1c);
                    color: white;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:checked {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #81C784, stop:0.5 #66BB6A, stop:1 #4CAF50);
                }
                QPushButton:hover {
                    border: 2px solid #333;
                }
                QPushButton:disabled {
                    background: #9E9E9E;
                    border: 2px solid #757575;
                }
            """)

            self.buttons[axis] = button
            servo_layout.addWidget(button)

            buttons_layout.addLayout(servo_layout)

        control_layout.addLayout(buttons_layout)
        tabs.addTab(control_widget, "Control")

        # Settings tab
        settings_widget = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout()
        settings_layout.setContentsMargins(5, 5, 5, 5)
        settings_layout.setSpacing(8)
        settings_widget.setLayout(settings_layout)

        # Initialize current servo index
        self.current_servo_idx = 0

        # Servo selector with dropdown
        selector_layout = QtWidgets.QHBoxLayout()
        selector_layout.addWidget(QtWidgets.QLabel("Select Servo:"))
        self.servo_selector = QtWidgets.QComboBox()
        self.servo_selector.addItems(["Servo 1", "Servo 2", "Servo 3", "Servo 4"])
        self.servo_selector.currentIndexChanged.connect(
            lambda idx: self._switch_servo(idx)
        )
        selector_layout.addWidget(self.servo_selector)
        selector_layout.addStretch()
        settings_layout.addLayout(selector_layout)

        # Settings form
        form_layout = QtWidgets.QFormLayout()
        form_layout.setVerticalSpacing(8)
        form_layout.setContentsMargins(0, 5, 0, 0)

        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("e.g., Front Left")
        form_layout.addRow("Name:", self.name_input)

        self.closed_pw_spinbox = QtWidgets.QSpinBox()
        self.closed_pw_spinbox.setRange(500, 2500)
        self.closed_pw_spinbox.setValue(1000)
        self.closed_pw_spinbox.setSuffix(" μs")
        form_layout.addRow("Closed Position:", self.closed_pw_spinbox)

        self.open_pw_spinbox = QtWidgets.QSpinBox()
        self.open_pw_spinbox.setRange(500, 2500)
        self.open_pw_spinbox.setValue(2000)
        self.open_pw_spinbox.setSuffix(" μs")
        form_layout.addRow("Open Position:", self.open_pw_spinbox)

        self.step_deg_spinbox = QtWidgets.QDoubleSpinBox()
        self.step_deg_spinbox.setRange(0.1, 25.5)
        self.step_deg_spinbox.setValue(1.0)
        self.step_deg_spinbox.setSingleStep(0.1)
        self.step_deg_spinbox.setDecimals(1)
        self.step_deg_spinbox.setSuffix(" °")
        form_layout.addRow("Step Size:", self.step_deg_spinbox)

        self.step_delay_spinbox = QtWidgets.QSpinBox()
        self.step_delay_spinbox.setRange(1, 1000)
        self.step_delay_spinbox.setValue(10)
        self.step_delay_spinbox.setSuffix(" ms")
        form_layout.addRow("Step Delay:", self.step_delay_spinbox)

        settings_layout.addLayout(form_layout)

        apply_btn = QtWidgets.QPushButton("Apply Settings")
        apply_btn.clicked.connect(self._update_settings_from_ui)
        apply_btn.setMaximumWidth(150)
        settings_layout.addWidget(apply_btn)

        settings_layout.addStretch()
        tabs.addTab(settings_widget, "Settings")

        # Load initial settings
        self._load_settings_to_ui()

        self.dock.setWidget(widget)
        self.dock.setAllowedAreas(
            QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea
        )
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, self.dock)
        if menu:
            menu.addAction(self.dock.toggleViewAction())

        self.createListenerThread(self.update_ui)
