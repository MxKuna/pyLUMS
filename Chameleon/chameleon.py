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
from PyQt5.QtWidgets import QTabWidget  # Added for tabbed interface
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLCDNumber,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
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

@include_remote_methods(ChameleonWorker)
class Chameleon(DeviceOverZeroMQ):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default values for GUI display
        self.current_wavelength = 2137
        self.fixed_power = 2137
        self.tunable_power = 2137
        self.fixed_shutter_open = False
        self.tunable_shutter_open = False

    def createDock(self, parentWidget, menu=None):
        """ Function for integration in GUI app. Creates a comprehensive
        GUI panel for the Chameleon laser control. """
        dock = QtWidgets.QDockWidget("Chameleon laser", parentWidget)
        main_widget = QtWidgets.QWidget(parentWidget)

        # Create a tab widget
        self.tab_widget = QTabWidget()

        # Create separator function
        def create_separator():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            return line

        # ---- Tab 1: Laser Status and Shutter Control ----
        status_tab = QWidget()
        status_layout = QVBoxLayout()

        # ---- 1. Lasing Status and Powers Section ----
        lasing_group = QGroupBox("Laser Status")
        lasing_layout = QVBoxLayout()

        # Fixed beam status
        fixed_status_layout = QHBoxLayout()

        # Indicator and label container
        fixed_label_container = QHBoxLayout()
        fixed_lasing_indicator = QLabel("⬤")
        fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.fixed_lasing_indicator = fixed_lasing_indicator

        fixed_status_label = QLabel("FIX 1030 nm:")
        fixed_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        fixed_status_label.setMinimumWidth(160)
        fixed_status_label.setMaximumWidth(160)

        fixed_label_container.addWidget(fixed_lasing_indicator)
        fixed_label_container.addWidget(fixed_status_label)
        fixed_label_container.addStretch()

        # Power display container
        power_display_container = QHBoxLayout()
        self.fixed_power_display = QLCDNumber()
        self.fixed_power_display.setDigitCount(5)
        self.fixed_power_display.setSegmentStyle(QLCDNumber.Flat)
        self.fixed_power_display.setStyleSheet("color: #00AAFF; background-color: black;")
        self.fixed_power_display.setMinimumWidth(100)
        self.fixed_power_display.display(self.fixed_power)

        power_unit_label = QLabel("mW")
        power_unit_label.setStyleSheet("font-weight: bold;")

        power_display_container.addWidget(self.fixed_power_display)
        power_display_container.addWidget(power_unit_label)

        fixed_status_layout.addLayout(fixed_label_container, 1)
        fixed_status_layout.addLayout(power_display_container, 1)
        lasing_layout.addLayout(fixed_status_layout)

        lasing_layout.addWidget(create_separator())

        # Tunable beam status
        tunable_status_layout = QHBoxLayout()

        # Indicator and label container
        tunable_label_container = QHBoxLayout()
        tunable_lasing_indicator = QLabel("⬤")
        tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.tunable_lasing_indicator = tunable_lasing_indicator

        self.tunable_status_label = QLabel(f"TUN {self.current_wavelength} nm:")
        self.tunable_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.tunable_status_label.setMinimumWidth(160)
        self.tunable_status_label.setMaximumWidth(160)

        tunable_label_container.addWidget(tunable_lasing_indicator)
        tunable_label_container.addWidget(self.tunable_status_label)
        tunable_label_container.addStretch()

        # Power display container for tunable
        tunable_power_container = QHBoxLayout()
        self.tunable_power_display = QLCDNumber()
        self.tunable_power_display.setDigitCount(5)
        self.tunable_power_display.setSegmentStyle(QLCDNumber.Flat)
        self.tunable_power_display.setStyleSheet("color: #00AAFF; background-color: black;")
        self.tunable_power_display.setMinimumWidth(100)
        self.tunable_power_display.display(self.tunable_power)

        power_unit_label2 = QLabel("mW")
        power_unit_label2.setStyleSheet("font-weight: bold;")

        tunable_power_container.addWidget(self.tunable_power_display)
        tunable_power_container.addWidget(power_unit_label2)

        tunable_status_layout.addLayout(tunable_label_container, 1)
        tunable_status_layout.addLayout(tunable_power_container, 1)
        lasing_layout.addLayout(tunable_status_layout)

        lasing_group.setLayout(lasing_layout)
        status_layout.addWidget(lasing_group)

        # ---- 2. Shutter Control Section ----
        shutter_group = QGroupBox("Shutter Control")
        shutter_layout = QVBoxLayout()

        # Fixed beam shutter controls
        fixed_layout = QHBoxLayout()
        fixed_label = QLabel("FIXED:")
        fixed_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.fixed_shutter_button = QPushButton("CLOSED")
        self.fixed_shutter_button.setCheckable(True)
        self.fixed_shutter_button.clicked.connect(self.toggle_fixed_shutter)
        self.fixed_shutter_button.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background-color: gray;")
        self.fixed_shutter_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        fixed_layout.addWidget(fixed_label, 1)
        fixed_layout.addWidget(self.fixed_shutter_button, 2)

        # Tunable beam shutter controls
        tunable_layout = QHBoxLayout()
        tunable_label = QLabel("TUNABLE:")
        tunable_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.tunable_shutter_button = QPushButton("CLOSED")
        self.tunable_shutter_button.setCheckable(True)
        self.tunable_shutter_button.clicked.connect(self.toggle_tunable_shutter)
        self.tunable_shutter_button.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background-color: gray;")
        self.tunable_shutter_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        tunable_layout.addWidget(tunable_label, 1)
        tunable_layout.addWidget(self.tunable_shutter_button, 2)

        shutter_layout.addLayout(fixed_layout)
        shutter_layout.addLayout(tunable_layout)
        shutter_group.setLayout(shutter_layout)
        status_layout.addWidget(shutter_group)

        status_tab.setLayout(status_layout)

        # ---- Tab 2: Wavelength Control ----
        wavelength_tab = QWidget()
        wavelength_layout = QVBoxLayout()

        # ---- 3. Wavelength Control Section ----
        wavelength_group = QGroupBox("Wavelength Control")
        wavelength_inner_layout = QVBoxLayout()

        wavelength_inner_layout.addWidget(QLabel("Set Wavelength (nm):"))

        # Input field and set button
        input_layout = QHBoxLayout()
        self.wavelength_input = QLineEdit()
        self.wavelength_input.setPlaceholderText("Enter wavelength (680-1030 nm)")
        self.wavelength_input.returnPressed.connect(self.set_wavelength_from_input)
        set_button = QPushButton("Set")
        set_button.clicked.connect(self.set_wavelength_from_input)
        input_layout.addWidget(self.wavelength_input, 3)
        input_layout.addWidget(set_button, 1)
        wavelength_inner_layout.addLayout(input_layout)

        # Slider for wavelength (read-only indicator)
        self.inner_wl_label = QLabel(f"Current Wavelength: {self.current_wavelength}")
        wavelength_inner_layout.addWidget(self.inner_wl_label)
        self.wavelength_slider = QSlider(QtCore.Qt.Horizontal)
        self.wavelength_slider.setMinimum(680)
        self.wavelength_slider.setMaximum(1030)
        self.wavelength_slider.setValue(self.current_wavelength)
        self.wavelength_slider.setEnabled(False)  # Make the slider inactive/read-only

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("680 nm"))
        slider_layout.addWidget(self.wavelength_slider)
        slider_layout.addWidget(QLabel("1030 nm"))
        wavelength_inner_layout.addLayout(slider_layout)

        # Preset buttons
        button_layout = QHBoxLayout()
        self.preset_680 = QPushButton("680 nm")
        self.preset_750 = QPushButton("750 nm")
        self.preset_800 = QPushButton("800 nm")
        self.preset_680.clicked.connect(lambda: self.set_wavelength(680))
        self.preset_750.clicked.connect(lambda: self.set_wavelength(750))
        self.preset_800.clicked.connect(lambda: self.set_wavelength(800))
        button_layout.addWidget(self.preset_680)
        button_layout.addWidget(self.preset_750)
        button_layout.addWidget(self.preset_800)
        wavelength_inner_layout.addWidget(QLabel("Presets:"))
        wavelength_inner_layout.addLayout(button_layout)

        # Add energy calculation field
        energy_layout = QHBoxLayout()
        self.display_energy = QLineEdit()
        self.display_energy.setReadOnly(True)
        energy_layout.addWidget(QLabel("Photon energy:"))
        energy_layout.addWidget(self.display_energy)
        wavelength_inner_layout.addLayout(energy_layout)

        wavelength_group.setLayout(wavelength_inner_layout)
        wavelength_layout.addWidget(wavelength_group)

        # Add a button to launch the wavelength control as a separate window
        popup_button = QPushButton("Launch as Separate Window")
        popup_button.clicked.connect(self.launch_wavelength_window)
        wavelength_layout.addWidget(popup_button)

        wavelength_tab.setLayout(wavelength_layout)

        # Add tabs to the tab widget
        self.tab_widget.addTab(status_tab, "Status & Shutter")
        self.tab_widget.addTab(wavelength_tab, "Wavelength Control")

        # Set up the main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tab_widget)
        main_widget.setLayout(main_layout)

        dock.setWidget(main_widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        # Initialize UI state based on device status
        print("\t --INITIALIZING--")
        self.update_ui_from_device()
        print("\t --DONE--")

        # Following lines "turn on" the widget operation (from original code)
        self.createListenerThread(self.updateSlot)

    def launch_wavelength_window(self):
        """Launch wavelength controls as a separate window with dark theme"""
        self.wavelength_window = QDialog()
        self.wavelength_window.setWindowTitle("Wavelength Control")
        self.wavelength_window.setMinimumWidth(400)

        # Apply dark theme to the entire window
        self.wavelength_window.setStyleSheet("""
            QDialog, QGroupBox, QLabel {
                background-color: #2D2D30;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #3E3E42;
                color: white;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #007ACC;
            }
            QLineEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #3E3E42;
                padding: 3px;
            }
        """)

        # Create a copy of the wavelength controls for the popup window
        popup_layout = QVBoxLayout()

        # ---- Wavelength Control Section for Popup ----
        wavelength_group = QGroupBox("Wavelength Control")
        wavelength_layout = QVBoxLayout()

        wavelength_layout.addWidget(QLabel("Set Wavelength (nm):"))

        # Input field and set button
        input_layout = QHBoxLayout()
        popup_wavelength_input = QLineEdit()
        popup_wavelength_input.setPlaceholderText("Enter wavelength (680-1030 nm)")
        self.popup_wavelength_input = popup_wavelength_input  # Save reference for validation
        popup_wavelength_input.returnPressed.connect(lambda: self.set_wavelength_from_popup(popup_wavelength_input.text()))
        popup_set_button = QPushButton("Set")
        popup_set_button.clicked.connect(lambda: self.set_wavelength_from_popup(popup_wavelength_input.text()))
        input_layout.addWidget(popup_wavelength_input, 3)
        input_layout.addWidget(popup_set_button, 1)
        wavelength_layout.addLayout(input_layout)

        # Current wavelength display
        current_wl_layout = QHBoxLayout()
        self.current_wl_label = QLabel("Current Wavelength:")
        popup_wl_value = QLabel(f"{self.current_wavelength} nm")
        popup_wl_value.setStyleSheet("font-weight: bold; font-size: 16px; color: #00AAFF;")
        self.popup_wl_value = popup_wl_value  # Save reference to update later
        current_wl_layout.addWidget(self.current_wl_label)
        current_wl_layout.addWidget(popup_wl_value)
        wavelength_layout.addLayout(current_wl_layout)

        # Wavelength range slider (read-only indicator)
        popup_slider_layout = QHBoxLayout()
        popup_wavelength_slider = QSlider(QtCore.Qt.Horizontal)
        popup_wavelength_slider.setMinimum(680)
        popup_wavelength_slider.setMaximum(1030)
        popup_wavelength_slider.setValue(self.current_wavelength)
        popup_wavelength_slider.setEnabled(False)  # Make the slider inactive/read-only
        self.popup_wavelength_slider = popup_wavelength_slider  # Save reference to update later
        min_label = QLabel("680 nm")
        min_label.setStyleSheet("color: #999999;")
        max_label = QLabel("1030 nm")
        max_label.setStyleSheet("color: #999999;")
        popup_slider_layout.addWidget(min_label)
        popup_slider_layout.addWidget(popup_wavelength_slider)
        popup_slider_layout.addWidget(max_label)
        wavelength_layout.addLayout(popup_slider_layout)

        # Preset buttons
        button_layout = QHBoxLayout()
        preset_680 = QPushButton("680 nm")
        preset_750 = QPushButton("750 nm")
        preset_800 = QPushButton("800 nm")
        preset_850 = QPushButton("850 nm")
        preset_680.clicked.connect(lambda: self.set_wavelength(680))
        preset_750.clicked.connect(lambda: self.set_wavelength(750))
        preset_800.clicked.connect(lambda: self.set_wavelength(800))
        preset_850.clicked.connect(lambda: self.set_wavelength(850))
        button_layout.addWidget(preset_680)
        button_layout.addWidget(preset_750)
        button_layout.addWidget(preset_800)
        button_layout.addWidget(preset_850)
        wavelength_layout.addWidget(QLabel("Presets:"))
        wavelength_layout.addLayout(button_layout)

        # Add energy calculation field
        energy_layout = QHBoxLayout()
        popup_energy = QLineEdit()
        popup_energy.setReadOnly(True)
        popup_energy.setText(self.display_energy.text())
        self.popup_energy = popup_energy  # Save reference to update later
        energy_layout.addWidget(QLabel("Photon energy:"))
        energy_layout.addWidget(popup_energy)
        wavelength_layout.addLayout(energy_layout)

        # Add validation status message
        self.popup_status_msg = QLabel("")
        self.popup_status_msg.setStyleSheet("color: #FF5555;")
        wavelength_layout.addWidget(self.popup_status_msg)

        wavelength_group.setLayout(wavelength_layout)
        popup_layout.addWidget(wavelength_group)

        # Add shutter status display for context
        shutter_status_layout = QHBoxLayout()
        tunable_status = "OPEN" if self.tunable_shutter_open else "CLOSED"
        tunable_color = "green" if self.tunable_shutter_open else "gray"
        shutter_status_label = QLabel(f"Tunable Shutter: ")
        shutter_status_value = QLabel(tunable_status)
        shutter_status_value.setStyleSheet(f"color: {tunable_color}; font-weight: bold;")
        self.popup_shutter_status = shutter_status_value  # Save reference to update later
        shutter_status_layout.addWidget(shutter_status_label)
        shutter_status_layout.addWidget(shutter_status_value)
        shutter_status_layout.addStretch()
        popup_layout.addLayout(shutter_status_layout)

        # Add close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.wavelength_window.close)
        popup_layout.addWidget(close_button)

        self.wavelength_window.setLayout(popup_layout)
        self.wavelength_window.show()

    def set_wavelength_from_popup(self, text):
        """Handle wavelength setting from popup window with validation"""
        try:
            value = int(text)
            if 680 <= value <= 1030:
                self.set_wavelength(value)
                self.popup_wavelength_input.clear()
                self.popup_status_msg.setText("")
            else:
                self.popup_wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
                self.popup_status_msg.setText(f"Valid range: 680-1030 nm. Got: {value} nm")
                QtCore.QTimer.singleShot(1000, lambda: self.popup_wavelength_input.setStyleSheet("background-color: #1E1E1E; color: #FFFFFF;"))
        except ValueError:
            self.popup_wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
            self.popup_status_msg.setText("Please enter a valid integer wavelength")
            QtCore.QTimer.singleShot(1000, lambda: self.popup_wavelength_input.setStyleSheet("background-color: #1E1E1E; color: #FFFFFF;"))

    def update_popup_window(self):
        """Update the popup window if it exists with more comprehensive updates"""
        if hasattr(self, 'wavelength_window') and self.wavelength_window.isVisible():
            try:
                # Update wavelength and energy displays
                self.popup_wl_value.setText(f"{self.current_wavelength} nm")
                self.popup_energy.setText(self.display_energy.text())

                # Update slider position
                self.popup_wavelength_slider.setValue(self.current_wavelength)

                # Update shutter status if available
                if hasattr(self, 'popup_shutter_status'):
                    tunable_status = "OPEN" if self.tunable_shutter_open else "CLOSED"
                    tunable_color = "green" if self.tunable_shutter_open else "gray"
                    self.popup_shutter_status.setText(tunable_status)
                    self.popup_shutter_status.setStyleSheet(f"color: {tunable_color}; font-weight: bold;")

            except Exception as e:
                print(f"Error updating popup window: {str(e)}")

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

    def update_popup_window(self):
        """Update the popup window if it exists"""
        if hasattr(self, 'wavelength_window') and self.wavelength_window.isVisible():
            try:
                self.popup_wl_value.setText(f"{self.current_wavelength} nm")
                self.popup_energy.setText(self.display_energy.text())
            except Exception as e:
                print(f"Error updating popup window: {str(e)}")

    def set_wavelength(self, value):
        """Set wavelength from preset button or other input"""
        try:
            # Call the parent class's set_wavelength method
            super().set_wavelength(value)

            # Update UI elements
            self.current_wavelength = value
            self.tunable_status_label.setText(f"TUN {value} nm:")
            self.wavelength_slider.setValue(value)
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/value))

            # Update popup window if it exists
            self.update_popup_window()
        except Exception as e:
            print(f"Error setting wavelength: {str(e)}")

    def set_wavelength_from_input(self):
        """Set wavelength from input field"""
        try:
            value = int(self.wavelength_input.text())
            if 680 <= value <= 1030:
                self.set_wavelength(value)
                self.wavelength_input.clear()
            else:
                self.wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
                QtCore.QTimer.singleShot(1000, lambda: self.wavelength_input.setStyleSheet(""))
        except ValueError:
            self.wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
            QtCore.QTimer.singleShot(1000, lambda: self.wavelength_input.setStyleSheet(""))

    def toggle_fixed_shutter(self):
        """Toggle fixed beam shutter"""
        try:
            if self.is_shutter_open_fixed():
                self.close_shutter_fixed()
            else:
                self.open_shutter_fixed()
            self.update_fixed_shutter_ui()
        except Exception as e:
            print(f"Error toggling fixed shutter: {str(e)}")

    def toggle_tunable_shutter(self):
        """Toggle tunable beam shutter"""
        try:
            if self.is_shutter_open_tunable():
                self.close_shutter_tunable()
            else:
                self.open_shutter_tunable()
            self.update_tunable_shutter_ui()
        except Exception as e:
            print(f"Error toggling tunable shutter: {str(e)}")

    def update_fixed_shutter_ui(self):
        """Update fixed shutter button appearance"""
        if self.is_shutter_open_fixed():
            self.fixed_shutter_button.setText("OPEN")
            self.fixed_shutter_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: green;"
            )
        else:
            self.fixed_shutter_button.setText("CLOSED")
            self.fixed_shutter_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: gray;"
            )

    def update_tunable_shutter_ui(self):
        """Update tunable shutter button appearance"""
        if self.is_shutter_open_tunable():
            self.tunable_shutter_button.setText("OPEN")
            self.tunable_shutter_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: green;"
            )
        else:
            self.tunable_shutter_button.setText("CLOSED")
            self.tunable_shutter_button.setStyleSheet(
                "color: white; font-weight: bold; font-size: 14px; background-color: gray;"
            )

    def get_wavelength(self):
        """Get current wavelength - maintained for backward compatibility"""
        return self.wavelength()
