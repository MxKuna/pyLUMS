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
		self.ser = serial.Serial(self._comport, 57600, timeout=0.5)

		while len(self.ser.read()) > 0:
			pass  # read all data in buffer

		reply = self._send_msg(r"q\r", reply_pattern=r"^QR(\d+)\s+\n\r\?$")
		print(f"Found a device with an ID: {reply.group(1)}")

	@remote
	def _send_msg(self, msg, reply_pattern=r".*\n\r"):
		self.ser.reset_input_buffer()
		self.ser.write(msg.encode('ascii'))
		buf = self.ser.read()
		while not re.match(reply_pattern.encode('ascii'), buf):
			if reply_pattern.endswith(r'\?$'):
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
		pattern = r"^\n\rl1\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rl2\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rl3\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rl4\s+F=(\d+\.?\d*)\s+P=(-?\d+\.?\d*)\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rb1\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rb2\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rb3\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\rb4\s+([A-Z]+)\s+([A-Z]+)" \
		          r"\n\r\?$"
		reply = self._send_msg("S", reply_pattern=pattern)
		d = {}
		for ch in range(1, 5):
			d[f"channel{ch}"] = {"frequency":        float(reply.group(1 + 4 * (ch - 1))),
			                     "power":            float(reply.group(2 + 4 * (ch - 1))),
			                     "power_state":      reply.group(3 + 4 * (ch - 1)) == 'ON',
			                     "power_control":    reply.group(4 + 4 * (ch - 1)),
			                     "blanking_state":   reply.group(17 + 2 * (ch - 1)) == 'ON',
			                     "blanking_control": reply.group(18 + 2 * (ch - 1)),
			                     "phase":            0  # Placeholder, as phase isn't in the status pattern
			                     }
		return d

	@remote
	def configure_channel(self, channel: int, frequency_mhz=None, power_raw=None, power_db=None, phase=None, switch=None, internal_mode=None):
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
			cmd += f"H{int(phase)}"
		if power_raw is not None:
			if power_raw < 0 or power_raw > 1023:
				raise ValueError(f"Wrong power: {power_raw}. Expected value between 0 and 1023")
			cmd += f"P{int(power_raw)}"
		if power_db is not None:
			if power_db < -5.2 or power_db > 33:
				raise ValueError(f"Wrong power: {power_db}. Expected value between -5.2 and 33 dB")
			cmd += f"D{power_db:.2f}"
		if switch is not None:
			cmd += "O1" if switch else "O0"
		if internal_mode is not None:
			cmd += "I1" if internal_mode else "I0"
		cmd += '\r'
		print(cmd)
		self._send_msg(cmd)


