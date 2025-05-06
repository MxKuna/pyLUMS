import serial
import serial.tools.list_ports
import threading
import struct
from time import sleep
from PyQt5 import QtWidgets, QtCore

from devices.zeromq_device import DeviceWorker, DeviceOverZeroMQ, remote, include_remote_methods


class ShutterWorker(DeviceWorker):
	def __init__(self, *args, hwid="SER=066DFF494877514867133945", com=None, baud=115200, **kwargs):
		super().__init__(*args, **kwargs)
		self.baud = baud
		self.com = com
		self.hwid = hwid
		self._connected = False
		self._command_lock = threading.Lock()

		# Binary protocol command codes
		self.CMD_SET_POSITION = 0x01
		self.CMD_QUERY_POSITION = 0x02
		self.CMD_HANDSHAKE = 0x03

		# Position value codes
		self.POS_LOW = 0x01  # close
		self.POS_MID = 0x02  # open
		self.POS_HIGH = 0x03  # w_open

		# Response codes
		self.RESP_SUCCESS = 0x00
		self.RESP_ERROR = 0xFF
		self.RESP_INIT_COMPLETE = 0xAA
		self.RESP_HANDSHAKE = 0xBB

	def init_device(self):
		ports = list(serial.tools.list_ports.comports())
		for port in ports:
			if port.vid and port.hwid:
				if port.hwid.__contains__(self.hwid):
					self.com = port.device
					try:
						self.comp = serial.Serial(self.com, self.baud, timeout=1)  # Increased timeout
						print(f"Connecting to device on: {self.comp.name}")

						# Clear any pending data
						self.comp.reset_input_buffer()
						self.comp.reset_output_buffer()

						# Wait for device to initialize (Arduino needs time after reset)
						sleep(2.0)

						# Try to read initialization signal
						self.comp.reset_input_buffer()
						init_signal = self.comp.read(1)

						if init_signal and init_signal[0] == self.RESP_INIT_COMPLETE:
							print("Received initialization signal")
							self._connected = True
						else:
							print(f"No initialization signal received: {init_signal.hex() if init_signal else 'None'}")

							# Try handshake as fallback
							print("Attempting handshake...")
							self.comp.reset_input_buffer()
							self.comp.write(bytes([self.CMD_HANDSHAKE]))
							self.comp.flush()

							handshake_response = self.comp.read(1)
							if handshake_response and handshake_response[0] == self.RESP_HANDSHAKE:
								print("Handshake successful, device connected")
								self._connected = True
							else:
								print(f"Handshake failed: {handshake_response.hex() if handshake_response else 'None'}")

					except Exception as e:
						print(f"Error initializing device: {e}")
						self._connected = False

	def status(self):
		d = super().status()
		for axis in [1, 2, 3, 4]:
			d[f"open{axis}"] = self.state(axis)
		return d

	@remote
	def state(self, ax):
		if not self._connected:
			print("Device not connected")
			return False

		with self._command_lock:
			try:
				# Convert 1-based axis to 0-based for protocol
				servo_index = ax - 1

				# Clear input buffer
				self.comp.reset_input_buffer()

				# Send query command
				# Format: [CMD_QUERY_POSITION, servo_index]
				command = bytes([self.CMD_QUERY_POSITION, servo_index])
				# print(f"Sending query: {command.hex()}")
				self.comp.write(command)
				self.comp.flush()

				# Read response status byte
				status_byte = self.comp.read(1)
				if not status_byte:
					print(f"No response to query for axis {ax}")
					return False

				if status_byte[0] == self.RESP_SUCCESS:
					# Now read the rest of the response (5 more bytes)
					remaining_bytes = self.comp.read(5)
					if len(remaining_bytes) != 5:
						print(f"Incomplete response for axis {ax}: {remaining_bytes.hex()}")
						return False

					# Combine all response bytes
					response = status_byte + remaining_bytes
					# print(f"Got response: {response.hex()}")

					# Check if the returned servo index matches the requested one
					if response[1] != servo_index:
						print(f"Error: Requested axis {ax}, received axis {response[1] + 1}")
						return False

					# Extract position value from bytes 2-5 (4 bytes, big-endian uint32)
					position = struct.unpack('>I', response[2:6])[0]
					# print(f"Servo {ax} position: {position}")

					# Return True if position > 1100 (same logic as original)
					return position > 1100
				else:
					print(f"Error status in response: {status_byte.hex()}")
					return False
			except Exception as e:
				print(f"Exception in state query: {e}")
				return False

	@remote
	def move(self, action, *axes):
		if not self._connected:
			print("Device not connected")
			return

		try:
			with self._command_lock:
				for ax in axes:
					# Convert 1-based axis to 0-based for protocol
					servo_index = ax - 1

					# Map action to position code
					position_code = None
					match action:
						case 'close':
							position_code = self.POS_LOW
						case 'open':
							position_code = self.POS_MID
						case 'w_open':
							position_code = self.POS_HIGH
						case _:
							print("Invalid action: Use 'open', 'close', or 'w_open'")
							break

					if position_code is not None:
						# Send set position command
						# Format: [CMD_SET_POSITION, servo_index, position_code]
						self.comp.reset_input_buffer()
						command = bytes([self.CMD_SET_POSITION, servo_index, position_code])
						print(f"Sending move command: {command.hex()}")
						self.comp.write(command)
						self.comp.flush()

						# Read response
						response = self.comp.read(1)
						if not response:
							print(f"No response to move command for axis {ax}")
						elif response[0] != self.RESP_SUCCESS:
							print(f"Error moving servo {ax}: {response.hex()}")
						else:
							print(f"Successfully moved servo {ax}")
		except Exception as e:
			print(f"Error on moving shutter: {e}")

	@remote
	def get_connected(self):
		return self._connected


