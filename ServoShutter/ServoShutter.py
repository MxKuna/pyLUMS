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

        # Status caching for performance
        self._cached_status = {}
        self._monitor_active = False
        self._monitor_thread = None

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

                    # Start background polling thread if connected
                    if self._connected and (
                        self._monitor_thread is None
                        or not self._monitor_thread.is_alive()
                    ):
                        self._monitor_active = True
                        self._monitor_thread = threading.Thread(
                            target=self._monitor_loop, daemon=True
                        )
                        self._monitor_thread.start()

                except Exception as e:
                    print(f"Error initializing device: {e}")
                    self._connected = False
        else:
            if not self._connected:
                print(
                    "Device may not be connected.\nInitialization function can't find Nucleo L432KC / F303K8 with VID: 0x0483 and PID: 0x374B at any COM port."
                )

    def _monitor_loop(self):
        """Background thread to poll device status without blocking UI"""
        while self._monitor_active:
            if not self._connected:
                sleep(1)
                continue

            try:
                # Use lock to prevent conflict with immediate moves
                with self._command_lock:
                    status_update = {}
                    self.comp.reset_input_buffer()
                    self._send_packet(self.CMD_GET_ALL, b"")
                    pkt = self._receive_packet()

                    if pkt and pkt["cmd"] == self.CMD_GET_ALL and pkt["length"] == 8:
                        for i in range(4):
                            pw = (pkt["data"][i * 2] << 8) | pkt["data"][i * 2 + 1]
                            settings = self.servo_settings[i]
                            mid_point = (
                                settings["closed_pw"] + settings["open_pw"]
                            ) / 2
                            status_update[f"open{i + 1}"] = pw > mid_point
                            status_update[f"position{i + 1}"] = pw
                    else:
                        # Fallback to individual query if bulk fails
                        for i in range(4):
                            status_update[f"open{i + 1}"] = self._state_internal(i)

                    # Atomic update of the cache
                    self._cached_status.update(status_update)

            except Exception as e:
                pass

            # Poll rate
            sleep(0.1)

    def status(self):
        """Non-blocking status check returning cached data"""
        d = super().status()
        if not self._connected:
            return d

        d.update(self._cached_status)
        return d

    def _state_internal(self, servo_idx):
        """Internal state query (NOTE: Assumes lock is already held by caller)"""
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
        if not self._connected:
            return False

        cache_key = f"open{ax}"
        if cache_key in self._cached_status:
            return self._cached_status[cache_key]

        with self._command_lock:
            return self._state_internal(ax - 1)

    @remote
    def move_immediate(self, action, *axes):
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
        for key, value in kwargs.items():
            if key in self.servo_settings[servo_idx]:
                self.servo_settings[servo_idx][key] = value
        print(f"Updated settings for servo {servo_idx}: {kwargs}")

    @remote
    def get_settings(self, servo_idx):
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
                    # Update button text with custom name
                    servo_idx = axis - 1
                    settings = self.get_settings(servo_idx)
                    name = settings.get("name", f"Servo {axis}")
                    self.buttons[axis].setText(name)
                    self.buttons[axis].setEnabled(True)
                except Exception as e:
                    print(f"Error updating status for axis {axis}: {e}")
        else:
            for axis in [1, 2, 3, 4]:
                self.buttons[axis].setChecked(False)
                self.buttons[axis].setEnabled(False)
                self.buttons[axis].setText(f"Servo {axis}")

    def _show_help_dialog(self):
        """Show help dialog with API commands"""
        dialog = QtWidgets.QDialog(self.dock)
        dialog.setWindowTitle("API Commands")
        dialog.setMinimumSize(500, 350)

        layout = QtWidgets.QVBoxLayout()
        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)
        help_text = """<h3>Control</h3>... (same as before) ..."""
        text_edit.setHtml(help_text)
        layout.addWidget(text_edit)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.setLayout(layout)
        dialog.exec()

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

            # Update the button text in control tab
            self.buttons[servo_idx + 1].setText(name)
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

            # Update radio button selection
            if hasattr(self, "servo_radios"):
                self.servo_radios[servo_idx].setChecked(True)
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
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        widget.setLayout(main_layout)

        # Tab widget - expandable
        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)
        main_layout.addWidget(tabs, 1)  # Stretch factor 1

        # --- Control Tab ---
        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(4)
        control_widget.setLayout(control_layout)

        self.buttons = {}

        # Grid layout for 2x2 button grid
        grid_layout = QtWidgets.QGridLayout()
        grid_layout.setSpacing(4)

        for idx, axis in enumerate([1, 2, 3, 4]):
            row = idx // 2
            col = idx % 2

            button = QtWidgets.QPushButton(f"Servo {axis}")
            button.setCheckable(True)
            button.clicked.connect(self._generate_func(axis))

            # Fully expandable in both directions
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )

            # Large bold text centered
            button.setStyleSheet("""
                QPushButton {
                    border: 3px solid #666;
                    border-radius: 8px;
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:checked {
                    background-color: #4CAF50;
                    border: 3px solid #2E7D32;
                }
                QPushButton:hover {
                    border: 3px solid #333;
                }
                QPushButton:disabled {
                    background-color: #9E9E9E;
                    color: #E0E0E0;
                }
            """)

            self.buttons[axis] = button
            grid_layout.addWidget(button, row, col)

        # Make grid rows and columns stretch equally
        grid_layout.setRowStretch(0, 1)
        grid_layout.setRowStretch(1, 1)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)

        control_layout.addLayout(grid_layout, 1)  # Stretch factor 1
        tabs.addTab(control_widget, "Control")

        # --- Settings Tab ---
        settings_widget = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout()
        settings_layout.setContentsMargins(8, 8, 8, 8)
        settings_layout.setSpacing(6)
        settings_widget.setLayout(settings_layout)

        self.current_servo_idx = 0

        # Radio buttons for servo selection - compact horizontal layout
        radio_container = QtWidgets.QWidget()
        radio_layout = QtWidgets.QHBoxLayout()
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(4)
        radio_container.setLayout(radio_layout)

        self.servo_group = QtWidgets.QButtonGroup()
        self.servo_radios = []

        for i in range(4):
            rbtn = QtWidgets.QRadioButton(f"S{i + 1}")
            if i == 0:
                rbtn.setChecked(True)
            self.servo_group.addButton(rbtn, i)
            self.servo_radios.append(rbtn)
            radio_layout.addWidget(rbtn)

        radio_layout.addStretch(1)
        settings_layout.addWidget(radio_container)

        # Connect group signal
        self.servo_group.idClicked.connect(self._switch_servo)

        # Settings form - using grid for compact layout
        form_container = QtWidgets.QWidget()
        form_layout = QtWidgets.QGridLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(6)
        form_container.setLayout(form_layout)

        # Row 0: Name
        form_layout.addWidget(QtWidgets.QLabel("Name:"), 0, 0)
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("e.g., Front Left")
        form_layout.addWidget(self.name_input, 0, 1, 1, 3)

        # Row 1: Closed/Open positions
        form_layout.addWidget(QtWidgets.QLabel("Closed:"), 1, 0)
        self.closed_pw_spinbox = QtWidgets.QSpinBox()
        self.closed_pw_spinbox.setRange(500, 2500)
        self.closed_pw_spinbox.setSuffix(" μs")
        form_layout.addWidget(self.closed_pw_spinbox, 1, 1)

        form_layout.addWidget(QtWidgets.QLabel("Open:"), 1, 2)
        self.open_pw_spinbox = QtWidgets.QSpinBox()
        self.open_pw_spinbox.setRange(500, 2500)
        self.open_pw_spinbox.setSuffix(" μs")
        form_layout.addWidget(self.open_pw_spinbox, 1, 3)

        # Row 2: Step settings
        form_layout.addWidget(QtWidgets.QLabel("Step:"), 2, 0)
        self.step_deg_spinbox = QtWidgets.QDoubleSpinBox()
        self.step_deg_spinbox.setRange(0.1, 25.5)
        self.step_deg_spinbox.setSingleStep(0.1)
        self.step_deg_spinbox.setSuffix(" °")
        form_layout.addWidget(self.step_deg_spinbox, 2, 1)

        form_layout.addWidget(QtWidgets.QLabel("Delay:"), 2, 2)
        self.step_delay_spinbox = QtWidgets.QSpinBox()
        self.step_delay_spinbox.setRange(1, 1000)
        self.step_delay_spinbox.setSuffix(" ms")
        form_layout.addWidget(self.step_delay_spinbox, 2, 3)

        # Set column stretches for form
        form_layout.setColumnStretch(0, 0)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(2, 0)
        form_layout.setColumnStretch(3, 1)

        settings_layout.addWidget(form_container)

        # Apply button - stretchable height
        apply_btn = QtWidgets.QPushButton("Apply Settings")
        apply_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
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
        """)
        apply_btn.clicked.connect(self._update_settings_from_ui)
        settings_layout.addWidget(apply_btn, 1)  # Stretch factor 1

        settings_layout.addStretch(0)  # Minimal stretch to push content up
        tabs.addTab(settings_widget, "Settings")

        # Load initial settings
        self._load_settings_to_ui()

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
