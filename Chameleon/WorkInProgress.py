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
        d["lasing"] = self.is_lasing()
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

        self.dict = {
            "keyswitch": {"ON": 1, "OFF": 0}, 
            "tuning": {"Tuning...": 1, "Tuned": 0}, 
            "lasing": {"Lasing!": 1, "Not Lasing": 0}   
        }

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
                
                sub_group_text_box = QLineEdit(f"{list(group_names.values())[i*2 + j]}")
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
        checkbox1 = QtWidgets.QCheckBox("FIXED")
        checkbox2 = QtWidgets.QCheckBox("TUNABLE")
        
        checkbox_layout.addWidget(checkbox_label)
        checkbox_layout.addWidget(checkbox1)
        checkbox_layout.addWidget(checkbox2)
        
        checkbox_group.setLayout(checkbox_layout)
        first_tab_layout.addWidget(checkbox_group, 1)
        
        first_tab.setLayout(first_tab_layout)
        
        # Second Tab - Button on Top, Group Below Divided Vertically
        second_tab = QWidget()
        second_tab_layout = QVBoxLayout()
        
        # Red Rectangle Label
        red_rectangle = QLabel("LASING!")
        red_rectangle.setAlignment(Qt.AlignCenter)
        red_rectangle.setStyleSheet("""
            background-color: red; 
            color: white; 
            font-weight: bold; 
            font-size: 20px; 
            border: 3px solid darkred; 
            padding: 4px;
            border-radius: 10px;
        """)
        red_rectangle.setMinimumHeight(20)  # Ensure minimum height
        red_rectangle.setMaximumHeight(35)  # Ensure max height
        
        # Main Group for Second Tab
        second_main_group = QGroupBox("SHUTTERS")
        second_main_group_layout = QHBoxLayout()
        
        # left Subgroup
        left_subgroup = QGroupBox("FIXED")
        left_subgroup_layout = QVBoxLayout()
        
        left_label = QLabel("1030 nm")
        left_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        left_label.setAlignment(Qt.AlignCenter)
        left_lcd = QLCDNumber()
        left_lcd.setDigitCount(5)
        left_lcd.setStyleSheet("color: blue; background-color: black;")
        left_lcd.setMinimumHeight(40)
        left_lcd.display(12345)
        
        self.left_button = QPushButton("OPEN")
        self.left_button.setMinimumHeight(32)
        
        left_subgroup_layout.addWidget(left_label)
        left_subgroup_layout.addWidget(left_lcd)
        left_subgroup_layout.addWidget(self.left_button)
        left_subgroup.setLayout(left_subgroup_layout)
        
        # Bottom Subgroup
        right_subgroup = QGroupBox("TUNABLE")
        right_subgroup_layout = QVBoxLayout()
        
        self.right_label = QLabel(f"{self.current_wavelength} nm")
        self.right_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.right_label.setAlignment(Qt.AlignCenter)
        right_lcd = QLCDNumber()
        right_lcd.setDigitCount(5)
        right_lcd.setStyleSheet("color: green; background-color: black;")
        right_lcd.setMinimumHeight(40)
        right_lcd.display(67890)
        
        self.right_button = QPushButton("OPEN")
        self.right_button.setMinimumHeight(32)
        
        right_subgroup_layout.addWidget(self.right_label)
        right_subgroup_layout.addWidget(right_lcd)
        right_subgroup_layout.addWidget(self.right_button)
        right_subgroup.setLayout(right_subgroup_layout)
        
        # Add subgroups to main group
        second_main_group_layout.addWidget(left_subgroup)
        second_main_group_layout.addWidget(right_subgroup)
        second_main_group.setLayout(second_main_group_layout)
        
        # Add components to second tab layout
        second_tab_layout.addWidget(red_rectangle)
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
        self.wavelength_input = QLineEdit()
        self.wavelength_input.setPlaceholderText("Enter wavelength (680-1030)")
        self.wavelength_set_button = QPushButton("Set Wavelength")
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
            preset_btn.clicked.connect(lambda _, v=value: self.set_wavelength_with_safety(v))
            preset_row.addWidget(preset_btn)

        # Add widgets to layout
        wavelength_layout.addLayout(input_row)
        wavelength_layout.addLayout(slider_layout)
        wavelength_layout.addLayout(preset_row)

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
            
            # Update slider and label
            self.wavelength_slider.setValue(wavelength)
            self.right_label.setText(f"{wavelength} nm")
            
            QMessageBox.information(
                None, 
                "Wavelength Set", 
                f"Wavelength successfully set to {wavelength} nm."
            )
        
        except ValueError:
            QMessageBox.warning(
                None, 
                "Input Error", 
                "Please enter a valid integer wavelength."
        )

    def update_ui_from_device(self):
        """Initialize the UI state from device status"""
        try:
            # Update wavelength display and slider
            wl = self.wavelength()
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.tunable_status_label.setText(f"TUN {wl} nm:")
            self.inner_wl_label.setText(f"Current Wavelength = {self.current_wavelength}")

            # Update shutter status
            self.fixed_shutter_open = self.is_shutter_open_fixed()
            self.tunable_shutter_open = self.is_shutter_open_tunable()
            self.update_fixed_shutter_ui()
            self.update_tunable_shutter_ui()

            # Update lasing indicators
            is_lasing = self.is_lasing()
            if is_lasing:
                if self.fixed_shutter_open:
                    self.fixed_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")
                if self.tunable_shutter_open:
                    self.tunable_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")

            # Update power displays
            if is_lasing:
                self.fixed_power = self.power_fixed() ###
                self.fixed_power_display.display(self.fixed_power)

                self.tunable_power = self.power_tunable()
                self.tunable_power_display.display(self.tunable_power)

            # Update energy display
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/wl))

            # Update popup window if it exists
            self.update_popup_window()

        except Exception as e:
            print(f"Error initializing UI from device: {str(e)}")

    def updateSlot(self, status):
        """Update UI elements based on device status updates"""
        try:
            # Update wavelength display
            wl = status["tunable"]["wavelength"]
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.tunable_status_label.setText(f"TUN {wl} nm:")
            self.inner_wl_label.setText(f"Current Wavelength = {self.current_wavelength}")
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/wl))

            # Update shutter status
            fixed_shutter = self.is_shutter_open_fixed()
            tunable_shutter = status["tunable"]["shutter"]

            if fixed_shutter != self.fixed_shutter_open:
                self.fixed_shutter_open = fixed_shutter
                self.update_fixed_shutter_ui()

            if tunable_shutter != self.tunable_shutter_open:
                self.tunable_shutter_open = tunable_shutter
                self.update_tunable_shutter_ui()

            # Update lasing status
            is_lasing = status["lasing"]

            # Update power displays
            if  is_lasing:
                self.fixed_power = status["fixed"]["power"] ###
                self.fixed_power_display.display(self.fixed_power)
                self.fixed_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")

                self.tunable_power = status["tunable"]["power"]
                self.tunable_power_display.display(self.tunable_power)
                self.tunable_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")
            else:
                self.fixed_power = 0.0
                self.fixed_power_display.display(self.fixed_power)
                self.fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")

                self.tunable_power = 0.0
                self.tunable_power_display.display(self.tunable_power)
                self.tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")

            # Update popup window if it exists
            self.update_popup_window()

        except Exception as e:
            print(f"Error in updateSlot: {str(e)}")