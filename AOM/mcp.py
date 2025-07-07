# -*- coding: utf-8 -*-
"""
Support for QuadAOM - 4-channel AOM driver from AA Opto with enhanced GUI
"""

import re
import threading
import time

import numpy as np
from devices.zeromq_device import (
    DeviceOverZeroMQ,
    DeviceWorker,
    include_remote_methods,
    remote,
)
from PyQt5 import QtCore, QtGui, QtWidgets


class QuadAOMWorker(DeviceWorker):
    """ Worker class for 4-channel AOM driver by AA Opto """

    def __init__(self, comport=None, *args, **kwargs):
        """ comport: COM1, COM2, ... """
        super().__init__(*args, **kwargs)
        if comport is None:
            raise Exception("Error - you should specify COM port as comport parameter in the config file")

        self._comport = comport

    def init_device(self):
        """ Initializes connection with the device """
        import serial
        print(self._comport)
        self.ser = serial.Serial(self._comport, 57600, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.5)

        while len(self.ser.read()) > 0:
            pass # read all data in buffer

        reply = self._send_msg("q\r", reply_pattern="^QR(\d+)\s+\n\r\?$")
        print(f"Found a device with an ID: {reply.group(1)}")

    @remote
    def _send_msg(self, msg, reply_pattern=".*\n\r"):
        self.ser.reset_input_buffer()
        self.ser.write(msg.encode('ascii'))

        buf = self.ser.read()
        while not re.match(reply_pattern.encode('ascii'), buf):
            if reply_pattern.endswith('\?$'):
                new_data = self.ser.read_until(b'?')
            else:
                new_data = self.ser.read()
            if len(new_data) == 0:
                print(f"Buf ({len(buf)}): {buf}")
                raise IOError(f"The device did not send the expected response (got: {repr(buf)}, expected: {repr(reply_pattern)}")
            buf += new_data
        return re.match(reply_pattern, buf.decode('ascii'))

    def status(self):
        d = super().status()
        d.update(self.read_status_from_device())
        return d

    @remote
    def read_status_from_device(self):
        pattern = "^\n\rl1\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rl2\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rl3\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rl4\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rb1\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rb2\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rb3\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\rb4\s+([A-Z]+)\s+([A-Z]+)" \
                  "\n\r\?$"
        reply = self._send_msg("S", reply_pattern=pattern)
        d = {}
        for ch in range(1,5):
            d[f"channel{ch}"] = {"frequency": float(reply.group(1+4*(ch-1))),
                                 "power": float(reply.group(2+4*(ch-1))),
                                 "power_state": reply.group(3+4*(ch-1)) == 'ON',
                                 "power_control": reply.group(4+4*(ch-1)),
                                 "blanking_state": reply.group(17+2*(ch-1)) == 'ON',
                                 "blanking_control": reply.group(18+2*(ch-1))}
        return d

    @remote
    def configure_channel(self, channel:int, frequency_mhz=None, power_raw=None, power_db=None, phase=None, switch=None, internal_mode=None):
        if channel not in {1, 2, 3, 4}:
            raise Exception(f"Wrong channel number: {channel}. Expected value from 1-4")
        cmd = f'L{channel}'
        if frequency_mhz is not None:
            if frequency_mhz < 85 or frequency_mhz > 135:
                raise ValueError(f"Wrong frequency: {frequency_mhz}. Expected value between 85 and 135 MHz")
            cmd += f"F{frequency_mhz:.2f}"
        if phase is not None:
            if phase < 0 or phase > 16383:
                raise ValueError(f"Wrong phase: {phase}. Expected value between 0 and 16383")
            cmd += f"H{int(phase)}" # Assuming 'H' is the command for phase
        if power_raw is not None:
            if power_raw < 0 or power_raw > 1023:
                raise ValueError(f"Wrong power: {power_raw}. Expected value between 0 and 1023")
            cmd += f"P{int(power_raw)}"
        if power_db is not None:
            # Assuming a valid range for power_db, the original check was incomplete
            if power_db < self._POWER_DB_MIN or power_db > self._POWER_DB_MAX:
                raise ValueError(f"Wrong power: {power_db}.")
            cmd += f"D{power_db:.2f}"
        if switch is not None:
            cmd += "O1" if switch else "O0"
        if internal_mode is not None:
            cmd += "I1" if internal_mode else "I0"
        cmd += '\r'
        print(cmd)
        self._send_msg(cmd)

    @remote
    def configure_blanking(self, channel:int, blanking_on=None, internal_control=None):
        """Configure blanking settings for a channel"""
        if channel not in {1, 2, 3, 4}:
            raise Exception(f"Wrong channel number: {channel}. Expected value from 1-4")
        cmd = f'B{channel}'
        if blanking_on is not None:
            cmd += "O1" if blanking_on else "O0"
        if internal_control is not None:
            cmd += "I1" if internal_control else "I0"
        cmd += '\r'
        print(cmd)
        self._send_msg(cmd)

    @remote
    def debug_mess(self, message):
        print(str(message))