@include_remote_methods(QuadAOMWorker)
class QuadAOM(DeviceOverZeroMQ):
	# Constants for the device
	FREQ_MIN = 85.0
	FREQ_MAX = 135.0
	PHASE_MIN = 0
	PHASE_MAX = 16383
	POWER_DB_MIN = -5.2
	POWER_DB_MAX = 33.0
	POWER_RAW_MIN = 0
	POWER_RAW_MAX = 1023

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._channel_groups = {}
		# Input controls (dials and text boxes)
		self._frequency_dials = {}
		self._phase_dials = {}
		self._power_dials = {}
		self._frequency_inputs = {}
		self._phase_inputs = {}
		self._power_inputs = {}
		# Display only controls (read-only sliders)
		self._frequency_indicators = {}
		self._phase_indicators = {}
		self._power_indicators = {}
		# Buttons
		self._switch_buttons = {}
		self._internal_mode_buttons = {}

	def _create_control_group(self, parent, name, min_val, max_val, default_val, suffix="",
	                          warning_threshold=None, precision=1):
		"""Helper method to create a group with dial, text input, and read-only indicator"""
		container = QtWidgets.QGroupBox(name)
		layout = QtWidgets.QVBoxLayout(container)
		layout.setContentsMargins(5, 5, 5, 5)

		# Create horizontal layout for dial and text input
		input_layout = QtWidgets.QHBoxLayout()

		# Dial for adjustment
		dial = QtWidgets.QDial()
		dial.setMinimum(int(min_val * (10 ** precision)))
		dial.setMaximum(int(max_val * (10 ** precision)))
		dial.setValue(int(default_val * (10 ** precision)))
		dial.setNotchesVisible(True)
		dial.setWrapping(False)
		dial.setFixedSize(70, 70)
		input_layout.addWidget(dial)

		# Text input for precise values
		input_layout.addStretch(1)
		text_input = QtWidgets.QLineEdit(f"{default_val:.{precision}f}")
		text_input.setValidator(QtGui.QDoubleValidator(min_val, max_val, precision))
		text_input.setFixedWidth(60)
		text_input.setAlignment(QtCore.Qt.AlignRight)
		input_layout.addWidget(text_input)
		input_layout.addWidget(QtWidgets.QLabel(suffix))

		layout.addLayout(input_layout)

		# Read-only indicator/slider below
		slider_layout = QtWidgets.QHBoxLayout()
		min_label = QtWidgets.QLabel(f"{min_val}")
		min_label.setFixedWidth(30)
		min_label.setAlignment(QtCore.Qt.AlignRight)
		slider_layout.addWidget(min_label)

		indicator = QtWidgets.QProgressBar()
		indicator.setOrientation(QtCore.Qt.Horizontal)
		indicator.setMinimum(int(min_val * (10 ** precision)))
		indicator.setMaximum(int(max_val * (10 ** precision)))
		indicator.setValue(int(default_val * (10 ** precision)))
		indicator.setTextVisible(False)
		indicator.setFixedHeight(10)
		slider_layout.addWidget(indicator)

		max_label = QtWidgets.QLabel(f"{max_val}")
		max_label.setFixedWidth(30)
		max_label.setAlignment(QtCore.Qt.AlignLeft)
		slider_layout.addWidget(max_label)
		layout.addLayout(slider_layout)

		# Set up connections between dial and text input
		def update_text_from_dial(value):
			real_value = value / (10 ** precision)
			text_input.setText(f"{real_value:.{precision}f}")

		def update_dial_from_text():
			try:
				value = float(text_input.text())
				dial.setValue(int(value * (10 ** precision)))
			except ValueError:
				pass

		dial.valueChanged.connect(update_text_from_dial)
		text_input.editingFinished.connect(update_dial_from_text)

		return container, dial, text_input, indicator

	def createDock(self, parentWidget, menu=None):
		""" Function for integration in GUI app with enhanced controls """
		main_widget = QtWidgets.QWidget(parentWidget)
		dock = QtWidgets.QDockWidget("4x AOM Control Panel", parentWidget)
		main_layout = QtWidgets.QVBoxLayout()
		main_widget.setLayout(main_layout)

		# Create horizontal layout for the channel groups
		channel_layout = QtWidgets.QHBoxLayout()
		main_layout.addLayout(channel_layout)

		# Create a group box for each channel
		for ch in range(1, 5):
			group_box = QtWidgets.QGroupBox(f"Channel {ch}")
			self._channel_groups[ch] = group_box
			group_layout = QtWidgets.QVBoxLayout(group_box)
			group_layout.setSpacing(10)

			# Frequency control
			freq_group, freq_dial, freq_input, freq_indicator = self._create_control_group(
					group_box, "Frequency", self.FREQ_MIN, self.FREQ_MAX,
					self.FREQ_MIN, " MHz", precision=1
			)
			self._frequency_dials[ch] = freq_dial
			self._frequency_inputs[ch] = freq_input
			self._frequency_indicators[ch] = freq_indicator
			group_layout.addWidget(freq_group)

			# Phase control
			phase_group, phase_dial, phase_input, phase_indicator = self._create_control_group(
					group_box, "Phase", self.PHASE_MIN, self.PHASE_MAX,
					self.PHASE_MIN, "", precision=0
			)
			self._phase_dials[ch] = phase_dial
			self._phase_inputs[ch] = phase_input
			self._phase_indicators[ch] = phase_indicator
			group_layout.addWidget(phase_group)

			# Power control (in dB)
			power_group, power_dial, power_input, power_indicator = self._create_control_group(
					group_box, "Power", self.POWER_DB_MIN, self.POWER_DB_MAX,
					0.0, " dB", warning_threshold=25.0, precision=1
			)
			self._power_dials[ch] = power_dial
			self._power_inputs[ch] = power_input
			self._power_indicators[ch] = power_indicator
			group_layout.addWidget(power_group)

			# Control buttons
			button_layout = QtWidgets.QHBoxLayout()

			# Switch button
			switch_button = QtWidgets.QPushButton("Output OFF")
			switch_button.setCheckable(True)
			switch_button.setStyleSheet("QPushButton:checked { background-color: green; color: white; }")
			self._switch_buttons[ch] = switch_button
			button_layout.addWidget(switch_button)

			# Internal mode button
			internal_button = QtWidgets.QPushButton("Internal Mode OFF")
			internal_button.setCheckable(True)
			internal_button.setStyleSheet("QPushButton:checked { background-color: blue; color: white; }")
			self._internal_mode_buttons[ch] = internal_button
			button_layout.addWidget(internal_button)

			group_layout.addLayout(button_layout)

			# Add the group to the channel layout
			channel_layout.addWidget(group_box)

		# Apply button for all settings - now at the bottom
		apply_button = QtWidgets.QPushButton("APPLY SETTINGS")
		apply_button.clicked.connect(self._apply_all_settings)
		apply_button.setStyleSheet("font-weight: bold; padding: 8px; font-size: 14px; background-color: #4CAF50; color: white;")
		apply_button.setMinimumHeight(40)

		# Add apply button to the main layout (bottom)
		main_layout.addWidget(apply_button)

		# Set up the dock widget
		dock.setWidget(main_widget)
		dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
		parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
		if menu:
			menu.addAction(dock.toggleViewAction())

		# Create listener thread for updates
		self.createListenerThread(self.updateSlot)

		# Configure switch buttons
		for ch in range(1, 5):
			self._switch_buttons[ch].toggled.connect(
					lambda checked, ch=ch: self._toggle_switch(ch, checked)
			)
			self._internal_mode_buttons[ch].toggled.connect(
					lambda checked, ch=ch: self._toggle_internal_mode(ch, checked)
			)

	def _toggle_switch(self, ch, checked):
		"""Handle switch button toggle"""
		self._switch_buttons[ch].setText(f"Output {'ON' if checked else 'OFF'}")

	def _toggle_internal_mode(self, ch, checked):
		"""Handle internal mode button toggle"""
		self._internal_mode_buttons[ch].setText(f"Internal Mode {'ON' if checked else 'OFF'}")

	def _apply_all_settings(self):
		"""Apply all settings to the device"""
		for ch in range(1, 5):
			try:
				# Get values from UI controls
				frequency = float(self._frequency_inputs[ch].text())
				phase = int(self._phase_inputs[ch].text())
				power_db = float(self._power_inputs[ch].text())
				switch_state = self._switch_buttons[ch].isChecked()
				internal_mode = self._internal_mode_buttons[ch].isChecked()

				# High power confirmation for safety
				if power_db > 25 and switch_state:
					confirm = QtWidgets.QMessageBox.warning(
							None,
							"High Power Warning",
							f"Channel {ch} is set to a high power level ({power_db:.1f} dB).\n"
							"Are you sure you want to apply this setting?",
							QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
							QtWidgets.QMessageBox.No
					)
					if confirm == QtWidgets.QMessageBox.No:
						continue

				# Apply settings to the device
				self.configure_channel(
						channel=ch,
						frequency_mhz=frequency,
						power_db=power_db,
						phase=phase,
						switch=switch_state,
						internal_mode=internal_mode
				)
				print(f"Applied settings for Channel {ch}")

			except Exception as e:
				QtWidgets.QMessageBox.critical(
						None,
						"Error",
						f"Failed to apply settings for Channel {ch}: {str(e)}"
				)

	def updateSlot(self, status):
		""" This function receives periodic updates from the worker """
		try:
			for ch in range(1, 5):
				channel_data = status[f'channel{ch}']

				# Update read-only indicators (not the input controls)
				freq_value = channel_data['frequency']
				self._frequency_indicators[ch].setValue(int(freq_value * 10))

				# Update power indicator
				power_db = channel_data['power']
				self._power_indicators[ch].setValue(int(power_db * 10))

				# Color code the power indicator based on value
				if power_db > 25:
					self._power_indicators[ch].setStyleSheet("QProgressBar { background-color: #f0f0f0; border: 1px solid gray; } "
					                                         "QProgressBar::chunk { background-color: #ff0000; }")
				elif power_db > 15:
					self._power_indicators[ch].setStyleSheet("QProgressBar { background-color: #f0f0f0; border: 1px solid gray; } "
					                                         "QProgressBar::chunk { background-color: #ff9900; }")
				else:
					self._power_indicators[ch].setStyleSheet("QProgressBar { background-color: #f0f0f0; border: 1px solid gray; } "
					                                         "QProgressBar::chunk { background-color: #00aa00; }")

				# Update button states (these reflect the actual state)
				is_on = channel_data['power_state']
				if self._switch_buttons[ch].isChecked() != is_on:
					self._switch_buttons[ch].setChecked(is_on)
					self._switch_buttons[ch].setText(f"Output {'ON' if is_on else 'OFF'}")

		except Exception as e:
			print(f"Error while updating Quad AOM GUI: {e}")