# -*- coding: utf-8 -*-


import time

from PyQt5 import QtCore, QtWidgets

from devices import Parameter
from devices.axis import Axis
from devices.zeromq_device import (
    DeviceOverZeroMQ,
    DeviceWorker,
    include_remote_methods,
    remote,
)

default_req_port = 7008
default_pub_port = 7009


class APTParameter(Parameter):
    def __init__(self, apt, motor_number):
        self.apt = apt
        self.motor_serial = motor_number

    def name(self):
        return "APT motor, s/n: %d" % self.motor_serial

    def value(self):
        return self.apt.get_position(self.motor_serial)

    def move_to_target(self, target):
        self.apt.move_absolute(self.motor_serial, target)

    def move_continuous(self, rate):
        self.apt.move_velocity(self.motor_serial, rate)

    def is_moving(self):
        return not self.apt.is_stopped()


class APTWorker(DeviceWorker):
    """Class managing all Thorlabs APT  motor controllers"""

    def __init__(self, req_port=default_req_port, pub_port=default_pub_port, **kwargs):
        super().__init__(req_port=req_port, pub_port=pub_port, **kwargs)
        self.motors = {}

    def init_device(self):
        from . import apt_wrapper

        serials = [n for (t, n) in apt_wrapper.list_available_devices()]
        print("%d APT devices found" % len(serials))
        for n in serials:
            print("SN: %d" % n)
            mot = apt_wrapper.Motor(n)
            mot.acceleration = 5
            mot.initial_parameters = mot.get_velocity_parameters()
            mot.prev_request_time = time.time()
            self.motors[n] = mot

    min_request_delay = 0.05

    def wait(self, motor):
        now = time.time()
        elapsed = now - motor.prev_request_time
        if elapsed > 0 and elapsed < self.min_request_delay:
            time.sleep(self.min_request_delay - elapsed)
        motor.prev_request_time = now

    def status(self):
        d = super().status()
        d["apt_devices"] = self.devices()
        for sn in self.motors:
            motor = self.motors[sn]
            self.wait(motor)
            d["apt_{0}".format(sn)] = {
                "position": motor.position,
                "stopped": not motor.is_in_motion,
                "homed": motor.has_homing_been_completed,
            }
        return d

    @remote
    def move_absolute(self, serial, target):
        mot = self.motors[serial]
        self.wait(mot)
        mot.set_velocity_parameters(*mot.initial_parameters)
        mot.move_to(target)

    @remote
    def devices(self):
        return [sn for sn in self.motors]

    @remote
    def axes(self):
        return self.devices()

    @remote
    def move_velocity(self, serial, velocity):
        if velocity == 0:
            return self.stop(serial)
        """ velocity should be between -1 to 1 """
        mot = self.motors[serial]
        self.wait(mot)
        mot.maximum_velocity = abs(velocity) * mot.initial_parameters[2]
        direction = 1 if velocity > 0 else 2
        mot.move_velocity(direction)

    @remote
    def stop(self, serial):
        mot = self.motors[serial]
        self.wait(mot)
        mot.set_velocity_parameters(*mot.initial_parameters)
        mot.stop_profiled()

    @remote
    def get_position(self, serial):
        mot = self.motors[serial]
        self.wait(mot)
        return mot.position

    @remote
    def is_stopped(self, serial):
        mot = self.motors[serial]
        return not mot.is_in_motion

    @remote
    def homed(self, serial):
        mot = self.motors[serial]
        return mot.homed()

    @remote
    def home(self, serial):
        mot = self.motors[serial]
        mot.move_home(blocking=False)

    @remote
    def get_name(self, axis):  # TODO: read axis names from config file like in stepper
        try:
            return self.axis_names[self.axis_by_name[axis]]
        except:
            return str(axis)


@include_remote_methods(APTWorker)
class APT(DeviceOverZeroMQ):
    def __init__(
        self,
        req_port=default_req_port,
        pub_port=default_pub_port,
        display_decimal_places=1,
        **kwargs,
    ):
        super().__init__(req_port=req_port, pub_port=pub_port, **kwargs)
        # custom initialization here
        self.widgets = {}
        try:
            self._display_fmt = "%." + str(display_decimal_places) + "f"
            self._display_fmt % 0.5  # raises exception if the format is incorrect
        except:
            self._display_fmt = "%.1f"
        self._display_decimal_places = int(display_decimal_places)

    def get_axis(self, axis):
        return Axis(self, axis)

    def createDock(self, parentWidget, menu=None):
        """Function for integration in GUI app."""
        dock = QtWidgets.QDockWidget("Thorlabs APT", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        self.layout = QtWidgets.QVBoxLayout(parentWidget)
        widget.setLayout(self.layout)
        dock.setWidget(widget)
        dock.setAllowedAreas(
            QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea
        )
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        self.createListenerThread(self.updateSlot)

    def appendRow(self, serial):
        hlayout = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(f"{serial}")
        hlayout.addWidget(label)
        display = QtWidgets.QLCDNumber()
        display.setSegmentStyle(QtWidgets.QLCDNumber.Flat)
        display.setDigitCount(len(self._display_fmt % 360))
        display.display("-")
        hlayout.addWidget(display)

        home_button = QtWidgets.QPushButton("Home")
        home_button.setFixedWidth(50)

        def home_clicked():
            self.home(serial)

        home_button.clicked.connect(home_clicked)
        hlayout.addWidget(home_button)

        hlayout.addStretch(3)
        self.layout.addLayout(hlayout)
        self.widgets[serial] = (display, home_button)

        def on_click(event):
            if event.button() == 1:
                current = self.get_position(serial)
                d, okPressed = QtWidgets.QInputDialog.getDouble(
                    display,
                    "Go to",
                    "Target:",
                    current,
                    -360,
                    360,
                    decimals=self._display_decimal_places,
                )
                if okPressed:
                    self.move_absolute(serial, d)

        display.mousePressEvent = on_click

    def updateSlot(self, status):
        for serial in status["apt_devices"]:
            if serial not in self.widgets:
                self.appendRow(serial)
            motor_status = status["apt_{0}".format(serial)]
            self.widgets[serial][0].display(
                self._display_fmt % motor_status["position"]
            )
            if motor_status["homed"]:
                self.widgets[serial][1].setText("Homed")
            else:
                self.widgets[serial][1].setText("Home")

    def get_parameters(self):
        return [APTParameter(self, serial) for serial in self.devices()]
