# -*- coding: utf-8 -*-
from devices.zeromq_device import DeviceWorker,DeviceOverZeroMQ,remote,include_remote_methods
from PyQt5 import QtWidgets,QtCore
from PyQt5.QtWidgets import (QPushButton, QMessageBox, QDialog)
from PyQt5.QtWidgets import (QApplication, QWidget, QMainWindow)
from PyQt5.QtWidgets import (QVBoxLayout, QHBoxLayout, QLineEdit)
from PyQt5.QtWidgets import (QLabel, QInputDialog)
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
                             
    def createDock(self, parentWidget, menu=None):
        """ Function for integration in GUI app. Implementation below 
        creates a button and a display """
        dock = QtWidgets.QDockWidget("Chameleon laser", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        
        layout_form = QtWidgets.QFormLayout()
        self.display_nm = QtWidgets.QLineEdit()
        self.display_nm.setReadOnly(True)
        layout_form.addRow("Wavelength (air)", self.display_nm)
        self.display_energy = QtWidgets.QLineEdit()
        self.display_energy.setReadOnly(True)
        layout_form.addRow("Photon energy", self.display_energy)
        
        def on_click_nm(event):
            try:
                if event.button() == 1:
                    current = self.get_wavelength()
                    d, okPressed = QtWidgets.QInputDialog.getDouble(parentWidget, "Set wavelength", "Target wavelength (air) in nm:", current, 680, 900)
                    if okPressed:
                        self.set_wavelength(d)
            except:
                pass
        self.display_nm.mousePressEvent  = on_click_nm
        
        def on_click_energy(event):
            try:
                if event.button() == 1:
                    current = H_C*N_AIR / self.get_wavelength()*1000
                    print(current)
                    d, okPressed = QtWidgets.QInputDialog.getDouble(parentWidget, "Set energy", "Target energy in meV:", current, 1300, 1900)
                    if okPressed:
                        self.set_wavelength(H_C*N_AIR*1000/ d)
            except:
                pass
        self.display_energy.mousePressEvent  = on_click_energy
        
        button = QtWidgets.QPushButton("Calibrate")
        button.clicked.connect(self.show_calibration_window)
        layout_form.addRow(button)
        
        widget.setLayout(layout_form)
        
        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())
            
        # Following lines "turn on" the widget operation
        self.createListenerThread(self.updateSlot)

        
    def updateSlot(self, status):
        try:
            self.display_nm.setText("%.3f nm" % status["wavelength"])
            self.display_energy.setText("%.3f meV" % (H_C*N_AIR*1000/status["wavelength"]))
        except:
            pass

            
    def show_calibration_window(self):
        ''' Displays a window with several calibration options '''
        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle("Calibrate Ti:Sapphire laser")
        layout = QtWidgets.QFormLayout(dialog)
        dialog.setLayout(layout)
        
        option1 = QtWidgets.QRadioButton("Auto-calibration using wavemeter")
        layout.addRow(option1)
        
        edit_wavemeter = QtWidgets.QLineEdit("wavemeter")
        label = QtWidgets.QLabel("Wavemeter id")
        layout.addRow(label, edit_wavemeter)
        option1.toggled.connect(edit_wavemeter.setEnabled)
        option1.toggled.connect(label.setEnabled)
        option1.setChecked(True)
        
        option2 = QtWidgets.QRadioButton("Specify current wavelength")
        layout.addRow(option2)
        edit_wavelength = QtWidgets.QLineEdit()
        edit_wavelength.setPlaceholderText("Enter wavelength in nm")
        label = QtWidgets.QLabel("Current wavelength")
        layout.addRow(label, edit_wavelength)
        option2.toggled.connect(edit_wavelength.setEnabled)
        option2.toggled.connect(label.setEnabled)
        edit_wavelength.setEnabled(False)
        label.setEnabled(False)
        
        buttonBox = QtWidgets.QDialogButtonBox(dialog)
        buttonBox.setOrientation(QtCore.Qt.Horizontal)
        buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(dialog.accept)
        buttonBox.rejected.connect(dialog.reject)
        layout.addRow(buttonBox)
        dialog.setModal(True)
        dialog.show()
        
        if dialog.exec_():
            if option1.isChecked():
                try:
                    self.perform_wavemeter_calibration(edit_wavemeter.text())
                except:
                    pass
            elif option2.isChecked():
                try:
                    self.calibrate(float(edit_wavelength.text()))
                except:
                    pass
        
    def perform_wavemeter_calibration(self, wavemeter_id):
        ''' Display a dialog with wavemeter calibration '''
        wavemeter = devices.active_devices[wavemeter_id]
        