@include_remote_methods(ShutterWorker)
class Shutter(DeviceOverZeroMQ):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def _generate_func(self, number):
		def change_state(on):
			if on:
				self.move('w_open', number)
			else:
				self.move('close', number)

		return change_state

	def update_ui(self, status):
		if self.get_connected():
			for axis in [1, 2, 3, 4]:
				try:
					state_key = f"open{axis}"
					if state_key in status:
						if status[state_key]:
							self.buttons[axis].setText("OPEN")
						else:
							self.buttons[axis].setText("CLOSED")
				except Exception as e:
					print(f"Error updating status for axis {axis}: {e}")
					self.buttons[axis].setText("ERROR")
		else:
			for axis in {1, 2, 3, 4}:
				self.buttons[axis].setText("Disconnected")
				self.checkboxes[axis].setChecked(False)

	def createDock(self, parentWidget, menu=None):
		dock = QtWidgets.QDockWidget("ServoShutter", parentWidget)
		widget = QtWidgets.QWidget(parentWidget)

		# Use QVBoxLayout with stretch factor for vertical expansion
		layout = QtWidgets.QVBoxLayout()
		widget.setLayout(layout)

		self.buttons = {}
		self.checkboxes = {}

		for axis in [1, 2, 3, 4]:
			# Create a horizontal layout for each row
			row_layout = QtWidgets.QHBoxLayout()

			# Create label with servo number
			label = QtWidgets.QLabel(f"{axis}")
			label.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
			row_layout.addWidget(label)

			# Create button with horizontal stretch
			button = QtWidgets.QPushButton("Unknown")
			button.setCheckable(True)
			button.clicked.connect(self._generate_func(axis))

			# Set size policy to make button expand horizontally and vertically
			button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

			# Set minimum height for better appearance
			button.setMinimumHeight(30)

			self.buttons[axis] = button
			row_layout.addWidget(button, 1)  # The 1 gives it a stretch factor

			# Create checkbox for enabling/disabling the button
			checkbox = QtWidgets.QCheckBox("")
			checkbox.setChecked(True)  # Default to enabled
			checkbox.stateChanged.connect(lambda state, btn=button: btn.setEnabled(state == QtCore.Qt.Checked))
			checkbox.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
			self.checkboxes[axis] = checkbox
			row_layout.addWidget(checkbox)

			# Add the row to the main layout with stretch factor
			layout.addLayout(row_layout, 1)

		# Add a stretch at the end to push all rows to the top when resizing
		layout.addStretch()

		dock.setWidget(widget)
		dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
		parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
		if menu:
			menu.addAction(dock.toggleViewAction())

		self.createListenerThread(self.update_ui)
