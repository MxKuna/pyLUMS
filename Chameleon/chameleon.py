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
    '''The class contains every methods needed to talk to the motor'''
    
   
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
        return int(self.query('?WV'))
        
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
    
    
@include_remote_methods(ChameleonWorker)
class Chameleon(DeviceOverZeroMQ):  
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default values for GUI display
        self.current_wavelength = 0
        self.fixed_power = 0.0
        self.tunable_power = 0.0
        self.fixed_shutter_open = False
        self.tunable_shutter_open = False
                             
    def createDock(self, parentWidget, menu=None):
        """ Function for integration in GUI app. Creates a comprehensive
        GUI panel for the Chameleon laser control. """
        dock = QtWidgets.QDockWidget("Chameleon laser", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        main_layout = QVBoxLayout()
        
        # ---- 1. Lasing Status and Powers Section ----
        lasing_group = QGroupBox("Laser Status")
        lasing_layout = QVBoxLayout()
        
        # Create separator function
        def create_separator():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            return line
        
        # Fixed beam status
        fixed_status_layout = QHBoxLayout()
        
        # Indicator and label container
        fixed_label_container = QHBoxLayout()
        fixed_lasing_indicator = QLabel("⬤")
        fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.fixed_lasing_indicator = fixed_lasing_indicator
        
        fixed_status_label = QLabel("FIXED \t\t 1030 nm:")
        fixed_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        fixed_status_label.setMinimumWidth(110)
        fixed_status_label.setMaximumWidth(170)
        
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
        
        self.tunable_status_label = QLabel(f"TUNABLE \t {self.current_wavelength} nm:")
        self.tunable_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.tunable_status_label.setMinimumWidth(110)
        self.tunable_status_label.setMaximumWidth(170)
        
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
        main_layout.addWidget(lasing_group)
        
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
        main_layout.addWidget(shutter_group)
        
        # ---- 3. Wavelength Control Section ----
        wavelength_group = QGroupBox("Wavelength Control")
        wavelength_layout = QVBoxLayout()
        
        wavelength_layout.addWidget(QLabel("Set Wavelength (nm):"))
        
        # Input field and set button
        input_layout = QHBoxLayout()
        self.wavelength_input = QLineEdit()
        self.wavelength_input.setPlaceholderText("Enter wavelength (680-900 nm)")
        self.wavelength_input.returnPressed.connect(self.set_wavelength_from_input)
        set_button = QPushButton("Set")
        set_button.clicked.connect(self.set_wavelength_from_input)
        input_layout.addWidget(self.wavelength_input, 3)
        input_layout.addWidget(set_button, 1)
        wavelength_layout.addLayout(input_layout)
        
        # Slider for wavelength (read-only indicator)
        wavelength_layout.addWidget(QLabel("Current Wavelength:"))
        self.wavelength_slider = QSlider(QtCore.Qt.Horizontal)
        self.wavelength_slider.setMinimum(680)
        self.wavelength_slider.setMaximum(900)
        self.wavelength_slider.setValue(self.current_wavelength)
        self.wavelength_slider.setEnabled(False)  # Make the slider inactive/read-only
        
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("680 nm"))
        slider_layout.addWidget(self.wavelength_slider)
        slider_layout.addWidget(QLabel("900 nm"))
        wavelength_layout.addLayout(slider_layout)
        
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
        wavelength_layout.addWidget(QLabel("Presets:"))
        wavelength_layout.addLayout(button_layout)
        
        # Add energy calculation field
        energy_layout = QHBoxLayout()
        self.display_energy = QLineEdit()
        self.display_energy.setReadOnly(True)
        energy_layout.addWidget(QLabel("Photon energy:"))
        energy_layout.addWidget(self.display_energy)
        wavelength_layout.addLayout(energy_layout)
        
        wavelength_group.setLayout(wavelength_layout)
        main_layout.addWidget(wavelength_group)
        
        widget.setLayout(main_layout)
        dock.setWidget(widget)
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
    
    def update_ui_from_device(self):
        """Initialize the UI state from device status"""
        try:
            # Update wavelength display and slider
            wl = self.wavelength()
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.tunable_status_label.setText(f"TUNABLE {wl} nm:")
            
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
                self.fixed_power = 1500.0  # Estimated - would need actual power reading
                self.fixed_power_display.display(self.fixed_power)

                self.tunable_power = self.power_tunable()
                self.tunable_power_display.display(self.tunable_power)
                
            # Update energy display
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/wl))
            
        except Exception as e:
            print(f"Error initializing UI from device: {str(e)}")
        
    def updateSlot(self, status):
        """Update UI elements based on device status updates"""
        try:
            # Update wavelength display
            wl = status["tunable"]["wavelength"]
            self.current_wavelength = wl
            self.wavelength_slider.setValue(wl)
            self.tunable_status_label.setText(f"TUNABLE {wl} nm:")
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
                self.fixed_power = 4500.0  # Estimated - would need actual power reading
                self.fixed_power_display.display(self.fixed_power)
                self.fixed_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")
                
                self.tunable_power = status["tunable"]["power"]
                self.tunable_power_display.display(self.tunable_power)
                self.tunable_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")
            else:
                self.fixed_power_display.display(0.0)
                self.fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
                
                self.tunable_power = 0.0
                self.tunable_power_display.display(0.0)
                self.tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
                
        except Exception as e:
            print(f"Error in updateSlot: {str(e)}")
    
    def set_wavelength(self, value):
        """Set wavelength from preset button or other input"""
        try:
            self.set_wavelength(value)  # Call remote method
            self.current_wavelength = value
            self.tunable_status_label.setText(f"TUNABLE {value} nm:")
            self.wavelength_slider.setValue(value)
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/value))
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