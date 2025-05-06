# -*- coding: utf-8 -*-
"""
Support for QuadAOM - 4-channel AOM driver from AA Opto with enhanced GUI
"""

from devices.zeromq_device import DeviceWorker, DeviceOverZeroMQ, remote, include_remote_methods
from PyQt5 import QtWidgets, QtCore, QtGui
import threading
import time
import numpy as np
import re


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
        #d["voltage"] = self.voltage()
        #d["phase"] = voltage2phase(d["voltage"])
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
        if power_raw is not None:
            if power_raw < 0 or power_raw > 1023:
                raise ValueError(f"Wrong power: {power_raw}. Expected value between 0 and 1023")
            cmd += f"P{int(power_raw)}"
        if power_db is not None:
            if power_db < 0 or power_db > 1023:
                raise ValueError(f"Wrong power: {power_db}. Expected value between 0 and ???")
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

        # Status display elements for showing current device state
        self._current_frequency_displays = {}
        self._current_phase_displays = {}
        self._current_power_displays = {}
        self._current_switch_indicators = {}
        self._current_internal_mode_indicators = {}
        # New indicators for blanking
        self._current_blanking_state_indicators = {}
        self._current_blanking_control_indicators = {}

        # Control elements for the interactive tab
        self._channel_controls = {}

    def _create_status_display(self, parent, label, min_val, max_val, suffix="", precision=1):
        """Helper method to create a labeled status display for current values with stretchable labels"""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Label - now stretchable
        label_widget = QtWidgets.QLabel(label)
        layout.addWidget(label_widget)

        # Value display - stretchable but with minimum width
        value_display = QtWidgets.QLabel(f"0.0{suffix}")
        value_display.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Sunken)
        value_display.setMinimumWidth(60)
        value_display.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        value_display.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        value_display.setStyleSheet("background-color: #000000;")
        layout.addWidget(value_display)

        # Progress bar for visual indicator - stretchable
        progress = QtWidgets.QProgressBar()
        progress.setMinimum(int(min_val * (10 ** precision)))
        progress.setMaximum(int(max_val * (10 ** precision)))
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(15)
        progress.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(progress)

        return container, value_display, progress

    def _create_channel_control_group(self, channel):
        """Create control elements for a channel with the specified layout"""
        group = QtWidgets.QGroupBox(f"Channel {channel}")
        group.setStyleSheet("QGroupBox { font-weight: bold; color: white }")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(5, 5, 5, 5)

        controls = {}

        # 1st row - 2 textboxes to adjust power in dB and frequency in MHz
        row1 = QtWidgets.QHBoxLayout()

        # Frequency control
        freq_container = QtWidgets.QWidget()
        freq_layout = QtWidgets.QHBoxLayout(freq_container)
        freq_layout.setContentsMargins(0, 0, 0, 0)

        freq_label = QtWidgets.QLabel("Frequency:")
        freq_layout.addWidget(freq_label)

        freq_input = QtWidgets.QLineEdit()
        freq_input.setValidator(QtGui.QDoubleValidator(self._FREQ_MIN, self._FREQ_MAX, 2))
        freq_input.setText(f"{self._FREQ_MIN:.1f}")
        freq_input.setFixedWidth(60)
        freq_layout.addWidget(freq_input)

        freq_unit = QtWidgets.QLabel("MHz")
        freq_layout.addWidget(freq_unit)

        row1.addWidget(freq_container)
        controls['frequency_input'] = freq_input

        # Power control
        power_container = QtWidgets.QWidget()
        power_layout = QtWidgets.QHBoxLayout(power_container)
        power_layout.setContentsMargins(0, 0, 0, 0)

        power_label = QtWidgets.QLabel("Power:")
        power_layout.addWidget(power_label)

        power_input = QtWidgets.QLineEdit()
        power_input.setValidator(QtGui.QDoubleValidator(self._POWER_DB_MIN, self._POWER_DB_MAX, 1))
        power_input.setText("0.0")
        power_input.setFixedWidth(60)
        power_layout.addWidget(power_input)

        power_unit = QtWidgets.QLabel("dB")
        power_layout.addWidget(power_unit)

        row1.addWidget(power_container)
        controls['power_input'] = power_input

        layout.addLayout(row1)

        # 2nd row - 2 buttons to adjust power and external/internal mode of control
        row2 = QtWidgets.QHBoxLayout()

        power_toggle = QtWidgets.QPushButton("Power OFF")
        power_toggle.setCheckable(True)
        power_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        power_toggle.setStyleSheet("QPushButton { background-color: #ff6666; } QPushButton:checked { background-color: #66ff66; }")
        power_toggle.toggled.connect(lambda state: self.configure_channel(channel, switch=not self.status()[f'channel{channel}']['power_state']))
        row2.addWidget(power_toggle)
        controls['power_toggle'] = power_toggle

        power_mode_toggle = QtWidgets.QPushButton("EXTERNAL")
        power_mode_toggle.setCheckable(True)
        power_mode_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        power_mode_toggle.setStyleSheet("QPushButton { background-color: #3399ff; } QPushButton:checked { background-color: #ff9933; }")
        power_mode_toggle.toggled.connect(lambda state: self.configure_channel(channel, internal_mode=self.status()[f'channel{channel}']['power_control']=='EXTERNAL'))
        row2.addWidget(power_mode_toggle)
        controls['power_mode_toggle'] = power_mode_toggle

        layout.addLayout(row2)

        # 3rd row - 2 buttons to adjust power and int/ext mode of blanking
        row3 = QtWidgets.QHBoxLayout()

        blanking_toggle = QtWidgets.QPushButton("Blanking OFF")
        blanking_toggle.setCheckable(True)
        blanking_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        blanking_toggle.setStyleSheet("QPushButton { background-color: #ff6666; } QPushButton:checked { background-color: #66ff66; }")
        blanking_toggle.toggled.connect(lambda state: self.configure_blanking(channel, blanking_on=not self.status()[f'channel{channel}']['blanking_state']))
        row3.addWidget(blanking_toggle)
        controls['blanking_toggle'] = blanking_toggle

        blanking_mode_toggle = QtWidgets.QPushButton("Ext Blanking")
        blanking_mode_toggle.setCheckable(True)
        blanking_mode_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        blanking_mode_toggle.setStyleSheet("QPushButton { background-color: #3399ff; } QPushButton:checked { background-color: #ff9933; }")
        blanking_mode_toggle.toggled.connect(lambda checked: blanking_mode_toggle.setText('Int Blanking' if checked else 'Ext Blanking'))
        row3.addWidget(blanking_mode_toggle)
        controls['blanking_mode_toggle'] = blanking_mode_toggle

        layout.addLayout(row3)

        # Last row - slider to adjust phase
        row4 = QtWidgets.QVBoxLayout()

        # Phase slider label and value display
        phase_header = QtWidgets.QHBoxLayout()
        phase_label = QtWidgets.QLabel("Phase:")
        phase_header.addWidget(phase_label)

        phase_value = QtWidgets.QLabel("0")
        phase_value.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Sunken)
        phase_value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        phase_value.setStyleSheet("background-color: #000000;")
        phase_value.setMinimumWidth(60)
        phase_header.addWidget(phase_value)

        row4.addLayout(phase_header)

        # Phase slider
        phase_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        phase_slider.setMinimum(self._PHASE_MIN)
        phase_slider.setMaximum(self._PHASE_MAX)
        phase_slider.setValue(0)
        phase_slider.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        phase_slider.valueChanged.connect(lambda v: phase_value.setText(str(v)))
        row4.addWidget(phase_slider)

        layout.addLayout(row4)
        controls['phase_slider'] = phase_slider
        controls['phase_value'] = phase_value

        # Apply button at the very bottom
        apply_button = QtWidgets.QPushButton("Apply Settings")
        apply_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        apply_button.setStyleSheet("background-color: #99ccff;")
        apply_button.clicked.connect(lambda: self._apply_channel_settings(channel))
        layout.addWidget(apply_button)
        controls['apply_button'] = apply_button

        # Store controls for later access
        self._channel_controls[channel] = controls

        return group

    def _apply_channel_settings(self, channel):
        """Apply channel settings when Apply button is clicked"""
        controls = self._channel_controls[channel]

        try:
            # Get values from controls
            frequency = float(controls['frequency_input'].text())
            power_db = float(controls['power_input'].text())
            phase = controls['phase_slider'].value()
            power_on = controls['power_toggle'].isChecked()
            power_internal = controls['power_mode_toggle'].isChecked()
            blanking_on = controls['blanking_toggle'].isChecked()
            blanking_internal = controls['blanking_mode_toggle'].isChecked()

            # Configure channel
            self.configure_channel(
                channel=channel,
                frequency_mhz=frequency,
                power_db=power_db,
                phase=phase,
                switch=power_on,
                internal_mode=power_internal
            )

            # Configure blanking
            self.configure_blanking(
                channel=channel,
                blanking_on=blanking_on,
                internal_control=blanking_internal
            )

        except Exception as e:
            print(f"Error applying channel {channel} settings: {e}")
            # Optionally, show error message to user
            error_dialog = QtWidgets.QMessageBox()
            error_dialog.setIcon(QtWidgets.QMessageBox.Critical)
            error_dialog.setText(f"Error applying settings: {str(e)}")
            error_dialog.setWindowTitle("Error")
            error_dialog.exec_()

    def createDock(self, parentWidget, menu=None):
        main_widget = QtWidgets.QWidget(parentWidget)
        dock = QtWidgets.QDockWidget("4xAOM", parentWidget)
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)  # Reduce margins
        main_widget.setLayout(main_layout)

        # Create a tab widget for status and control tabs
        tab_widget = QtWidgets.QTabWidget()
        main_layout.addWidget(tab_widget)

        # --------- STATUS TAB ---------
        status_tab = QtWidgets.QWidget()
        status_layout = QtWidgets.QVBoxLayout(status_tab)
        status_layout.setSpacing(5)  # Reduce spacing
        status_layout.setContentsMargins(3, 3, 3, 3)  # Reduce margins

        # Status display layout - Changed to QGridLayout for better space management
        channels_layout = QtWidgets.QGridLayout()
        channels_layout.setSpacing(5)  # Reduce spacing
        status_layout.addLayout(channels_layout, 1)  # Add stretch factor

        # Create channel groups for status display
        for ch in range(1, 5):
            # Status group
            status_group = QtWidgets.QGroupBox(f"Channel {ch}")
            status_group.setStyleSheet("QGroupBox { font-weight: bold; color: white}")
            status_group_layout = QtWidgets.QVBoxLayout(status_group)
            status_group_layout.setSpacing(3)  # Reduce spacing for tighter look
            status_group_layout.setContentsMargins(3, 10, 3, 3)  # Tighter margins

            # Make the group expand in all directions
            status_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

            # Channel status displays
            freq_display, freq_value, freq_progress = self._create_status_display(
                status_group, "Frequ:", self._FREQ_MIN, self._FREQ_MAX, " MHz", precision=1
            )
            self._current_frequency_displays[ch] = (freq_value, freq_progress)
            status_group_layout.addWidget(freq_display)

            power_display, power_value, power_progress = self._create_status_display(
                status_group, "Power:", self._POWER_DB_MIN, self._POWER_DB_MAX, " dB", precision=1
            )
            self._current_power_displays[ch] = (power_value, power_progress)
            status_group_layout.addWidget(power_display)

            # Create grid layout for status indicators (2x2 grid)
            indicators_grid = QtWidgets.QGridLayout()
            indicators_grid.setSpacing(3)  # Tighter spacing
            indicators_grid.setColumnStretch(0, 1)  # Make columns stretch equally
            indicators_grid.setColumnStretch(1, 1)
            indicators_grid.setRowStretch(0, 1)  # Make rows stretch equally
            indicators_grid.setRowStretch(1, 1)
            status_group_layout.addLayout(indicators_grid)

            # Status indicators for switch and internal mode
            switch_indicator = QtWidgets.QLabel("Output: OFF")
            # Force the indicator to expand both horizontally and vertically
            switch_indicator.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            switch_indicator.setStyleSheet("background-color: #ffcccc; padding: 3px; border-radius: 3px; color: black;")
            self._current_switch_indicators[ch] = switch_indicator
            indicators_grid.addWidget(switch_indicator, 0, 0)

            mode_indicator = QtWidgets.QLabel("External")
            # Force the indicator to expand both horizontally and vertically
            mode_indicator.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            mode_indicator.setStyleSheet("background-color: #ccccff; padding: 3px; border-radius: 3px; color: black;")
            self._current_internal_mode_indicators[ch] = mode_indicator
            indicators_grid.addWidget(mode_indicator, 0, 1)

            # Add blanking status indicators in the 2x2 grid
            blanking_state = QtWidgets.QLabel("Blanking: OFF")
            # Force the indicator to expand both horizontally and vertically
            blanking_state.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            blanking_state.setStyleSheet("background-color: #ffddcc; padding: 3px; border-radius: 3px; color: black;")
            self._current_blanking_state_indicators[ch] = blanking_state
            indicators_grid.addWidget(blanking_state, 1, 0)

            blanking_control = QtWidgets.QLabel("External")
            # Force the indicator to expand both horizontally and vertically
            blanking_control.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            blanking_control.setStyleSheet("background-color: #ccffdd; padding: 3px; border-radius: 3px; color: black;")
            self._current_blanking_control_indicators[ch] = blanking_control
            indicators_grid.addWidget(blanking_control, 1, 1)

            # Add vertical stretch to push content to the top and fill extra space
            status_group_layout.addStretch(1)

            # Add to grid layout with equal columns
            col = (ch - 1) % 2
            row = (ch - 1) // 2
            channels_layout.addWidget(status_group, row, col)

            # Set column and row stretch factors
            channels_layout.setColumnStretch(col, 1)
            channels_layout.setRowStretch(row, 1)

        # Add stretch to main layout to push content up
        status_layout.addStretch(1)

        # Add the status tab to the tab widget
        tab_widget.addTab(status_tab, "Status")

        # --------- CONTROL TAB ---------
        control_tab = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout(control_tab)
        control_layout.setContentsMargins(5, 5, 5, 5)

        # Control display layout
        control_channels_layout = QtWidgets.QHBoxLayout()
        control_layout.addLayout(control_channels_layout)

        # Create channel control groups
        for ch in range(1, 5):
            # Create control group with all interactive elements
            control_group = self._create_channel_control_group(ch)
            control_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            control_channels_layout.addWidget(control_group)

        # Add the control tab to the tab widget
        tab_widget.addTab(control_tab, "Controls")

        # Set up the dock widget
        dock.setWidget(main_widget)
        dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        # Create listener thread for updates
        self.createListenerThread(self.updateSlot)

    def updateSlot(self, status):
        """ This function receives periodic updates from the worker """
        try:
            for ch in range(1, 5):
                channel_data = status[f'channel{ch}']

                # Update frequency display
                freq_value = channel_data['frequency']
                freq_label, freq_progress = self._current_frequency_displays[ch]
                freq_label.setText(f"{freq_value:.1f} MHz")
                freq_progress.setValue(int(freq_value * 10))

                # Update power display
                power_db = channel_data['power']
                power_label, power_progress = self._current_power_displays[ch]
                power_label.setText(f"{power_db:.1f} dB")
                power_progress.setValue(int(power_db * 10))

                # Color code the power progress bar based on value
                if power_db > 25:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff0000; }")
                elif power_db > 15:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff9900; }")
                else:
                    power_progress.setStyleSheet("QProgressBar::chunk { background-color: #00aa00; }")

                # Update switch and mode indicators
                is_on = channel_data['power_state']
                self._current_switch_indicators[ch].setText(f"Output: {'ON' if is_on else 'OFF'}")
                self._current_switch_indicators[ch].setStyleSheet(
                    f"background-color: {'#66ff66' if is_on else '#ff6666'}; padding: 3px; border-radius: 3px; color: black"
                )

                is_internal = channel_data['power_control'] == 'INT'
                self._current_internal_mode_indicators[ch].setText(f"{'Internal' if is_internal else 'External'}")
                self._current_internal_mode_indicators[ch].setStyleSheet(
                    f"background-color: {'#ff9933' if is_internal else '#3399ff'}; padding: 3px; border-radius: 3px; color: black"
                )

                # Update blanking indicators
                is_blanking_on = channel_data['blanking_state']
                self._current_blanking_state_indicators[ch].setText(f"Blanking: {'ON' if is_blanking_on else 'OFF'}")
                self._current_blanking_state_indicators[ch].setStyleSheet(
                    f"background-color: {'#66ff66' if is_blanking_on else '#ff6666'}; padding: 3px; border-radius: 3px; color: black"
                )

                is_blanking_internal = channel_data['blanking_control'] == 'INT'
                self._current_blanking_control_indicators[ch].setText(f"{'Internal' if is_blanking_internal else 'External'}")
                self._current_blanking_control_indicators[ch].setStyleSheet(
                    f"background-color: {'#ff9933' if is_blanking_internal else '#3399ff'}; padding: 3px; border-radius: 3px; color: black"
                )

                # Also update the control elements to match current state if they exist
                if ch in self._channel_controls:
                    controls = self._channel_controls[ch]
                    # Only update if not being edited by user
                    if not controls['frequency_input'].hasFocus():
                        controls['frequency_input'].setText(f"{freq_value:.1f}")
                    if not controls['power_input'].hasFocus():
                        controls['power_input'].setText(f"{power_db:.1f}")

                    expected_text = 'Power ON' if is_on else 'Power OFF'
                    if controls['power_toggle'].isChecked() != is_on or controls['power_toggle'].text() != expected_text:
                        controls['power_toggle'].blockSignals(True)
                        controls['power_toggle'].setChecked(is_on)
                        controls['power_toggle'].setText(expected_text)
                        controls['power_toggle'].blockSignals(False)

                    expected_text = 'INTERNAL' if is_internal else 'EXTERNAL'
                    if controls['power_mode_toggle'].isChecked() != is_internal or controls['power_mode_toggle'].text() != expected_text:
                        controls['power_mode_toggle'].blockSignals(True)
                        controls['power_mode_toggle'].setChecked(is_internal)
                        controls['power_mode_toggle'].setText('INTERNAL' if is_internal else 'EXTERNAL')
                        controls['power_mode_toggle'].blockSignals(False)

                    expected_text = 'Blanking ON' if is_blanking_on else 'Blanking OFF'
                    if controls['blanking_toggle'].isChecked() != is_blanking_on or controls['blanking_toggle'].text() != expected_text:
                        controls['blanking_toggle'].blockSignals(True)
                        controls['blanking_toggle'].setChecked(is_blanking_on)
                        controls['blanking_toggle'].setText('Blanking ON' if is_blanking_on else 'Blanking OFF')
                        controls['blanking_toggle'].blockSignals(False)

                    controls['blanking_mode_toggle'].blockSignals(True)
                    controls['blanking_mode_toggle'].setChecked(is_blanking_internal)
                    controls['blanking_mode_toggle'].setText('Int Blanking' if is_blanking_internal else 'Ext Blanking')
                    controls['blanking_mode_toggle'].blockSignals(False)

        except Exception as e:
            print(f"Error while updating Quad AOM GUI: {e}")
