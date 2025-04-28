# -*- coding: utf-8 -*-
import numpy as np
import scipy.optimize
from devices import H_C, N_AIR
from devices.zeromq_device import (
	DeviceOverZeroMQ,
	DeviceWorker,
	include_remote_methods,
	remote,
)
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QApplication, QDialog, QDockWidget, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLCDNumber, QLabel, QLineEdit, QMainWindow, QMenuBar, QMessageBox, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

class ChameleonWorker(DeviceWorker):
	def __init__(self, port, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.port = port

	def init_device(self):
		from pyvisa import ResourceManager
		rm = ResourceManager()
		self.handle = rm.open_resource(self.port)
		self.handle.baud_rate = 19200
		self.handle.write_termination = '\r\n'
		self.handle.read_termination = '\r\n'

		print("Checking communication: ")
		self.query("?L")  # would raise an exception if communication failed
		print("OK")

	def __del__(self):
		self.ser.close()  # serial port close

	def status(self):
		d = super().status()
		d["laser"] = \
			{
				"keyswitch": self.keyswitch(),
				"busy":      self.busy(),
				"tuning":    self.tuning(),
				"lasing":    self.is_lasing()
			}
		d["tunable"] = \
			{
				"wavelength": self.wavelength(),
				"power":      self.power_tunable(),
				"shutter":    self.is_shutter_open_tunable(),
				"align":      self.align_tunable()
			}
		d["fixed"] = \
			{
				"power":   self.power_fixed(),
				"shutter": self.is_shutter_open_fixed(),
				"align":   self.align_fixed()
			}
		return d

	@remote
	def query(self, command):
		res = self.handle.query(command)
		if not res.startswith(command):
			raise Exception("No connection to laser or ECHO is OFF")
		res = res[len(command):].strip()
		return res

	@remote
	def wavelength(self):
		return int(self.query('?VW'))

	@remote
	def set_wavelength(self, nm):
		self.query(f"WV={int(nm)}")

	@remote
	def open_shutter_tunable(self, ok=True):
		if ok:
			self.query("SVAR=1")
		else:
			self.close_shutter_tunable()

	@remote
	def close_shutter_tunable(self):
		self.query("SVAR=0")

	@remote
	def is_shutter_open_tunable(self):
		return int(self.query("?SVAR")) == 1

	@remote
	def open_shutter_fixed(self, ok=True):
		if ok:
			self.query("SFIXED=1")
		else:
			self.close_shutter_fixed()

	@remote
	def close_shutter_fixed(self):
		self.query("SFIXED=0")

	@remote
	def is_shutter_open_fixed(self):
		return int(self.query("?SFIXED")) == 1

	@remote
	def is_lasing(self):
		return int(self.query("?L")) == 1

	@remote
	def set_laser_state(self, state):
		if state:
			self.query("L=1")
		else:
			self.query("L=0")

	@remote
	def power_tunable(self):
		return int(self.query("?PVAR"))

	@remote
	def power_fixed(self):
		return int(self.query("?PFIXED"))

	@remote
	def busy(self):
		return str(self.query("?ST"))

	@remote
	def keyswitch(self) -> int:
		'''Returns the current keyswitch position: 1-ON and 0-OFF'''
		return int(self.query("?K"))

	@remote
	def tuning(self) -> int:
		'''Returns the tuning staus: 1-Tuning and 0-Completed tune'''
		return int(self.query("?TS"))

	@remote
	def align_tunable(self) -> int:
		'''Returns the alignment mode status: 1-Enabled and 0-Disabled'''
		return int(self.query("?ALIGNVAR"))

	@remote
	def align_fixed(self) -> int:
		'''Returns the alignment mode status: 1-Enabled and 0-Disabled'''
		return int(self.query("?ALIGNFIXED"))

	@remote
	def set_align_tunable(self, state: int):
		'''Sets the alignment mode status: 1-Enabled and 0-Disabled'''
		self.query(f"ALIGNVAR={state}")

	@remote
	def set_align_fixed(self, state: int):
		'''Sets the alignment mode status: 1-Enabled and 0-Disabled'''
		self.query(f"ALIGNFIXED={state}")


@include_remote_methods(ChameleonWorker)
class Chameleon(DeviceOverZeroMQ):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Default values for GUI display
		self._fixed_shutter_open = 0
		self._tunable_shutter_open = 0

	def createDock(self, parentWidget, menu=None):
		# Create the dock widget
		dock = QDockWidget("Chameleon Laser Control", parentWidget)

		# Create a main widget to hold the content
		main_widget = QWidget(parentWidget)

		# Create the main horizontal layout with 2:1 ratio
		main_layout = QHBoxLayout()

		# Create two columns
		left_column = QWidget()
		right_column = QWidget()

		left_column_layout = QVBoxLayout()
		right_column_layout = QVBoxLayout()

		# Set stretch factor for the columns (2:1 ratio)
		main_layout.addWidget(left_column, 2)
		main_layout.addWidget(right_column, 1)

		# ===== LEFT COLUMN: Beam Control and Wavelength Control =====

		# Create the indicators row at the top
		indicators_layout = QHBoxLayout()

		# Create the lasing indicator (half width)
		self.red_rectangle = QLabel("LASING!")
		self.red_rectangle.setAlignment(Qt.AlignCenter)
		self.red_rectangle.setStyleSheet("""
            background-color: red;
            color: white;
            font-weight: bold;
            font-size: 20px;
            border: 3px solid darkred;
            padding: 4px;
            border-radius: 10px;
        """)
		self.red_rectangle.setMinimumHeight(35)
		self.red_rectangle.setMaximumHeight(35)

		# Create the wavelength indicator
		self.wavelength_indicator = QLabel("")
		self.wavelength_indicator.setAlignment(Qt.AlignCenter)
		self.wavelength_indicator.setStyleSheet("""
		    background-color: white;
		    color: black;
		    font-weight: bold;
		    font-size: 20px;
		    border: 3px solid red;
		    padding: 4px;
		    border-radius: 10px;
		""")
		self.wavelength_indicator.setMinimumHeight(35)
		self.wavelength_indicator.setMaximumHeight(35)

		# Add both indicators to the layout
		indicators_layout.addWidget(self.red_rectangle)
		indicators_layout.addWidget(self.wavelength_indicator)

		# 1. Create the Fixed and Tunable beam controls
		# Fixed shutter control
		fixed_group = QGroupBox("FIXED (1030 nm)")
		fixed_layout = QVBoxLayout()

		self.left_lcd = QLCDNumber()
		self.left_lcd.setDigitCount(5)
		self.left_lcd.setStyleSheet("color: blue; background-color: black;")
		self.left_lcd.setMinimumHeight(40)
		self.left_lcd.display("ERR")

		self.left_button = QPushButton("OPEN")
		self.left_button.setMinimumHeight(32)
		self.left_button.clicked.connect(lambda: self.open_shutter_fixed(not self._fixed_shutter_open))

		fixed_layout.addWidget(self.left_lcd)
		fixed_layout.addWidget(self.left_button)
		fixed_group.setLayout(fixed_layout)

		# Tunable shutter control
		tunable_group = QGroupBox("TUNABLE")
		tunable_layout = QVBoxLayout()

		self.right_lcd = QLCDNumber()
		self.right_lcd.setDigitCount(5)
		self.right_lcd.setStyleSheet("color: green; background-color: black;")
		self.right_lcd.setMinimumHeight(40)
		self.right_lcd.display("ERR")

		self.right_button = QPushButton("OPEN")
		self.right_button.clicked.connect(lambda: self.open_shutter_tunable(not self._tunable_shutter_open))
		self.right_button.setMinimumHeight(32)

		tunable_layout.addWidget(self.right_lcd)
		tunable_layout.addWidget(self.right_button)
		tunable_group.setLayout(tunable_layout)

		# Create a horizontal layout for the two beam controls
		beam_controls_layout = QHBoxLayout()
		beam_controls_layout.addWidget(fixed_group)
		beam_controls_layout.addWidget(tunable_group)

		# 2. Create the Wavelength Control section
		wavelength_group = QGroupBox("Wavelength Control")
		wavelength_layout = QVBoxLayout()

		# Wavelength input row
		input_row = QHBoxLayout()
		wavelength_label = QLabel("Wavelength (nm):")
		wavelength_label.setStyleSheet("font-weight: bold; font-size: 14px;")
		self.wavelength_input = QLineEdit()
		self.wavelength_input.setPlaceholderText("Enter wavelength (680-1030)")
		self.wavelength_input.setMinimumHeight(30)
		self.wavelength_set_button = QPushButton("SET")
		self.wavelength_set_button.setMinimumHeight(30)
		self.wavelength_set_button.clicked.connect(lambda: self.set_wavelength_with_safety())

		input_row.addWidget(wavelength_label)
		input_row.addWidget(self.wavelength_input)
		input_row.addWidget(self.wavelength_set_button)

		# Wavelength slider
		slider_row = QHBoxLayout()
		min_label = QLabel("680 nm")
		max_label = QLabel("1030 nm")
		self.wavelength_slider = QSlider(Qt.Horizontal)
		self.wavelength_slider.setMinimum(680)
		self.wavelength_slider.setMaximum(1030)
		self.wavelength_slider.setEnabled(False)  # Read-only

		slider_row.addWidget(min_label)
		slider_row.addWidget(self.wavelength_slider)
		slider_row.addWidget(max_label)

		# Preset buttons
		preset_row = QHBoxLayout()
		preset_buttons = [
			("680 nm", 680),
			("700 nm", 700),
			("750 nm", 750),
			("800 nm", 800),
			("900 nm", 900)
		]

		for label, value in preset_buttons:
			preset_btn = QPushButton(label)
			preset_btn.setMinimumHeight(30)
			preset_btn.clicked.connect(lambda _, v=value: self.set_wavelength_with_safety(v))
			preset_row.addWidget(preset_btn)

		# Add components to wavelength layout
		wavelength_layout.addLayout(input_row)
		wavelength_layout.addLayout(slider_row)
		wavelength_layout.addLayout(preset_row)
		wavelength_group.setLayout(wavelength_layout)

		# Add components to left column layout
		left_column_layout.addLayout(indicators_layout)
		left_column_layout.addLayout(beam_controls_layout)
		left_column_layout.addWidget(wavelength_group, 1)
		left_column.setLayout(left_column_layout)

		# ===== RIGHT COLUMN: State Information =====
		right_column_layout.setSpacing(15)  # Add spacing between elements

		# 1. Laser State Information
		state_info_group = QGroupBox("Laser State Information")
		state_info_layout = QVBoxLayout()

		# Create button indicators instead of text fields
		self.keyText = QPushButton("Err")
		self.busyText = QPushButton("Err")
		self.tuningText = QPushButton("Err")
		self.lasingText = QPushButton("Err")

		# Create status indicators with consistent styling
		status_indicators = [
			("KEYSWITCH", self.keyText),
			("BUSY", self.busyText),
			("TUNING", self.tuningText),
			("LASING", self.lasingText)
		]

		status_style = """
		    background-color: #f0f0f0;
		    color: black;
		    border: 1px solid #a0a0a0;
		    padding: 6px;
		    font-weight: bold;
		    text-align: center;
		    min-height: 24px;
		"""

		# Create grid for status indicators
		status_grid = QGridLayout()
		status_grid.setVerticalSpacing(10)  # Add some spacing between rows

		for i, (label, text_field) in enumerate(status_indicators):
			# Create label
			indicator_label = QLabel(label)
			indicator_label.setAlignment(Qt.AlignCenter)
			indicator_label.setStyleSheet("font-weight: bold;")

			# Configure button for display only
			text_field.setEnabled(False)  # Make it non-clickable
			text_field.setFocusPolicy(Qt.NoFocus)  # Prevent focus
			text_field.setCursor(Qt.ArrowCursor)  # Normal cursor instead of hand
			text_field.setStyleSheet(status_style)

			# Set size policy to make the button expand vertically
			size_policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
			text_field.setSizePolicy(size_policy)

			# Add to grid
			status_grid.addWidget(indicator_label, i, 0)
			status_grid.addWidget(text_field, i, 1)

		# Set row stretch factors to make all rows equal
		for i in range(status_grid.rowCount()):
			status_grid.setRowStretch(i, 1)

		# Add status grid to layout with stretch
		state_info_layout.addLayout(status_grid)

		state_info_group.setLayout(state_info_layout)

		# 2. Alignment Mode control (moved from left column)
		align_group = QGroupBox("Alignment Mode")
		align_layout = QVBoxLayout()

		checkboxes_layout = QHBoxLayout()
		self.checkbox_fixed = QtWidgets.QCheckBox("FIXED")
		self.checkbox_fixed.stateChanged.connect(lambda state: self.set_align_fixed(1 if state == QtCore.Qt.Checked else 0))
		self.checkbox_tunable = QtWidgets.QCheckBox("TUNABLE")
		self.checkbox_tunable.stateChanged.connect(lambda state: self.set_align_tunable(1 if state == QtCore.Qt.Checked else 0))

		checkboxes_layout.addWidget(self.checkbox_fixed)
		checkboxes_layout.addWidget(self.checkbox_tunable)

		align_layout.addLayout(checkboxes_layout)
		align_group.setLayout(align_layout)

		# Add components to right column layout with equal stretch
		right_column_layout.addWidget(state_info_group, 3)
		right_column_layout.addWidget(align_group, 1)
		right_column.setLayout(right_column_layout)

		# Set main layout
		main_widget.setLayout(main_layout)
		dock.setWidget(main_widget)

		# Set allowed dock areas
		dock.setAllowedAreas(Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)

		# Add the dock to the parent widget
		parentWidget.addDockWidget(Qt.TopDockWidgetArea, dock)

		if menu:
			menu.addAction(dock.toggleViewAction())

		print("\t --INITIALIZING--")
		self.initial_check()
		# print(self.status())
		self.createListenerThread(self.updateSlot)
		print("\t --DONE--")

	def set_wavelength_with_safety(self, wavelength=None):
		"""
		Set wavelength with safety checks

		Args:
			wavelength (int, optional): Wavelength to set. If None, reads from input box.
		"""
		try:
			if wavelength is None:
				wavelength = int(self.wavelength_input.text())

			# Safety checks
			if wavelength < 680 or wavelength > 1030:
				QMessageBox.warning(
						None,
						"Wavelength Error",
						"Wavelength must be between 680 and 1030 nm."
				)
				return

			self.set_wavelength(wavelength)

		except ValueError:
			QMessageBox.warning(
					None,
					"Input Error",
					"Please enter a valid integer wavelength."
			)

	def updateSlot(self, status):
		"""Update UI elements based on device status updates"""
		try:
			wl = status["tunable"]["wavelength"]
			self.wavelength_slider.setValue(wl)
			self.wavelength_indicator.setText(f"{wl} nm")

			self.update_fixed_shutter_ui(status["fixed"]["shutter"])
			self.update_tunable_shutter_ui(status["tunable"]["shutter"])
			self.update_align(status["laser"]["busy"], status["tunable"]["align"], status["fixed"]["align"])
			self.update_state_info(status["laser"])

			if status["laser"]["lasing"]:
				self.red_rectangle.setStyleSheet("background-color: red; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkred; padding: 4px; border-radius: 10px;")
			else:
				self.red_rectangle.setStyleSheet("background-color: gray; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkgray; padding: 4px; border-radius: 10px;")

			self.left_lcd.display(status["fixed"]["power"])
			self.right_lcd.display(status["tunable"]["power"])

		except Exception as e:
			print(f"Error in updateSlot: {str(e)}")

	def update_fixed_shutter_ui(self, s):
		"""Update fixed shutter button appearance"""
		if s:
			self._fixed_shutter_open = 1
			self.left_button.setText("OPEN")
			self.left_button.setStyleSheet(
					"color: white; font-weight: bold; font-size: 14px; background-color: green;"
			)
		else:
			self._fixed_shutter_open = 0
			self.left_button.setText("CLOSED")
			self.left_button.setStyleSheet(
					"color: white; font-weight: bold; font-size: 14px; background-color: gray;"
			)

	def update_tunable_shutter_ui(self, s):
		"""Update tunable shutter button appearance"""
		if s:
			self._tunable_shutter_open = 1
			self.right_button.setText("OPEN")
			self.right_button.setStyleSheet(
					"color: white; font-weight: bold; font-size: 14px; background-color: green;"
			)
		else:
			self._tunable_shutter_open = 0
			self.right_button.setText("CLOSED")
			self.right_button.setStyleSheet(
					"color: white; font-weight: bold; font-size: 14px; background-color: gray;"
			)

	def update_state_info(self, s):
		"""Update the state info buttons"""
		dict = {
			"keyswitch": {1: "ON", 0: "OFF"},
			"tuning":    {1: "Tuning", 0: "Tuned"},
			"lasing":    {1: "Lasing!", 0: "Not Lasing"}
		}

		# Define colors for different states
		color_dict = {
			"keyswitch": {1: "#90EE90", 0: "#FFB6C1"},  # Light green for ON, light pink for OFF
			"tuning":    {1: "#FFD700", 0: "#90EE90"},  # Gold for Tuning, light green for Tuned
			"lasing":    {1: "#90EE90", 0: "#D3D3D3"}   # Tomato for Lasing, light gray for Not Lasing
		}

		# Update keyswitch text and color
		self.keyText.setText(dict["keyswitch"][s["keyswitch"]])
		self.keyText.setStyleSheet(f"QPushButton {{ background-color: {color_dict['keyswitch'][s['keyswitch']]}; color: black; font-weight: bold; text-align: center; }}")

		# Update busy text
		self.busyText.setText(s["busy"])
		# For busy text, we could set a default color or change based on specific busy messages
		if s["busy"] in ("OK", "Fixed Alignment Mode", "Variable Alignment Mode"):
			self.busyText.setStyleSheet("QPushButton { background-color: #90EE90; color: black; font-weight: bold; text-align: center; }")  # Light green for OK
		else:
			self.busyText.setStyleSheet("QPushButton { background-color: #FFD700; color: black; font-weight: bold; text-align: center; }")  # Gold for other states

		# Update tuning text and color
		self.tuningText.setText(dict["tuning"][s["tuning"]])
		self.tuningText.setStyleSheet(f"QPushButton {{ background-color: {color_dict['tuning'][s['tuning']]}; color: black; font-weight: bold; text-align: center; }}")

		# Update lasing text and color
		self.lasingText.setText(dict["lasing"][s["lasing"]])
		self.lasingText.setStyleSheet(f"QPushButton {{ background-color: {color_dict['lasing'][s['lasing']]}; color: black; font-weight: bold; text-align: center; }}")

	def update_align(self, s, ta, fa):
		"""Update the alignment mode checkboxes"""
		if s == "OK" and ta == 0 and fa == 0:
			self.checkbox_fixed.setDisabled(False)
			self.checkbox_tunable.setDisabled(False)
		elif s == "Variable Alignment Mode" and ta == 1 and fa == 0:
			self.checkbox_fixed.setDisabled(True)
			self.checkbox_tunable.setDisabled(False)
		elif s == "Fixed Alignment Mode" and ta == 0 and fa == 1:
			self.checkbox_fixed.setDisabled(False)
			self.checkbox_tunable.setDisabled(True)
		else:
			self.checkbox_fixed.setDisabled(True)
			self.checkbox_tunable.setDisabled(True)

	def initial_check(self):
		s = self.status()
		if s["laser"]["busy"] == "Fixed Alignment Mode":
			self.checkbox_fixed.setChecked(True)
		elif s["laser"]["busy"] == "Variable Alignment Mode":
			self.checkbox_tunable.setChecked(True)
