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
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLCDNumber,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


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
        self.query("?L") # would raise an exception if communication failed
        print("OK")


    def __del__(self):
        self.ser.close() #serial port close

    def status(self):
        d = super().status()
        d["laser"] = \
            {
                "keyswitch": self.keyswitch(),
                "busy": self.busy(),
                "tuning": self.tuning(),
                "lasing": self.is_lasing()
            }
        d["tunable"] = \
            {
                "wavelength": self.wavelength(),
                "power": self.power_tunable(),
                "shutter": self.is_shutter_open_tunable()
            }
        d["fixed"] = \
            {
                "power": self.power_fixed(),
                "shutter": self.is_shutter_open_fixed()
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
        self.keyswitch = 0
        self.busy = ""
        self.tuning = 0
        self.lasing = 0
        self.current_wavelength = 2137
        self.fixed_power = 2137
        self.tunable_power = 2137
        self.fixed_shutter_open = False
        self.tunable_shutter_open = False
        self.fixed_align = False
        self.tunable_align = False

    def createDock(self, parentWidget, menu=None):
        # Create the dock widget
        dock = QDockWidget("Chameleon Laser Control", parentWidget)

        # Create a main widget to hold the content
        main_widget = QWidget(parentWidget)

        # Create a tab widget
        tab_widget = QTabWidget()

        # First Tab - 2x2 Grid of Smaller Groups with Additional Row
        first_tab = QWidget()
        first_tab_layout = QVBoxLayout()

        # Create outer group for grid
        grid_outer_group = QGroupBox("Processes")
        grid_outer_group_layout = QVBoxLayout()

        # Create grid layout directly
        grid_layout = QGridLayout()

        # Create 2x2 grid of groups
        self.keyText = QLineEdit("placeholder")
        self.busyText = QLineEdit("placeholder")
        self.tuningText = QLineEdit("placeholder")
        self.lasingText = QLineEdit("placeholder")
        gridTexts = [self.keyText, self.busyText, self.tuningText, self.lasingText]

        group_names = {
            "KEYSWITCH": self.keyswitch,
            "BUSY": self.busy,
            "TUNING": self.tuning,
            "LASING": self.lasing
        }

        for i in range(2):
            for j in range(2):
                sub_group = QGroupBox(list(group_names.keys())[i*2 + j])
                sub_group_layout = QVBoxLayout()

                sub_group_text_box = gridTexts[i*2 + j]
                sub_group_text_box.setReadOnly(True)
                sub_group_text_box.setStyleSheet("""
                    background-color: #f0f0f0;
                    color: black;
                    border: 1px solid #a0a0a0;
                    padding: 4px;
                """)

                sub_group_layout.addWidget(sub_group_text_box)
                sub_group.setLayout(sub_group_layout)
                grid_layout.addWidget(sub_group, i, j)

        grid_outer_group_layout.addLayout(grid_layout)
        grid_outer_group.setLayout(grid_outer_group_layout)
        first_tab_layout.addWidget(grid_outer_group, 2)

        # New Group for Checkboxes
        checkbox_group = QGroupBox("Alignment Mode")
        checkbox_layout = QHBoxLayout()

        # Label for the checkbox row
        checkbox_label = QLabel("Check to enable:")

        # Two Checkboxes
        self.checkbox1 = QtWidgets.QCheckBox("FIXED")
        self.checkbox1.stateChanged.connect(lambda: self.switch_align_fixed)
        self.checkbox2 = QtWidgets.QCheckBox("TUNABLE")
        self.checkbox2.stateChanged.connect(lambda: self.switch_align_tunable)

        checkbox_layout.addWidget(checkbox_label)
        checkbox_layout.addWidget(self.checkbox1)
        checkbox_layout.addWidget(self.checkbox2)

        checkbox_group.setLayout(checkbox_layout)
        first_tab_layout.addWidget(checkbox_group, 1)

        first_tab.setLayout(first_tab_layout)

        # Second Tab - Button on Top, Group Below Divided Vertically
        second_tab = QWidget()
        second_tab_layout = QVBoxLayout()

        # Red Rectangle Label
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
        self.red_rectangle.setMinimumHeight(20)  # Ensure minimum height
        self.red_rectangle.setMaximumHeight(35)  # Ensure max height

        # Main Group for Second Tab
        second_main_group = QGroupBox("SHUTTERS")
        second_main_group_layout = QHBoxLayout()

        # left Subgroup
        left_subgroup = QGroupBox("FIXED")
        left_subgroup_layout = QVBoxLayout()

        left_label = QLabel("1030 nm")
        left_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        left_label.setAlignment(Qt.AlignCenter)
        self.left_lcd = QLCDNumber()
        self.left_lcd.setDigitCount(5)
        self.left_lcd.setStyleSheet("color: blue; background-color: black;")
        self.left_lcd.setMinimumHeight(40)
        self.left_lcd.display("ERR")

        self.left_button = QPushButton("OPEN")
        self.left_button.setMinimumHeight(32)
        self.left_button.clicked.connect(lambda: self.open_shutter_fixed(not self.fixed_shutter_open))

        left_subgroup_layout.addWidget(left_label)
        left_subgroup_layout.addWidget(self.left_lcd)
        left_subgroup_layout.addWidget(self.left_button)
        left_subgroup.setLayout(left_subgroup_layout)

        # Bottom Subgroup
        right_subgroup = QGroupBox("TUNABLE")
        right_subgroup_layout = QVBoxLayout()

        self.right_label = QLabel(f"{self.current_wavelength} nm")
        self.right_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.right_label.setAlignment(Qt.AlignCenter)
        self.right_lcd = QLCDNumber()
        self.right_lcd.setDigitCount(5)
        self.right_lcd.setStyleSheet("color: green; background-color: black;")
        self.right_lcd.setMinimumHeight(40)
        self.right_lcd.display("ERR")

        self.right_button = QPushButton("OPEN")
        self.right_button.clicked.connect(lambda: self.open_shutter_tunable(not self.tunable_shutter_open))
        self.right_button.setMinimumHeight(32)

        right_subgroup_layout.addWidget(self.right_label)
        right_subgroup_layout.addWidget(self.right_lcd)
        right_subgroup_layout.addWidget(self.right_button)
        right_subgroup.setLayout(right_subgroup_layout)

        # Add subgroups to main group
        second_main_group_layout.addWidget(left_subgroup)
        second_main_group_layout.addWidget(right_subgroup)
        second_main_group.setLayout(second_main_group_layout)

        # Add components to second tab layout
        second_tab_layout.addWidget(self.red_rectangle)
        second_tab_layout.addWidget(second_main_group)

        second_tab.setLayout(second_tab_layout)

        # Third Tab
        third_tab = QWidget()
        third_tab_layout = QVBoxLayout()

        # Wavelength Input Group
        wavelength_group = QGroupBox("Wavelength Control")
        wavelength_layout = QVBoxLayout()

        # Wavelength Input Row
        input_row = QHBoxLayout()
        wavelength_label = QLabel("Wavelength (nm):")
        wavelength_label.setStyleSheet("font-weight: bold; font-size: 16px; color: white;")
        self.wavelength_input = QLineEdit()
        self.wavelength_input.setPlaceholderText("Enter wavelength (680-1030)")
        self.wavelength_input.setMinimumHeight(40)
        self.wavelength_set_button = QPushButton("SET")
        self.wavelength_set_button.setMinimumHeight(40)
        self.wavelength_set_button.clicked.connect(lambda: self.set_wavelength_with_safety())

        input_row.addWidget(wavelength_label)
        input_row.addWidget(self.wavelength_input)
        input_row.addWidget(self.wavelength_set_button)

        # Wavelength Slider
        slider_layout = QHBoxLayout()
        min_label = QLabel("680 nm")
        max_label = QLabel("1030 nm")
        self.wavelength_slider = QSlider(Qt.Horizontal)
        self.wavelength_slider.setMinimum(680)
        self.wavelength_slider.setMaximum(1030)
        self.wavelength_slider.setEnabled(False)  # Read-only
        slider_layout.addWidget(min_label)
        slider_layout.addWidget(self.wavelength_slider)
        slider_layout.addWidget(max_label)

        # Preset Buttons Row
        preset_row = QHBoxLayout()
        preset_buttons = [
            ("680 nm", 680),
            ("700 nm", 700),
            ("750 nm", 750)
        ]

        for label, value in preset_buttons:
            preset_btn = QPushButton(label)
            preset_btn.setMinimumHeight(40)
            preset_btn.clicked.connect(lambda _, v=value: self.set_wavelength_with_safety(v))
            preset_row.addWidget(preset_btn)

        # Add widgets to layout
        wavelength_layout.addLayout(input_row, 2)
        wavelength_layout.addLayout(slider_layout, 1)
        wavelength_layout.addLayout(preset_row, 2)

        wavelength_group.setLayout(wavelength_layout)
        third_tab_layout.addWidget(wavelength_group)
        third_tab.setLayout(third_tab_layout)

        # Add tabs to the tab widget
        tab_widget.addTab(first_tab, "State Info")
        tab_widget.addTab(second_tab, "Beam Control")
        tab_widget.addTab(third_tab, "Wave")

        # Create a main layout for the dock widget
        main_layout = QVBoxLayout()
        main_layout.addWidget(tab_widget)

        # Set the layout for the main widget
        main_widget.setLayout(main_layout)

        # Set the main widget for the dock
        dock.setWidget(main_widget)

        # Set allowed dock areas
        dock.setAllowedAreas(Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)

        # Add the dock to the parent widget
        parentWidget.addDockWidget(Qt.TopDockWidgetArea, dock)

        if menu:
            menu.addAction(dock.toggleViewAction())

        print("\t --INITIALIZING--")
        self.update_ui_from_device()
        print("\t --DONE--")

        self.createListenerThread(self.updateSlot)

    def set_wavelength_with_safety(self, wavelength=None):
        """
        Set wavelength with safety checks

        Args:
            wavelength (int, optional): Wavelength to set. If None, reads from input box.
        """
        try:
            # Use input box value if no wavelength provided
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

            # Set wavelength via remote method
            self.set_wavelength(wavelength)

        except ValueError:
            QMessageBox.warning(
                None,
                "Input Error",
                "Please enter a valid integer wavelength."
        )

    def update_ui_from_device(self):
        """Initialize the UI state from device status"""
        try:
            wl = self.wavelength()
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.right_label.setText(f"{wl} nm")

            # Update shutter status
            self.fixed_shutter_open = self.is_shutter_open_fixed()
            self.tunable_shutter_open = self.is_shutter_open_tunable()
            self.update_fixed_shutter_ui()
            self.update_tunable_shutter_ui()

            self.fixed_align = self.align_fixed()
            self.tunable_align = self.align_tunable()
            self.checkbox1.setChecked(self.fixed_align)
            self.checkbox2.setChecked(self.tunable_align)
            self.update_align()

            self.keyswitch = self.keyswitch()
            self.busy = self.busy()
            self.tuning = self.tuning()
            self.lasing = self.is_lasing()

            self.update_state_info()
            if self.lasing:
                self.red_rectangle.setStyleSheet("background-color: red; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkred; padding: 4px; border-radius: 10px;")
            else:
                self.red_rectangle.setStyleSheet("background-color: gray; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkgray; padding: 4px; border-radius: 10px;")


            self.fixed_power = self.power_fixed()
            self.left_lcd.display(self.fixed_power)

            self.tunable_power = self.power_tunable()
            self.right_lcd.display(self.tunable_power)

        except Exception as e:
            print(f"Error initializing UI from device: {str(e)}")

    def updateSlot(self, status):
        """Update UI elements based on device status updates"""
        try:
            wl = status["tunable"]["wavelength"]
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.right_label.setText(f"{wl} nm")

            # Update shutter status
            self.fixed_shutter_open = status["fixed"]["shutter"]
            self.tunable_shutter_open = status["tunable"]["shutter"]
            self.update_fixed_shutter_ui()
            self.update_tunable_shutter_ui()

            self.fixed_align = self.align_fixed()
            self.tunable_align = self.align_tunable()
            self.checkbox1.setChecked(self.fixed_align)
            self.checkbox2.setChecked(self.tunable_align)
            self.update_align()

            self.keyswitch = status["laser"]["keyswitch"]
            self.busy = status["laser"]["busy"]
            self.tuning = status["laser"]["tuning"]
            self.lasing = status["laser"]["lasing"]

            self.update_state_info()
            if self.lasing:
                self.red_rectangle.setStyleSheet("background-color: red; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkred; padding: 4px; border-radius: 10px;")
            else:
                self.red_rectangle.setStyleSheet("background-color: gray; color: white; font-weight: bold; font-size: 20px; border: 3px solid darkgray; padding: 4px; border-radius: 10px;")


            self.fixed_power = status["fixed"]["power"]
            self.left_lcd.display(self.fixed_power)

            self.tunable_power = status["tunable"]["power"]
            self.right_lcd.display(self.tunable_power)

        except Exception as e:
            print(f"Error in updateSlot: {str(e)}")

    def update_fixed_shutter_ui(self):
        """Update fixed shutter button appearance"""
        if self.fixed_shutter_open:
            self.left_button.setText("OPEN")
            self.left_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: green;"
            )
        else:
            self.left_button.setText("CLOSED")
            self.left_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: gray;"
            )

    def update_tunable_shutter_ui(self):
        """Update tunable shutter button appearance"""
        if self.tunable_shutter_open:
            self.right_button.setText("OPEN")
            self.right_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: green;"
            )
        else:
            self.right_button.setText("CLOSED")
            self.right_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: gray;"
            )

    def update_state_info(self):
        """Update the state info text boxes"""
        dict = {
            "keyswitch": {1: "ON", 0: "OFF"},
            "tuning": {1: "Tuning...", 0: "Tuned"},
            "lasing": {1: "Lasing!", 0: "Not Lasing"}
        }
        self.keyText.setText(dict["keyswitch"][self.keyswitch])
        self.busyText.setText(self.busy)
        self.tuningText.setText(dict["tuning"][self.tuning])
        self.lasingText.setText(dict["lasing"][self.lasing])

    def update_align(self):
        """Update the alignment mode checkboxes"""
        if self.fixed_align and self.checkbox1.isChecked():
            self.checkbox2.setDisabled(True)
        if self.tunable_align and self.checkbox2.isChecked():
            self.checkbox1.setDisabled(True)

    def switch_align_fixed(self):
        try :
            self.set_align_fixed(0 if self.checkbox1.isChecked() else 1)
        except Exception as e:
            print(f"Error in switch_align_fixed: {str(e)}")

    def switch_align_tunable(self):
        try :
            self.set_align_tunable(0 if self.checkbox2.isChecked() else 1)
        except Exception as e:
            print(f"Error in switch_align_tunable: {str(e)}")
