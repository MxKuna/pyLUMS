import sys

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLCDNumber,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ChameleonGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chameleon Laser GUI")
        self.setGeometry(100, 100, 650, 550)
        self.current_wavelength = 750  # Default value
        
        # Lasing states and power values
        self.fixed_lasing = False
        self.tunable_lasing = False
        self.fixed_power = 0.0    # Power in mW
        self.tunable_power = 0.0  # Power in mW
        
        # Shutter states
        self.fixed_shutter_open = False
        self.tunable_shutter_open = False
        
        self.createDock()
    
    def createDock(self):
        """Creates a dock widget with lasing status, shutters, and wavelength controls"""
        dock = QDockWidget("Chameleon laser", self)
        widget = QWidget()
        main_layout = QVBoxLayout()
        
        # ---- 1. Lasing Status and Powers Section ----
        lasing_group = QGroupBox("Laser Status")
        lasing_layout = QVBoxLayout()
        
        # Create a horizontal separator line
        def create_separator():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            return line
        
        # Fixed beam status
        fixed_status_layout = QHBoxLayout()
        
        # Indicator and label in one container with fixed width
        fixed_label_container = QHBoxLayout()
        fixed_lasing_indicator = QLabel("⬤")
        fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.fixed_lasing_indicator = fixed_lasing_indicator
        
        fixed_status_label = QLabel("FIXED 1064 nm:")
        fixed_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        fixed_status_label.setMinimumWidth(150)
        fixed_status_label.setMaximumWidth(150)
        
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
        
        # Add both containers to the main layout with stretch
        fixed_status_layout.addLayout(fixed_label_container, 1)
        fixed_status_layout.addLayout(power_display_container, 1)
        lasing_layout.addLayout(fixed_status_layout)
        
        lasing_layout.addWidget(create_separator())
        
        # Tunable beam status
        tunable_status_layout = QHBoxLayout()
        
        # Indicator and label in one container with fixed width
        tunable_label_container = QHBoxLayout()
        tunable_lasing_indicator = QLabel("⬤")
        tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
        self.tunable_lasing_indicator = tunable_lasing_indicator
        
        tunable_status_label = QLabel(f"TUNABLE {self.current_wavelength} nm:")
        tunable_status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        tunable_status_label.setMinimumWidth(150)
        tunable_status_label.setMaximumWidth(150)
        self.tunable_status_label = tunable_status_label
        
        tunable_label_container.addWidget(tunable_lasing_indicator)
        tunable_label_container.addWidget(tunable_status_label)
        tunable_label_container.addStretch()
        
        # Power display container
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
        
        # Add both containers to the main layout with stretch
        tunable_status_layout.addLayout(tunable_label_container, 1)
        tunable_status_layout.addLayout(tunable_power_container, 1)
        lasing_layout.addLayout(tunable_status_layout)
        
        # Test buttons (for simulation only, would be removed in production)
        test_layout = QHBoxLayout()
        test_fixed_button = QPushButton("Test Fixed")
        test_fixed_button.clicked.connect(self.test_fixed_lasing)
        test_tunable_button = QPushButton("Test Tunable")
        test_tunable_button.clicked.connect(self.test_tunable_lasing)
        test_layout.addWidget(test_fixed_button)
        test_layout.addWidget(test_tunable_button)
        lasing_layout.addLayout(test_layout)  # Add test buttons
        
        lasing_group.setLayout(lasing_layout)
        main_layout.addWidget(lasing_group)
        
        # ---- 2. Shutter Control Section ----
        shutter_group = QGroupBox("Shutter Control")
        shutter_layout = QVBoxLayout()
        
        # Create horizontal layouts for each shutter with labels outside button
        fixed_layout = QHBoxLayout()
        tunable_layout = QHBoxLayout()
        
        # Fixed beam controls
        fixed_label = QLabel("FIXED Beam:")
        fixed_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.fixed_shutter_button = QPushButton("CLOSED")
        self.fixed_shutter_button.setCheckable(True)
        self.fixed_shutter_button.clicked.connect(self.toggle_fixed_shutter)
        self.fixed_shutter_button.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
        self.fixed_shutter_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        fixed_layout.addWidget(fixed_label, 1)
        fixed_layout.addWidget(self.fixed_shutter_button, 2)
        
        # Tunable beam controls  
        tunable_label = QLabel("TUNABLE Beam:")
        tunable_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.tunable_shutter_button = QPushButton("CLOSED")
        self.tunable_shutter_button.setCheckable(True)
        self.tunable_shutter_button.clicked.connect(self.toggle_tunable_shutter)
        self.tunable_shutter_button.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
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
        
        # Input field and feedback
        input_layout = QHBoxLayout()
        self.wavelength_input = QLineEdit()
        self.wavelength_input.setPlaceholderText("Enter wavelength (660-1320 nm)")
        self.wavelength_input.returnPressed.connect(self.set_wavelength_from_input)
        set_button = QPushButton("Set")
        set_button.clicked.connect(self.set_wavelength_from_input)
        input_layout.addWidget(self.wavelength_input, 3)
        input_layout.addWidget(set_button, 1)
        wavelength_layout.addLayout(input_layout)
        
        # Slider
        self.wavelength_slider = QSlider(QtCore.Qt.Horizontal)
        self.wavelength_slider.setMinimum(660)
        self.wavelength_slider.setMaximum(1320)
        self.wavelength_slider.setValue(self.current_wavelength)
        self.wavelength_slider.valueChanged.connect(self.set_wavelength_from_slider)
        
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("660 nm"))
        slider_layout.addWidget(self.wavelength_slider)
        slider_layout.addWidget(QLabel("1320 nm"))
        wavelength_layout.addWidget(QLabel("Adjust Wavelength:"))
        wavelength_layout.addLayout(slider_layout)
        
        # Preset buttons
        button_layout = QHBoxLayout()
        self.preset_680 = QPushButton("680 nm")
        self.preset_750 = QPushButton("750 nm")
        self.preset_1030 = QPushButton("1030 nm")
        self.preset_680.clicked.connect(lambda: self.set_wavelength(680))
        self.preset_750.clicked.connect(lambda: self.set_wavelength(750))
        self.preset_1030.clicked.connect(lambda: self.set_wavelength(1030))
        button_layout.addWidget(self.preset_680)
        button_layout.addWidget(self.preset_750)
        button_layout.addWidget(self.preset_1030)
        wavelength_layout.addWidget(QLabel("Presets:"))
        wavelength_layout.addLayout(button_layout)
        
        wavelength_group.setLayout(wavelength_layout)
        main_layout.addWidget(wavelength_group)
        
        widget.setLayout(main_layout)
        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        self.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
    
    def set_wavelength(self, value):
        """Set the wavelength from a preset button"""
        self.current_wavelength = value
        self.tunable_status_label.setText(f"TUNABLE {self.current_wavelength} nm:")
        self.wavelength_slider.setValue(value)
        # Update the display if the tunable beam is lasing
        if self.tunable_lasing:
            self.update_tunable_power()
    
    def set_wavelength_from_input(self):
        """Set the wavelength from the text input"""
        try:
            value = int(self.wavelength_input.text())
            if 660 <= value <= 1320:
                self.set_wavelength(value)
                self.wavelength_input.clear()
            else:
                self.wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
                QtCore.QTimer.singleShot(1000, lambda: self.wavelength_input.setStyleSheet(""))
        except ValueError:
            self.wavelength_input.setStyleSheet("background-color: rgba(255, 0, 0, 50);")
            QtCore.QTimer.singleShot(1000, lambda: self.wavelength_input.setStyleSheet(""))
    
    def set_wavelength_from_slider(self, value):
        """Set the wavelength from the slider"""
        self.set_wavelength(value)
    
    def toggle_fixed_shutter(self):
        """Toggle the fixed beam shutter state"""
        self.fixed_shutter_open = not self.fixed_shutter_open
        self.update_fixed_shutter_ui()
        
        # In a real system, this would also trigger lasing if the laser is on
        # For this demo, we'll simulate lasing when shutter is opened
        if self.fixed_shutter_open:
            self.fixed_lasing = True
            self.update_fixed_power()
        else:
            self.fixed_lasing = False
            self.fixed_power = 0.0
            self.fixed_power_display.display(0.0)
            self.fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
    
    def toggle_tunable_shutter(self):
        """Toggle the tunable beam shutter state"""
        self.tunable_shutter_open = not self.tunable_shutter_open
        self.update_tunable_shutter_ui()
        
        # In a real system, this would also trigger lasing if the laser is on
        # For this demo, we'll simulate lasing when shutter is opened
        if self.tunable_shutter_open:
            self.tunable_lasing = True
            self.update_tunable_power()
        else:
            self.tunable_lasing = False
            self.tunable_power = 0.0
            self.tunable_power_display.display(0.0)
            self.tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
    
    def update_fixed_shutter_ui(self):
        """Update the UI for the fixed shutter button"""
        if self.fixed_shutter_open:
            self.fixed_shutter_button.setText("OPEN")
            self.fixed_shutter_button.setStyleSheet(
                "color: green; font-weight: bold; font-size: 14px; background-color: rgba(0, 255, 0, 100);"
            )
        else:
            self.fixed_shutter_button.setText("CLOSED")
            self.fixed_shutter_button.setStyleSheet(
                "color: red; font-weight: bold; font-size: 14px;"
            )
    
    def update_tunable_shutter_ui(self):
        """Update the UI for the tunable shutter button"""
        if self.tunable_shutter_open:
            self.tunable_shutter_button.setText("OPEN")
            self.tunable_shutter_button.setStyleSheet(
                "color: green; font-weight: bold; font-size: 14px; background-color: rgba(0, 255, 0, 100);"
            )
        else:
            self.tunable_shutter_button.setText("CLOSED")
            self.tunable_shutter_button.setStyleSheet(
                "color: red; font-weight: bold; font-size: 14px;"
            )
    
    def update_fixed_power(self):
        """Update the fixed beam power display (simulated)"""
        if self.fixed_lasing:
            # Simulated power - in real application, this would read from the hardware
            self.fixed_power = 1500.0  # Fixed wavelength typically outputs higher power
            self.fixed_power_display.display(self.fixed_power)
            self.fixed_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")  # Red indicator for lasing
    
    def update_tunable_power(self):
        """Update the tunable beam power display (simulated)"""
        if self.tunable_lasing:
            # Simulated power - in real application, this would read from the hardware
            # Power varies with wavelength in most tunable lasers
            base_power = 1000.0
            wavelength_factor = 1.0 - abs(self.current_wavelength - 800) / 700  # Peak power around 800nm
            self.tunable_power = base_power * wavelength_factor
            self.tunable_power_display.display(round(self.tunable_power, 1))
            self.tunable_lasing_indicator.setStyleSheet("color: #FF0000; font-size: 20px;")  # Red indicator for lasing
    
    # Test functions for demonstration
    def test_fixed_lasing(self):
        """Test toggle for fixed beam lasing (demo only)"""
        self.fixed_lasing = not self.fixed_lasing
        if self.fixed_lasing:
            self.update_fixed_power()
            # Also open shutter if it's closed
            if not self.fixed_shutter_open:
                self.toggle_fixed_shutter()
        else:
            self.fixed_power = 0.0
            self.fixed_power_display.display(0.0)
            self.fixed_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")
    
    def test_tunable_lasing(self):
        """Test toggle for tunable beam lasing (demo only)"""
        self.tunable_lasing = not self.tunable_lasing
        if self.tunable_lasing:
            self.update_tunable_power()
            # Also open shutter if it's closed
            if not self.tunable_shutter_open:
                self.toggle_tunable_shutter()
        else:
            self.tunable_power = 0.0
            self.tunable_power_display.display(0.0)
            self.tunable_lasing_indicator.setStyleSheet("color: gray; font-size: 20px;")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChameleonGUI()
    window.show()
    sys.exit(app.exec_())