@include_remote_methods(QuadAOMWorker)
class QuadAOM(DeviceOverZeroMQ):
    # Constants for the device
    _FREQ_MIN = 85.0
    _FREQ_MAX = 135.0
    _PHASE_MIN = 0
    _PHASE_MAX = 16383
    _POWER_DB_MIN = -5.2
    _POWER_DB_MAX = 33.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Parent widget for dialogs
        self._parent_widget = None

        # Progress bar displays for channel status
        self._current_frequency_progresses = {}
        self._current_power_progresses = {}
        self._status_indicators = {}

        # Current channel being controlled
        self._current_channel = 1

    def _create_status_display(self, parent, label, min_val, max_val, suffix="", precision=1):
        """Helper method to create a progress bar for status display"""
        progress = QtWidgets.QProgressBar()
        progress.setMinimum(int(min_val * (10 ** precision)))
        progress.setMaximum(int(max_val * (10 ** precision)))
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat(f"{label} %v{suffix}")
        progress.setFixedHeight(28)
        progress.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        return progress

    def _create_status_row(self, channel):
        """Create a status row for a single channel"""
        channel_widget = QtWidgets.QWidget()
        channel_layout = QtWidgets.QHBoxLayout(channel_widget)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(5)

        # Channel label
        ch_label = QtWidgets.QLabel(f"CH{channel}")
        ch_label.setMinimumWidth(35)
        ch_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        channel_layout.addWidget(ch_label)

        # Frequency progress bar
        freq_progress = self._create_status_display(
            channel_widget, "F:", self._FREQ_MIN, self._FREQ_MAX, "MHz", precision=1
        )
        freq_progress.setMinimumWidth(140)
        channel_layout.addWidget(freq_progress)
        self._current_frequency_progresses[channel] = freq_progress

        # Power progress bar
        power_progress = self._create_status_display(
            channel_widget, "P:", self._POWER_DB_MIN, self._POWER_DB_MAX, "dB", precision=1
        )
        power_progress.setMinimumWidth(140)
        channel_layout.addWidget(power_progress)
        self._current_power_progresses[channel] = power_progress

        # Status indicators container
        status_widget = QtWidgets.QWidget()
        status_widget.setFixedWidth(80)
        status_widget_layout = QtWidgets.QHBoxLayout(status_widget)
        status_widget_layout.setContentsMargins(0, 0, 0, 0)
        status_widget_layout.setSpacing(3)

        # Power status indicator
        power_indicator = QtWidgets.QLabel("PWR")
        power_indicator.setFixedSize(25, 25)
        power_indicator.setAlignment(QtCore.Qt.AlignCenter)
        power_indicator.setStyleSheet("background-color: #ff6666; border: 1px solid black; font-size: 9px; font-weight: bold;")
        status_widget_layout.addWidget(power_indicator)

        # Blanking status indicator
        blank_indicator = QtWidgets.QLabel("BLK")
        blank_indicator.setFixedSize(25, 25)
        blank_indicator.setAlignment(QtCore.Qt.AlignCenter)
        blank_indicator.setStyleSheet("background-color: #ff6666; border: 1px solid black; font-size: 9px; font-weight: bold;")
        status_widget_layout.addWidget(blank_indicator)

        # Control mode indicators
        pmode_indicator = QtWidgets.QLabel("PI")
        pmode_indicator.setFixedSize(20, 25)
        pmode_indicator.setAlignment(QtCore.Qt.AlignCenter)
        pmode_indicator.setStyleSheet("background-color: #3399ff; border: 1px solid black; font-size: 8px; font-weight: bold;")
        status_widget_layout.addWidget(pmode_indicator)

        channel_layout.addWidget(status_widget)

        # Store indicators for updates
        self._status_indicators[channel] = {
            'power': power_indicator,
            'blanking': blank_indicator,
            'power_mode': pmode_indicator
        }

        return channel_widget

    def _create_control_panel(self):
        """Create the common control panel"""
        control_group = QtWidgets.QGroupBox("Control Panel")
        control_group.setStyleSheet("QGroupBox { font-weight: bold; color: white; font-size: 14px; }")
        control_group.setMinimumWidth(300)
        control_group.setMaximumWidth(350)
        control_layout = QtWidgets.QVBoxLayout(control_group)
        control_layout.setSpacing(5)

        # Channel selector
        channel_selector_layout = QtWidgets.QHBoxLayout()
        channel_label = QtWidgets.QLabel("Select Channel:")
        channel_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        channel_selector_layout.addWidget(channel_label)

        self._channel_selector = QtWidgets.QComboBox()
        self._channel_selector.addItems(["Channel 1", "Channel 2", "Channel 3", "Channel 4"])
        self._channel_selector.setStyleSheet("font-size: 12px; padding: 3px;")
        self._channel_selector.currentIndexChanged.connect(self._on_channel_changed)
        channel_selector_layout.addWidget(self._channel_selector)

        control_layout.addLayout(channel_selector_layout)

        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        control_layout.addWidget(separator)

        # Frequency control
        freq_layout = QtWidgets.QHBoxLayout()
        freq_label = QtWidgets.QLabel("Frequency:")
        freq_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        freq_label.setMinimumWidth(80)
        freq_layout.addWidget(freq_label)

        self._freq_input = QtWidgets.QLineEdit()
        self._freq_input.setValidator(QtGui.QDoubleValidator(self._FREQ_MIN, self._FREQ_MAX, 2))
        self._freq_input.setText(f"{self._FREQ_MIN:.1f}")
        self._freq_input.setFixedWidth(80)
        self._freq_input.setStyleSheet("font-size: 12px; padding: 3px;")
        freq_layout.addWidget(self._freq_input)

        freq_unit = QtWidgets.QLabel("MHz")
        freq_unit.setStyleSheet("font-size: 12px;")
        freq_layout.addWidget(freq_unit)
        freq_layout.addStretch()

        control_layout.addLayout(freq_layout)

        # Power control
        power_layout = QtWidgets.QHBoxLayout()
        power_label = QtWidgets.QLabel("Power:")
        power_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        power_label.setMinimumWidth(80)
        power_layout.addWidget(power_label)

        self._power_input = QtWidgets.QLineEdit()
        self._power_input.setValidator(QtGui.QDoubleValidator(self._POWER_DB_MIN, self._POWER_DB_MAX, 1))
        self._power_input.setText("0.0")
        self._power_input.setFixedWidth(80)
        self._power_input.setStyleSheet("font-size: 12px; padding: 3px;")
        power_layout.addWidget(self._power_input)

        power_unit = QtWidgets.QLabel("dB")
        power_unit.setStyleSheet("font-size: 12px;")
        power_layout.addWidget(power_unit)
        power_layout.addStretch()

        control_layout.addLayout(power_layout)

        # Phase control
        phase_layout = QtWidgets.QHBoxLayout()
        phase_label = QtWidgets.QLabel("Phase:")
        phase_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        phase_label.setMinimumWidth(80)
        phase_layout.addWidget(phase_label)

        self._phase_input = QtWidgets.QLineEdit()
        self._phase_input.setValidator(QtGui.QIntValidator(self._PHASE_MIN, self._PHASE_MAX))
        self._phase_input.setText("0")
        self._phase_input.setFixedWidth(80)
        self._phase_input.setStyleSheet("font-size: 12px; padding: 3px;")
        phase_layout.addWidget(self._phase_input)
        phase_layout.addStretch()

        control_layout.addLayout(phase_layout)

        # Toggle buttons
        button_layout = QtWidgets.QGridLayout()
        button_layout.setSpacing(5)

        # Power toggle
        self._power_toggle = QtWidgets.QPushButton("PWR OFF")
        self._power_toggle.setCheckable(True)
        self._power_toggle.setMinimumHeight(28)
        self._power_toggle.setStyleSheet("""
            QPushButton {
                background-color: #ff6666; font-weight: bold; font-size: 11px;
                border: 2px solid #333; border-radius: 5px;
            }
            QPushButton:checked { background-color: #66ff66; }
            QPushButton:hover { border: 2px solid #666; }
        """)
        self._power_toggle.toggled.connect(self._on_power_toggle)
        button_layout.addWidget(self._power_toggle, 0, 0)

        # Power mode toggle
        self._power_mode_toggle = QtWidgets.QPushButton("PWR EXT")
        self._power_mode_toggle.setCheckable(True)
        self._power_mode_toggle.setMinimumHeight(28)
        self._power_mode_toggle.setStyleSheet("""
            QPushButton {
                background-color: #3399ff; font-weight: bold; font-size: 11px;
                border: 2px solid #333; border-radius: 5px;
            }
            QPushButton:checked { background-color: #ff9933; }
            QPushButton:hover { border: 2px solid #666; }
        """)
        self._power_mode_toggle.toggled.connect(self._on_power_mode_toggle)
        button_layout.addWidget(self._power_mode_toggle, 0, 1)

        # Blanking toggle
        self._blanking_toggle = QtWidgets.QPushButton("BLK OFF")
        self._blanking_toggle.setCheckable(True)
        self._blanking_toggle.setMinimumHeight(28)
        self._blanking_toggle.setStyleSheet("""
            QPushButton {
                background-color: #ff6666; font-weight: bold; font-size: 11px;
                border: 2px solid #333; border-radius: 5px;
            }
            QPushButton:checked { background-color: #66ff66; }
            QPushButton:hover { border: 2px solid #666; }
        """)
        self._blanking_toggle.toggled.connect(self._on_blanking_toggle)
        button_layout.addWidget(self._blanking_toggle, 1, 0)

        # Blanking mode toggle
        self._blanking_mode_toggle = QtWidgets.QPushButton("BLK EXT")
        self._blanking_mode_toggle.setCheckable(True)
        self._blanking_mode_toggle.setMinimumHeight(28)
        self._blanking_mode_toggle.setStyleSheet("""
            QPushButton {
                background-color: #3399ff; font-weight: bold; font-size: 11px;
                border: 2px solid #333; border-radius: 5px;
            }
            QPushButton:checked { background-color: #ff9933; }
            QPushButton:hover { border: 2px solid #666; }
        """)
        self._blanking_mode_toggle.toggled.connect(self._on_blanking_mode_toggle)
        button_layout.addWidget(self._blanking_mode_toggle, 1, 1)

        control_layout.addLayout(button_layout)

        # Separator for extra buttons
        separator2 = QtWidgets.QFrame()
        separator2.setFrameShape(QtWidgets.QFrame.HLine)
        separator2.setFrameShadow(QtWidgets.QFrame.Sunken)
        control_layout.addWidget(separator2)

        # Calibrate and Presets buttons
        extra_buttons_layout = QtWidgets.QHBoxLayout()

        self._calibrate_button = QtWidgets.QPushButton("CALIBRATE")
        self._calibrate_button.setMinimumHeight(28)
        self._calibrate_button.setStyleSheet("font-weight: bold;")
        self._calibrate_button.clicked.connect(self._open_calibrate_window)
        extra_buttons_layout.addWidget(self._calibrate_button)

        self._presets_button = QtWidgets.QPushButton("PRESETS")
        self._presets_button.setMinimumHeight(28)
        self._presets_button.setStyleSheet("font-weight: bold;")
        self._presets_button.clicked.connect(self._open_presets_window)
        extra_buttons_layout.addWidget(self._presets_button)

        control_layout.addLayout(extra_buttons_layout)

        # Apply button
        apply_button = QtWidgets.QPushButton("APPLY SETTINGS")
        apply_button.setMinimumHeight(32)
        apply_button.setStyleSheet("""
            QPushButton {
                background-color: #99ccff; font-weight: bold; font-size: 14px;
                border: 2px solid #333; border-radius: 5px;
            }
            QPushButton:hover { background-color: #77aadd; border: 2px solid #555; }
            QPushButton:pressed { background-color: #5588bb; }
        """)
        apply_button.clicked.connect(self._apply_current_channel_settings)
        control_layout.addWidget(apply_button)

        return control_group

    def _open_calibrate_window(self):
        """Opens an empty calibration pop-up window."""
        dialog = QtWidgets.QDialog(self._parent_widget)
        dialog.setWindowTitle("Calibration")
        dialog.setMinimumSize(300, 200)
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel("Calibration window is under construction.")
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label)
        dialog.exec_()

    def _open_presets_window(self):
        """Opens an empty presets pop-up window."""
        dialog = QtWidgets.QDialog(self._parent_widget)
        dialog.setWindowTitle("Channel 4 Presets")
        dialog.setMinimumSize(300, 200)
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel("Presets window is under construction.")
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label)
        dialog.exec_()

    def _on_channel_changed(self, index):
        """Called when channel selector changes"""
        self._current_channel = index + 1
        # Show PRESETS button only for channel 4
        self._presets_button.setVisible(self._current_channel == 4)
        self._load_channel_settings(self._current_channel)

    def _load_channel_settings(self, channel):
        """Load settings for the specified channel into the control widgets"""
        try:
            status = self.status()
            channel_data = status[f'channel{channel}']

            # Update controls with current channel settings
            self._freq_input.setText(f"{channel_data['frequency']:.1f}")
            self._power_input.setText(f"{channel_data['power']:.1f}")
            self._phase_input.setText("0") # Reset phase to default on channel change

            # Update toggle buttons
            self._power_toggle.blockSignals(True)
            self._power_toggle.setChecked(channel_data['power_state'])
            self._power_toggle.setText('PWR ON' if channel_data['power_state'] else 'PWR OFF')
            self._power_toggle.blockSignals(False)

            self._power_mode_toggle.blockSignals(True)
            is_internal = channel_data['power_control'] == 'INT'
            self._power_mode_toggle.setChecked(is_internal)
            self._power_mode_toggle.setText('PWR INT' if is_internal else 'PWR EXT')
            self._power_mode_toggle.blockSignals(False)

            self._blanking_toggle.blockSignals(True)
            self._blanking_toggle.setChecked(channel_data['blanking_state'])
            self._blanking_toggle.setText('BLK ON' if channel_data['blanking_state'] else 'BLK OFF')
            self._blanking_toggle.blockSignals(False)

            self._blanking_mode_toggle.blockSignals(True)
            is_blanking_internal = channel_data['blanking_control'] == 'INT B'
            self._blanking_mode_toggle.setChecked(is_blanking_internal)
            self._blanking_mode_toggle.setText('BLK INT' if is_blanking_internal else 'BLK EXT')
            self._blanking_mode_toggle.blockSignals(False)

        except Exception as e:
            print(f"Error loading channel {channel} settings: {e}")

    def _apply_current_channel_settings(self):
        """Apply settings for the currently selected channel"""
        try:
            frequency = float(self._freq_input.text())
            power_db = float(self._power_input.text())
            phase = int(self._phase_input.text())
            power_on = self._power_toggle.isChecked()
            power_internal = self._power_mode_toggle.isChecked()
            blanking_on = self._blanking_toggle.isChecked()
            blanking_internal = self._blanking_mode_toggle.isChecked()

            # Configure channel
            self.configure_channel(
                channel=self._current_channel,
                frequency_mhz=frequency,
                power_db=power_db,
                phase=phase,
                switch=power_on,
                internal_mode=power_internal
            )

            # Configure blanking
            self.configure_blanking(
                channel=self._current_channel,
                blanking_on=blanking_on,
                internal_control=blanking_internal
            )

        except Exception as e:
            print(f"Error applying channel {self._current_channel} settings: {e}")

    def _on_power_toggle(self, checked):
        """Handle power toggle button"""
        self._power_toggle.setText('PWR ON' if checked else 'PWR OFF')

    def _on_power_mode_toggle(self, checked):
        """Handle power mode toggle button"""
        self._power_mode_toggle.setText('PWR INT' if checked else 'PWR EXT')

    def _on_blanking_toggle(self, checked):
        """Handle blanking toggle button"""
        self._blanking_toggle.setText('BLK ON' if checked else 'BLK OFF')

    def _on_blanking_mode_toggle(self, checked):
        """Handle blanking mode toggle button"""
        self._blanking_mode_toggle.setText('BLK INT' if checked else 'BLK EXT')

    def createDock(self, parentWidget, menu=None):
        self._parent_widget = parentWidget
        main_widget = QtWidgets.QWidget(parentWidget)
        dock = QtWidgets.QDockWidget("QuadAOM Controller", parentWidget)
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_widget.setLayout(main_layout)

        # Create main horizontal layout: status on left, controls on right
        control_container = QtWidgets.QWidget()
        control_layout = QtWidgets.QHBoxLayout(control_container)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(20)

        # Left side - Status display
        status_group = QtWidgets.QGroupBox("Channel Status")
        status_group.setStyleSheet("QGroupBox { font-weight: bold; color: white; font-size: 14px; }")
        status_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        status_layout = QtWidgets.QVBoxLayout(status_group)
        status_layout.setSpacing(8)

        # Create status rows for each channel
        for ch in range(1, 5):
            status_row = self._create_status_row(ch)
            status_layout.addWidget(status_row)

        control_layout.addWidget(status_group)

        # Right side - Control panel
        control_panel = self._create_control_panel()
        control_layout.addWidget(control_panel)

        # Add the control container to the main layout
        main_layout.addWidget(control_container)

        # Set up the dock widget
        dock.setWidget(main_widget)
        dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        # Initialize with channel 1
        self._current_channel = 1
        self._presets_button.setVisible(False) # Initially hide for CH1
        self._load_channel_settings(1)

        # Create listener thread for updates
        self.createListenerThread(self.updateSlot)

    def updateSlot(self, status):
        """This function receives periodic updates from the worker"""
        try:
            for ch in range(1, 5):
                channel_data = status[f'channel{ch}']

                # Update frequency progress bar
                freq_value = channel_data['frequency']
                freq_progress = self._current_frequency_progresses[ch]
                freq_progress.setValue(int(freq_value * 10))
                freq_progress.setFormat(f"F: {freq_value:.1f}MHz")

                # Update power progress bar
                power_db = channel_data['power']
                power_progress = self._current_power_progresses[ch]
                power_progress.setValue(int(power_db * 10))
                power_progress.setFormat(f"P: {power_db:.1f}dB")

                # Color code the power progress bar
                if power_db > 25:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff0000; }")
                elif power_db > 15:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff9900; }")
                else:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #00aa00; }")

                # Update status indicators
                indicators = self._status_indicators[ch]

                # Power indicator
                indicators['power'].setStyleSheet(
                    f"background-color: {'#66ff66' if channel_data['power_state'] else '#ff6666'}; "
                    "border: 1px solid black; font-size: 9px; font-weight: bold;"
                )

                # Blanking indicator
                indicators['blanking'].setStyleSheet(
                    f"background-color: {'#66ff66' if channel_data['blanking_state'] else '#ff6666'}; "
                    "border: 1px solid black; font-size: 9px; font-weight: bold;"
                )

                # Power mode indicator
                indicators['power_mode'].setStyleSheet(
                    f"background-color: {'#ff9933' if channel_data['power_control'] == 'INT' else '#3399ff'}; "
                    "border: 1px solid black; font-size: 8px; font-weight: bold;"
                )

            # Update current channel controls if they're not being edited
            if hasattr(self, '_current_channel'):
                current_data = status[f'channel{self._current_channel}']
                if not self._freq_input.hasFocus():
                    self._freq_input.setText(f"{current_data['frequency']:.1f}")
                if not self._power_input.hasFocus():
                    self._power_input.setText(f"{current_data['power']:.1f}")

        except Exception as e:
            print(f"Error while updating Quad AOM GUI: {e}")
