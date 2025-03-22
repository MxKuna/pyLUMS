from devices.zeromq_device import DeviceWorker, DeviceOverZeroMQ, remote, include_remote_methods
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import (
    QPushButton, QMessageBox, QDialog,
    QApplication, QWidget, QMainWindow,
    QVBoxLayout, QHBoxLayout, QLineEdit,
    QLabel, QInputDialog
)
from PyQt5.QtGui import (QFont, QColor)
import scipy.optimize
import numpy as np
from devices import H_C, N_AIR


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
        try:
            if hasattr(self, 'ser') and self.ser:
                self.ser.close() #serial port close
        except:
            pass

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

    @remote
    def get_wavelength(self):
        """Alias for wavelength() to maintain backward compatibility"""
        return self.wavelength()

@include_remote_methods(ChameleonWorker)
class Chameleon(DeviceOverZeroMQ):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def createDock(self, parentWidget, menu=None):
        """ Enhanced dock widget for Chameleon laser control """
        dock = QtWidgets.QDockWidget("Chameleon Laser", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)

        # Main layout
        main_layout = QtWidgets.QVBoxLayout()

        # Status section with indicator lights
        status_layout = QtWidgets.QHBoxLayout()

        # Lasing status indicator
        lasing_layout = QtWidgets.QVBoxLayout()
        self.lasing_indicator = QtWidgets.QLabel()
        self.lasing_indicator.setFixedSize(15, 15)
        self.lasing_indicator.setStyleSheet("background-color: gray; border-radius: 7px;")
        lasing_label = QtWidgets.QLabel("Lasing")
        lasing_label.setAlignment(QtCore.Qt.AlignCenter)
        lasing_layout.addWidget(self.lasing_indicator, 0, QtCore.Qt.AlignCenter)
        lasing_layout.addWidget(lasing_label)

        # Toggle laser button
        self.laser_toggle = QtWidgets.QPushButton("OFF")
        self.laser_toggle.setFixedWidth(60)
        self.laser_toggle.setCheckable(True)
        self.laser_toggle.clicked.connect(self.toggle_laser)
        lasing_layout.addWidget(self.laser_toggle, 0, QtCore.Qt.AlignCenter)
        status_layout.addLayout(lasing_layout)

        # Vertical separator
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        status_layout.addWidget(line)

        # Tunable beam section
        tunable_layout = QtWidgets.QVBoxLayout()
        tunable_label = QtWidgets.QLabel("Tunable Beam")
        tunable_label.setAlignment(QtCore.Qt.AlignCenter)
        self.tunable_indicator = QtWidgets.QLabel()
        self.tunable_indicator.setFixedSize(15, 15)
        self.tunable_indicator.setStyleSheet("background-color: gray; border-radius: 7px;")
        tunable_layout.addWidget(self.tunable_indicator, 0, QtCore.Qt.AlignCenter)
        tunable_layout.addWidget(tunable_label)

        # Tunable shutter slider
        self.tunable_shutter = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.tunable_shutter.setRange(0, 1)
        self.tunable_shutter.setSingleStep(1)
        self.tunable_shutter.setFixedWidth(50)
        self.tunable_shutter.valueChanged.connect(self.toggle_tunable_shutter)
        tunable_layout.addWidget(self.tunable_shutter, 0, QtCore.Qt.AlignCenter)
        status_layout.addLayout(tunable_layout)

        # Vertical separator
        line2 = QtWidgets.QFrame()
        line2.setFrameShape(QtWidgets.QFrame.VLine)
        line2.setFrameShadow(QtWidgets.QFrame.Sunken)
        status_layout.addWidget(line2)

        # Fixed beam section
        fixed_layout = QtWidgets.QVBoxLayout()
        fixed_label = QtWidgets.QLabel("Fixed Beam")
        fixed_label.setAlignment(QtCore.Qt.AlignCenter)
        self.fixed_indicator = QtWidgets.QLabel()
        self.fixed_indicator.setFixedSize(15, 15)
        self.fixed_indicator.setStyleSheet("background-color: gray; border-radius: 7px;")
        fixed_layout.addWidget(self.fixed_indicator, 0, QtCore.Qt.AlignCenter)
        fixed_layout.addWidget(fixed_label)

        # Fixed shutter slider
        self.fixed_shutter = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.fixed_shutter.setRange(0, 1)
        self.fixed_shutter.setSingleStep(1)
        self.fixed_shutter.setFixedWidth(50)
        self.fixed_shutter.valueChanged.connect(self.toggle_fixed_shutter)
        fixed_layout.addWidget(self.fixed_shutter, 0, QtCore.Qt.AlignCenter)
        status_layout.addLayout(fixed_layout)

        main_layout.addLayout(status_layout)

        # Add separator
        hline = QtWidgets.QFrame()
        hline.setFrameShape(QtWidgets.QFrame.HLine)
        hline.setFrameShadow(QtWidgets.QFrame.Sunken)
        main_layout.addWidget(hline)

        # Wavelength and energy information
        param_layout = QtWidgets.QFormLayout()

        # Wavelength display and control
        wave_layout = QtWidgets.QHBoxLayout()
        self.display_nm = QtWidgets.QLineEdit()
        self.display_nm.setReadOnly(True)
        self.display_nm.setFixedWidth(100)
        wave_layout.addWidget(self.display_nm)

        # Quick adjust buttons for wavelength
        self.wave_down = QtWidgets.QPushButton("-")
        self.wave_down.setFixedWidth(25)
        self.wave_down.clicked.connect(lambda: self.adjust_wavelength(-1))
        wave_layout.addWidget(self.wave_down)

        self.wave_up = QtWidgets.QPushButton("+")
        self.wave_up.setFixedWidth(25)
        self.wave_up.clicked.connect(lambda: self.adjust_wavelength(1))
        wave_layout.addWidget(self.wave_up)

        param_layout.addRow("Wavelength (air):", wave_layout)

        # Energy display
        self.display_energy = QtWidgets.QLineEdit()
        self.display_energy.setReadOnly(True)
        self.display_energy.setFixedWidth(100)
        param_layout.addRow("Photon energy:", self.display_energy)

        # Power display for tunable beam
        self.display_power_tunable = QtWidgets.QLineEdit()
        self.display_power_tunable.setReadOnly(True)
        self.display_power_tunable.setFixedWidth(100)
        param_layout.addRow("Tunable power:", self.display_power_tunable)

        main_layout.addLayout(param_layout)

        # Button row for additional functions
        button_layout = QtWidgets.QHBoxLayout()

        # Advanced controls button
        advanced_button = QtWidgets.QPushButton("ADVANCED")
        advanced_button.clicked.connect(self.show_advanced_controls)
        button_layout.addWidget(advanced_button)

        main_layout.addLayout(button_layout)

        # Set main layout
        widget.setLayout(main_layout)
        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)

        if menu:
            menu.addAction(dock.toggleViewAction())

        # Initialize the widget operation
        self.createListenerThread(self.updateSlot)

        # Setup mouse events for direct input
        self.display_nm.mousePressEvent = self.on_click_nm
        self.display_energy.mousePressEvent = self.on_click_energy

    def on_click_nm(self, event):
        """Handle mouse click on wavelength display"""
        try:
            if event.button() == 1:
                current = self.wavelength()
                d, okPressed = QtWidgets.QInputDialog.getDouble(
                    self.display_nm.parent(),
                    "Set wavelength",
                    "Target wavelength (air) in nm:",
                    current, 680, 900, 3)
                if okPressed:
                    self.set_wavelength(d)
        except Exception as e:
            print(f"Error setting wavelength: {e}")

    def on_click_energy(self, event):
        """Handle mouse click on energy display"""
        try:
            if event.button() == 1:
                current = H_C*N_AIR / self.wavelength()*1000
                d, okPressed = QtWidgets.QInputDialog.getDouble(
                    self.display_energy.parent(),
                    "Set energy",
                    "Target energy in meV:",
                    current, 1300, 1900, 3)
                if okPressed:
                    self.set_wavelength(H_C*N_AIR*1000/ d)
        except Exception as e:
            print(f"Error setting energy: {e}")

    def adjust_wavelength(self, delta):
        """Adjust wavelength by a small increment"""
        try:
            current = self.wavelength()
            self.set_wavelength(current + delta)
        except Exception as e:
            print(f"Error adjusting wavelength: {e}")

    def toggle_laser(self):
        """Toggle the laser on/off state"""
        try:
            if self.laser_toggle.isChecked():
                self.set_laser_state(True)
                self.laser_toggle.setText("ON")
            else:
                self.set_laser_state(False)
                self.laser_toggle.setText("OFF")
        except Exception as e:
            print(f"Error toggling laser: {e}")
            # Reset button state if there was an error
            self.laser_toggle.setChecked(self.is_lasing())

    def toggle_tunable_shutter(self):
        """Toggle the tunable beam shutter"""
        try:
            if self.tunable_shutter.value() == 1:
                self.open_shutter_tunable(True)
            else:
                self.close_shutter_tunable()
        except Exception as e:
            print(f"Error toggling tunable shutter: {e}")
            # Reset slider state if there was an error
            self.tunable_shutter.setValue(1 if self.is_shutter_open_tunable() else 0)

    def toggle_fixed_shutter(self):
        """Toggle the fixed beam shutter"""
        try:
            if self.fixed_shutter.value() == 1:
                self.open_shutter_fixed(True)
            else:
                self.close_shutter_fixed()
        except Exception as e:
            print(f"Error toggling fixed shutter: {e}")
            # Reset slider state if there was an error
            self.fixed_shutter.setValue(1 if self.is_shutter_open_fixed() else 0)

    def updateSlot(self, status):
        """Update the GUI based on the current laser status"""
        try:
            # Update wavelength and energy displays
            self.display_nm.setText(f"{status['tunable']['wavelength']:.3f} nm")
            photon_energy = H_C*N_AIR*1000/status['tunable']['wavelength']
            self.display_energy.setText(f"{photon_energy:.3f} meV")

            # Update power display
            self.display_power_tunable.setText(f"{status['tunable']['power']} mW")

            # Update lasing indicator
            if status['lasing']:
                self.lasing_indicator.setStyleSheet("background-color: green; border-radius: 7px;")
                if not self.laser_toggle.isChecked():
                    self.laser_toggle.setChecked(True)
                    self.laser_toggle.setText("ON")
            else:
                self.lasing_indicator.setStyleSheet("background-color: red; border-radius: 7px;")
                if self.laser_toggle.isChecked():
                    self.laser_toggle.setChecked(False)
                    self.laser_toggle.setText("OFF")

            # Update tunable beam indicator and slider
            if status['tunable']['shutter']:
                self.tunable_indicator.setStyleSheet("background-color: green; border-radius: 7px;")
                if self.tunable_shutter.value() != 1:
                    self.tunable_shutter.setValue(1)
            else:
                self.tunable_indicator.setStyleSheet("background-color: red; border-radius: 7px;")
                if self.tunable_shutter.value() != 0:
                    self.tunable_shutter.setValue(0)

            # Update fixed beam indicator (we need to add this to status in worker)
            fixed_shutter_open = self.is_shutter_open_fixed()
            if fixed_shutter_open:
                self.fixed_indicator.setStyleSheet("background-color: green; border-radius: 7px;")
                if self.fixed_shutter.value() != 1:
                    self.fixed_shutter.setValue(1)
            else:
                self.fixed_indicator.setStyleSheet("background-color: red; border-radius: 7px;")
                if self.fixed_shutter.value() != 0:
                    self.fixed_shutter.setValue(0)

        except Exception as e:
            print(f"Error updating GUI: {e}")

    def show_advanced_controls(self):
        """Show dialog with advanced controls"""
        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle("Advanced Laser Controls")
        dialog.setMinimumWidth(400)

        layout = QtWidgets.QVBoxLayout(dialog)

        # Group box for detailed wavelength control
        wave_group = QtWidgets.QGroupBox("Wavelength Control")
        wave_layout = QtWidgets.QFormLayout()

        current_wave = self.wavelength()

        # Wavelength presets
        preset_layout = QtWidgets.QHBoxLayout()
        preset_label = QtWidgets.QLabel("Presets:")
        preset_layout.addWidget(preset_label)

        presets = [700, 750, 800, 850, 900]
        for preset in presets:
            preset_btn = QtWidgets.QPushButton(f"{preset}")
            preset_btn.setFixedWidth(50)
            preset_btn.clicked.connect(lambda checked, p=preset: self.set_wavelength(p))
            preset_layout.addWidget(preset_btn)

        wave_layout.addRow(preset_layout)

        # Fine adjustment
        fine_layout = QtWidgets.QHBoxLayout()

        # Slider for fine adjustment
        self.fine_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.fine_slider.setRange(int(current_wave)-10, int(current_wave)+10)
        self.fine_slider.setValue(int(current_wave))
        self.fine_slider.valueChanged.connect(lambda v: self.set_wavelength(v))

        self.fine_display = QtWidgets.QLabel(f"{current_wave:.1f} nm")

        fine_layout.addWidget(QtWidgets.QLabel("Fine adjust:"))
        fine_layout.addWidget(self.fine_slider)
        fine_layout.addWidget(self.fine_display)

        wave_layout.addRow(fine_layout)
        wave_group.setLayout(wave_layout)
        layout.addWidget(wave_group)

        # Group box for shutter controls with safety features
        shutter_group = QtWidgets.QGroupBox("Shutter Control")
        shutter_layout = QtWidgets.QGridLayout()

        # Tunable beam controls
        shutter_layout.addWidget(QtWidgets.QLabel("Tunable Beam:"), 0, 0)

        # Safety switch for tunable beam
        self.tunable_safety = QtWidgets.QCheckBox("Safety")
        self.tunable_safety.setChecked(True)
        shutter_layout.addWidget(self.tunable_safety, 0, 1)

        # Open/close buttons for tunable
        tunable_open = QtWidgets.QPushButton("Open")
        tunable_open.clicked.connect(lambda: self.open_shutter_with_safety("tunable"))
        shutter_layout.addWidget(tunable_open, 0, 2)

        tunable_close = QtWidgets.QPushButton("Close")
        tunable_close.clicked.connect(self.close_shutter_tunable)
        shutter_layout.addWidget(tunable_close, 0, 3)

        # Fixed beam controls
        shutter_layout.addWidget(QtWidgets.QLabel("Fixed Beam:"), 1, 0)

        # Safety switch for fixed beam
        self.fixed_safety = QtWidgets.QCheckBox("Safety")
        self.fixed_safety.setChecked(True)
        shutter_layout.addWidget(self.fixed_safety, 1, 1)

        # Open/close buttons for fixed
        fixed_open = QtWidgets.QPushButton("Open")
        fixed_open.clicked.connect(lambda: self.open_shutter_with_safety("fixed"))
        shutter_layout.addWidget(fixed_open, 1, 2)

        fixed_close = QtWidgets.QPushButton("Close")
        fixed_close.clicked.connect(self.close_shutter_fixed)
        shutter_layout.addWidget(fixed_close, 1, 3)

        # Emergency close all shutters
        close_all = QtWidgets.QPushButton("CLOSE ALL SHUTTERS")
        close_all.setStyleSheet("background-color: red; color: white; font-weight: bold;")
        close_all.clicked.connect(self.close_all_shutters)
        shutter_layout.addWidget(close_all, 2, 0, 1, 4)

        shutter_group.setLayout(shutter_layout)
        layout.addWidget(shutter_group)

        # Status information
        status_group = QtWidgets.QGroupBox("Status Information")
        status_layout = QtWidgets.QFormLayout()

        # Additional status information
        self.detailed_power = QtWidgets.QLineEdit()
        self.detailed_power.setReadOnly(True)
        status_layout.addRow("Current Power:", self.detailed_power)

        self.laser_status = QtWidgets.QLineEdit()
        self.laser_status.setReadOnly(True)
        status_layout.addRow("Laser Status:", self.laser_status)

        # Update status immediately
        self.detailed_power.setText(f"{self.power_tunable()} mW")
        self.laser_status.setText("Active" if self.is_lasing() else "Inactive")

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Close button
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Update fine adjustment display when slider changes
        def update_fine_display():
            self.fine_display.setText(f"{self.fine_slider.value():.1f} nm")

        self.fine_slider.valueChanged.connect(update_fine_display)

        dialog.setModal(False)
        dialog.show()

    def open_shutter_with_safety(self, beam_type):
        """Open shutter with safety confirmation if safety is enabled"""
        try:
            if beam_type == "tunable" and self.tunable_safety.isChecked():
                reply = QtWidgets.QMessageBox.question(
                    None,
                    'Safety Confirmation',
                    'Are you sure you want to open the tunable beam shutter?',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    self.open_shutter_tunable(True)
            elif beam_type == "fixed" and self.fixed_safety.isChecked():
                reply = QtWidgets.QMessageBox.question(
                    None,
                    'Safety Confirmation',
                    'Are you sure you want to open the fixed beam shutter?',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    self.open_shutter_fixed(True)
            elif beam_type == "tunable":
                self.open_shutter_tunable(True)
            elif beam_type == "fixed":
                self.open_shutter_fixed(True)
        except Exception as e:
            print(f"Error opening shutter: {e}")

    def close_all_shutters(self):
        """Emergency function to close all shutters"""
        try:
            self.close_shutter_tunable()
            self.close_shutter_fixed()
            QtWidgets.QMessageBox.information(
                None,
                'Shutters Closed',
                'All shutters have been closed.',
                QtWidgets.QMessageBox.Ok
            )
        except Exception as e:
            print(f"Error closing shutters: {e}")
