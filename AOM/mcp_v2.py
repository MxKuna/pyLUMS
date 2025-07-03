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

		# Progress bar displays for channel status
		self._current_frequency_progresses = {}
		self._current_power_progresses = {}

		# Control elements for the interactive tab
		self._channel_controls = {}

	def _create_status_display(self, parent, label, min_val, max_val, suffix="", precision=1):
		"""Helper method to create a progress bar for status display"""
		# Progress bar for visual indicator
		progress = QtWidgets.QProgressBar()
		progress.setMinimum(int(min_val * (10 ** precision)))
		progress.setMaximum(int(max_val * (10 ** precision)))
		progress.setValue(0)
		progress.setTextVisible(True)
		progress.setFormat(f"{label} %v{suffix}")
		progress.setFixedHeight(15)
		progress.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

		return progress

	def _create_channel_control_group(self, channel):
		"""Create control elements for a channel with the specified layout"""
		group = QtWidgets.QGroupBox(f"Channel {channel}")
		group.setStyleSheet("QGroupBox { font-weight: bold; color: white }")
		layout = QtWidgets.QVBoxLayout(group)
		layout.setContentsMargins(5, 5, 5, 5)

		controls = {}

		# Status progress bars
		freq_progress = self._create_status_display(
				group, "Freq:", self._FREQ_MIN, self._FREQ_MAX, " MHz", precision=1
		)
		layout.addWidget(freq_progress)
		self._current_frequency_progresses[channel] = freq_progress

		power_progress = self._create_status_display(
				group, "Power:", self._POWER_DB_MIN, self._POWER_DB_MAX, " dB", precision=1
		)
		layout.addWidget(power_progress)
		self._current_power_progresses[channel] = power_progress

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
		power_mode_toggle.toggled.connect(lambda state: self.configure_channel(channel, internal_mode=self.status()[f'channel{channel}']['power_control'] == 'EXTERNAL'))
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

		# Control layout - grid with 2x2 arrangement
		control_grid = QtWidgets.QGridLayout()
		control_grid.setSpacing(5)  # Reduce spacing
		main_layout.addLayout(control_grid)

		# Create channel control groups in a 2x2 grid
		for ch in range(1, 5):
			row = (ch - 1) // 2
			col = (ch - 1) % 2

			# Create control group with all interactive elements
			control_group = self._create_channel_control_group(ch)
			control_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
			control_grid.addWidget(control_group, row, col)

			# Set equal stretch for columns and rows
			control_grid.setColumnStretch(col, 1)
			control_grid.setRowStretch(row, 1)

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

				# Update frequency progress bar
				freq_value = channel_data['frequency']
				freq_progress = self._current_frequency_progresses[ch]
				freq_progress.setValue(int(freq_value * 10))
				freq_progress.setFormat(f"Freq: {freq_value:.1f} MHz")

				# Update power progress bar
				power_db = channel_data['power']
				power_progress = self._current_power_progresses[ch]
				power_progress.setValue(int(power_db * 10))
				power_progress.setFormat(f"Power: {power_db:.1f} dB")

				# Color code the power progress bar based on value
				if power_db > 25:
					power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff0000; }")
				elif power_db > 15:
					power_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff9900; }")
				else:
					power_progress.setStyleSheet("QProgressBar::chunk { background-color: #00aa00; }")

				# Update control elements to match current state
				if ch in self._channel_controls:
					controls = self._channel_controls[ch]
					# Only update if not being edited by user
					if not controls['frequency_input'].hasFocus():
						controls['frequency_input'].setText(f"{freq_value:.1f}")
					if not controls['power_input'].hasFocus():
						controls['power_input'].setText(f"{power_db:.1f}")

					# Update power button state
					is_on = channel_data['power_state']
					expected_text = 'Power ON' if is_on else 'Power OFF'
					if controls['power_toggle'].isChecked() != is_on or controls['power_toggle'].text() != expected_text:
						controls['power_toggle'].blockSignals(True)
						controls['power_toggle'].setChecked(is_on)
						controls['power_toggle'].setText(expected_text)
						controls['power_toggle'].blockSignals(False)

					# Update power mode button state
					is_internal = channel_data['power_control'] == 'INT'
					expected_text = 'INTERNAL' if is_internal else 'EXTERNAL'
					if controls['power_mode_toggle'].isChecked() != is_internal or controls['power_mode_toggle'].text() != expected_text:
						controls['power_mode_toggle'].blockSignals(True)
						controls['power_mode_toggle'].setChecked(is_internal)
						controls['power_mode_toggle'].setText(expected_text)
						controls['power_mode_toggle'].blockSignals(False)

					# Update blanking button state
					is_blanking_on = channel_data['blanking_state']
					expected_text = 'Blanking ON' if is_blanking_on else 'Blanking OFF'
					if controls['blanking_toggle'].isChecked() != is_blanking_on or controls['blanking_toggle'].text() != expected_text:
						controls['blanking_toggle'].blockSignals(True)
						controls['blanking_toggle'].setChecked(is_blanking_on)
						controls['blanking_toggle'].setText(expected_text)
						controls['blanking_toggle'].blockSignals(False)

					# Update blanking mode button state
					is_blanking_internal = channel_data['blanking_control'] == 'INT'
					controls['blanking_mode_toggle'].blockSignals(True)
					controls['blanking_mode_toggle'].setChecked(is_blanking_internal)
					controls['blanking_mode_toggle'].setText('Int Blanking' if is_blanking_internal else 'Ext Blanking')
					controls['blanking_mode_toggle'].blockSignals(False)

		except Exception as e:
			print(f"Error while updating Quad AOM GUI: {e}")