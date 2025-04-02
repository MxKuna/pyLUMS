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
        self.states = []
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

    def status(self):
        d = super().status()
        for axis in [1, 2, 3, 4]:
            d[f"open{axis}"] = self.shutter_state(axis)
        # print(d)
        return d

    @remote
    def shutter_state(self, ax):
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
    def move_shutter(self, action, *axes):
        letters = [['q', 'a', 'z'], ['w', 's', 'x'], ['e', 'd', 'c'], ['r', 'f', 'v']]

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


@include_remote_methods(ShutterWorker)
class Shutter(DeviceOverZeroMQ):
    status_updated = QtCore.pyqtSignal(dict)  # Add signal for status updates

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_interval = 500
        self._update_timer = None

    def _generate_func(self, number):
        def change_shutter_state(on):
            if on:
                self.move_shutter('w_open', number)
                self.update_status()
                self.update_ui()
            else:
                self.move_shutter('close', number)
                self.update_status()
                self.update_ui()
        return change_shutter_state

    def update_status(self):
        status = self.status()
        self.update_ui(status)

    def update_ui(self, status):
        for axis in [1, 2, 3, 4]:
            try:
                state_key = f"open{axis}"
                if state_key in status:
                    if status[state_key]:
                        self.buttons[axis].setText(f"Servo {axis} - OPEN")
                    else:
                        self.buttons[axis].setText(f"Servo {axis} - CLOSED")
            except Exception as e:
                print(f"Error updating status for axis {axis}: {e}")
                self.buttons[axis].setText(f"Servo {axis} - ERROR")

    def createDock(self, parentWidget, menu=None):
        dock = QtWidgets.QDockWidget("ServoShutter", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        layout = QtWidgets.QVBoxLayout()
        widget.setLayout(layout)

        self.buttons = {}

        for axis in [1, 2, 3, 4]:
            button = QtWidgets.QPushButton(f"Servo {axis} - Unknown")
            button.setCheckable(True)
            button.clicked.connect(self._generate_func(axis))
            self.buttons[axis] = button
            layout.addWidget(button)

        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        # Setup timer for status updates
        # self._update_timer = QtCore.QTimer()
        # self._update_timer.timeout.connect(self.update_status)
        # self._update_timer.start(self._update_interval)
