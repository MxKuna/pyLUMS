import serial
import serial.tools.list_ports
import threading
from time import sleep
from PyQt5 import QtWidgets, QtCore

from devices.zeromq_device import DeviceWorker, DeviceOverZeroMQ, remote, include_remote_methods

class ShutterWorker(DeviceWorker):
    def __init__(self, *args, hwid="SER=066EFF343433464757222518", com=None, baud=115200, **kwargs):
        super().__init__(*args, **kwargs)
        self.baud = baud
        self.com = com
        self.hwid = hwid
        self._connected = False
        self._command_lock = threading.Lock()

    def init_device(self):
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            if port.vid and port.hwid:
                if port.hwid.__contains__(self.hwid):
                    self.com = port.device
                    self.comp = serial.Serial(self.com, self.baud, timeout=0.2)
                    self.comp.reset_input_buffer()
                    print("Device initialized on:", self.comp.name)
                    self._connected = False

    def status(self):
        d = super().status()
        for axis in [1, 2, 3, 4]:
            d[f"open{axis}"] = self.state(axis)
        # print(d)
        return d

    @remote
    def state(self, ax):
        with self._command_lock:
            self.comp.reset_input_buffer()
            pos = f'?{ax}'
            self.comp.write(pos.encode('ascii'))
            self.comp.flush()
            odp = self.comp.readline().strip()

            try:
                decoded = odp.decode('ascii', errors='replace')
                # print(f"{decoded}")

                try:
                    odp_ax = int(decoded[0:1])
                    if ax != odp_ax:
                        print(f"Error: Requested axis {ax}, received axis {odp_ax}")
                        return False
                    return int(decoded[2:7]) > 1100
                except:
                    return False

            except Exception as e:
                print(f"Decode Error: {e}, Raw Bytes: {odp}")
                return False

    @remote
    def move(self, action, *axes):
        letters = [['q', 'a', 'z'], ['w', 's', 'x'], ['e', 'd', 'c'], ['r', 'f', 'v']]

        try:
            with self._command_lock:
                for ax in axes:
                    match action:
                        case 'close':
                            pos = letters[ax - 1][0]
                        case 'open':
                            pos = letters[ax - 1][1]
                        case 'w_open':
                            pos = letters[ax - 1][2]
                        case _:
                            print("Invalid action: Use 'open', 'close', or 'w_open'")
                            break

                    self.comp.reset_input_buffer()
                    self.comp.write(pos.encode('ascii'))
                    self.comp.flush()
        except Exception as e:
            print(f"error on moving shutter: {e}")
            
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
                self.checkboxes.setChecked(False)
                

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
            label = QtWidgets.QLabel(f"Servo {axis}")
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
            checkbox = QtWidgets.QCheckBox("Hide")
            checkbox.setChecked(True)  # Default to enabled
            checkbox.stateChanged.connect(lambda state, btn=button: btn.setEnabled(state == QtCore.Qt.Checked))
            checkbox.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
            self.checkboxes[axis] = checkbox
            row_layout.addWidget(checkbox)
            
            # Add the row to the main layout with stretch factor
            layout.addLayout(row_layout, 1)  # The 1 gives it a stretch factor

        # Add a stretch at the end to push all rows to the top when resizing
        layout.addStretch()
        
        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())
            
        self.createListenerThread(self.update_ui)
