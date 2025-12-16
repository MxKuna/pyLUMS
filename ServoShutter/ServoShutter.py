import threading
from time import sleep, time

import serial
import serial.tools.list_ports
from PyQt5 import QtCore, QtWidgets

from devices.zeromq_device import (
    DeviceOverZeroMQ,
    DeviceWorker,
    include_remote_methods,
    remote,
)


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
                except Exception as e:
                    print(f"Error initializing device: {e}")
                    self._connected = False
        else:
            if not self._connected:
                print(
                    "Device may not be connected.\nInitialization function can't find Nucleo L432KC / F303K8 with VID: 0x0483 and PID: 0x374B at any COM port."
                )

    def status(self):
        d = super().status()
        if not self._connected:
            return d

        try:
            with self._command_lock:
                self.comp.reset_input_buffer()
                self._send_packet(self.CMD_GET_ALL, b"")
                pkt = self._receive_packet()

                if pkt and pkt["cmd"] == self.CMD_GET_ALL and pkt["length"] == 8:
                    for i in range(4):
                        pw = (pkt["data"][i * 2] << 8) | pkt["data"][i * 2 + 1]
                        settings = self.servo_settings[i]
                        mid_point = (settings["closed_pw"] + settings["open_pw"]) / 2
                        d[f"open{i + 1}"] = pw > mid_point
                        d[f"position{i + 1}"] = pw
                else:
                    for i in range(4):
                        d[f"open{i + 1}"] = self._state_internal(i)
        except Exception as e:
            print(f"Error getting status: {e}")

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

        with self._command_lock:
            for ax in axes:
                servo_idx = ax - 1
                settings = self.servo_settings[servo_idx]

                if action == "close":
                    pw = settings["closed_pw"]
                elif action == "open":
                    pw = settings["open_pw"]
                else:
                    print(f"Invalid action: {action}")
                    continue

                try:
                    self.comp.reset_input_buffer()
                    data = bytes([servo_idx, (pw >> 8) & 0xFF, pw & 0xFF])
                    self._send_packet(self.CMD_SET_SERVO, data)
                    pkt = self._receive_packet()

                    if not pkt or pkt["data"][0] != self.RESP_OK:
                        print(f"Error moving servo {ax}")
                    else:
                        print(f"Moved servo {ax} to {action}")
                except Exception as e:
                    print(f"Error moving servo {ax}: {e}")

    @remote
    def move_stepped(self, action, *axes):
        """Move servo with smooth stepping"""
        if not self._connected:
            print("Device not connected")
            return

        with self._command_lock:
            for ax in axes:
                servo_idx = ax - 1
                settings = self.servo_settings[servo_idx]

                if action == "close":
                    target_pw = settings["closed_pw"]
                elif action == "open":
                    target_pw = settings["open_pw"]
                else:
                    print(f"Invalid action: {action}")
                    continue

                target_deg = ((target_pw - 500) / 2000.0) * 180.0
                target_deg_100 = int(target_deg * 100)
                step_deg_100 = int(settings["step_deg"] * 100)

                if step_deg_100 > 255:
                    print(
                        f"Warning: Step size {settings['step_deg']}° exceeds max 2.5°"
                    )
                    step_deg_100 = 255

                try:
                    self.comp.reset_input_buffer()
                    data = bytes(
                        [
                            servo_idx,
                            (target_deg_100 >> 8) & 0xFF,
                            target_deg_100 & 0xFF,
                            step_deg_100,
                            (settings["step_delay_ms"] >> 8) & 0xFF,
                            settings["step_delay_ms"] & 0xFF,
                        ]
                    )
                    self._send_packet(self.CMD_MOVE_STEPPED, data)
                    pkt = self._receive_packet()

                    if not pkt or pkt["data"][0] != self.RESP_OK:
                        print(f"Error starting stepped move for servo {ax}")
                    else:
                        print(f"Started stepped move for servo {ax}")
                except Exception as e:
                    print(f"Error with stepped move for servo {ax}: {e}")

    @remote
    def stop_move(self, *axes):
        """Stop ongoing stepped movement"""
        if not self._connected:
            return

        with self._command_lock:
            for ax in axes:
                servo_idx = ax - 1
                try:
                    self.comp.reset_input_buffer()
                    data = bytes([servo_idx])
                    self._send_packet(self.CMD_STOP_MOVE, data)
                    self._receive_packet()
                except Exception as e:
                    print(f"Error stopping servo {ax}: {e}")

    @remote
    def update_settings(self, servo_idx, **kwargs):
        """Update settings for a servo (0-indexed)"""
        for key, value in kwargs.items():
            if key in self.servo_settings[servo_idx]:
                self.servo_settings[servo_idx][key] = value
        print(f"Updated settings for servo {servo_idx}: {kwargs}")

    @remote
    def get_settings(self, servo_idx):
        """Get settings for a servo (0-indexed)"""
        return self.servo_settings[servo_idx].copy()

    @remote
    def get_connected(self):
        return self._connected


@include_remote_methods(ShutterWorker)
class Shutter(DeviceOverZeroMQ):
    def __init__(self, *args, use_stepped=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_stepped = use_stepped

    def _generate_func(self, number):
        def change_state(on):
            if self.use_stepped:
                if on:
                    self.move_stepped("open", number)
                else:
                    self.move_stepped("close", number)
            else:
                if on:
                    self.move_immediate("open", number)
                else:
                    self.move_immediate("close", number)

        return change_state

    def update_ui(self, status):
        if self.get_connected():
            for axis in [1, 2, 3, 4]:
                try:
                    state_key = f"open{axis}"
                    if state_key in status:
                        self.buttons[axis].setChecked(status[state_key])
                    # Update label with custom name
                    servo_idx = axis - 1
                    settings = self.get_settings(servo_idx)
                    self.servo_labels[axis].setText(
                        settings.get("name", f"Servo {axis}")
                    )
                except Exception as e:
                    print(f"Error updating status for axis {axis}: {e}")
        else:
            for axis in [1, 2, 3, 4]:
                self.buttons[axis].setChecked(False)
                self.buttons[axis].setEnabled(False)

    def _show_help_dialog(self):
        """Show help dialog with API commands"""
        dialog = QtWidgets.QDialog(self.dock)
        dialog.setWindowTitle("API Commands")
        dialog.setMinimumSize(500, 350)

        layout = QtWidgets.QVBoxLayout()

        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)

        help_text = """<h3>Control</h3>
<b>move_immediate(action, *axes)</b> - Instant move<br>
<b>move_stepped(action, *axes)</b> - Smooth move<br>
<b>stop_move(*axes)</b> - Stop movement<br>
<b>state(axis)</b> - Get servo state (True=open)<br>
<br>
<i>action: "open" or "close", axes: 1-4</i>

<h3>Settings</h3>
<b>update_settings(servo_idx, **kwargs)</b><br>
<i>servo_idx: 0-3, kwargs: closed_pw, open_pw, step_deg, step_delay_ms</i><br>
<br>
<b>get_settings(servo_idx)</b> - Get current settings<br>
<b>get_connected()</b> - Check connection status

<h3>Examples</h3>
<code>device.move_stepped("open", 1, 2)</code><br>
<code>device.update_settings(0, closed_pw=1000)</code><br>
<code>is_open = device.state(1)</code>
"""

        text_edit.setHtml(help_text)
        layout.addWidget(text_edit)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
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
