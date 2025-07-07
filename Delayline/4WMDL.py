# -*- coding: utf-8 -*-

import time

from PyQt5 import QtCore, QtWidgets

from devices.thorlabs.apt import APTWorker, APTParameter
from devices.axis import Axis
from devices.zeromq_device import (
    DeviceOverZeroMQ,
    include_remote_methods,
)

default_req_port = 7008
default_pub_port = 7009


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
        self.zero_positions = {}  # Store custom zero positions for each motor
        self.hardcoded_delaylines = [104351285, 104351286, 104351287]  # Replace with your actual IDs

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
        dock = QtWidgets.QDockWidget("Thorlabs APT Delay Lines", parentWidget)
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

    def mm_to_picoseconds(self, mm):
        """Convert mm to picoseconds (c = 299792458 m/s, round trip)"""
        return (mm / 1000) * 2 / 299792458 * 1e12

    def picoseconds_to_mm(self, ps):
        """Convert picoseconds to mm (c = 299792458 m/s, round trip)"""
        return (ps * 1e-12 * 299792458 / 2) * 1000

    def appendRow(self, serial):
        # Main container for this motor
        main_frame = QtWidgets.QFrame()
        main_frame.setFrameStyle(QtWidgets.QFrame.Box)
        main_layout = QtWidgets.QVBoxLayout(main_frame)

        # Row 1: Position display, status indicator, homing button
        row1 = QtWidgets.QHBoxLayout()

        # Motor label
        label = QtWidgets.QLabel(f"DL {serial}")
        label.setFixedWidth(80)
        row1.addWidget(label)

        # Position display
        pos_display = QtWidgets.QLCDNumber()
        pos_display.setSegmentStyle(QtWidgets.QLCDNumber.Flat)
        pos_display.setDigitCount(8)
        pos_display.display("-")
        pos_display.setFixedHeight(30)
        row1.addWidget(pos_display)

        # Status indicator
        status_label = QtWidgets.QLabel("STOPPED")
        status_label.setFixedWidth(80)
        status_label.setStyleSheet("background-color: green; color: white; padding: 5px; border-radius: 3px;")
        row1.addWidget(status_label)

        # Homing button
        home_button = QtWidgets.QPushButton("Home")
        home_button.setFixedWidth(60)
        home_button.clicked.connect(lambda: self.home(serial))
        row1.addWidget(home_button)

        # Set zero button
        set_zero_button = QtWidgets.QPushButton("Set Zero")
        set_zero_button.setFixedWidth(70)
        set_zero_button.clicked.connect(lambda: self.set_zero_position(serial))
        row1.addWidget(set_zero_button)

        # Zero position display
        zero_display = QtWidgets.QLabel("not set")
        zero_display.setFixedWidth(80)
        zero_display.setStyleSheet("background-color: lightgray; padding: 2px; border: 1px solid gray;")
        row1.addWidget(zero_display)

        main_layout.addLayout(row1)

        # Row 2: Control inputs
        row2 = QtWidgets.QHBoxLayout()

        # Absolute position control
        abs_label = QtWidgets.QLabel("Abs (mm):")
        abs_label.setFixedWidth(60)
        row2.addWidget(abs_label)

        abs_input = QtWidgets.QDoubleSpinBox()
        abs_input.setRange(-1000, 1000)
        abs_input.setDecimals(3)
        abs_input.setFixedWidth(100)
        # Move to position and clear field when ENTER is pressed or focus is lost
        def abs_input_finished():
            if abs_input.value() != 0:  # Only move if value is not zero
                self.move_absolute(serial, abs_input.value())
            abs_input.clear()
        abs_input.editingFinished.connect(abs_input_finished)
        row2.addWidget(abs_input)

        abs_go_button = QtWidgets.QPushButton("Go")
        abs_go_button.setFixedWidth(40)
        abs_go_button.clicked.connect(lambda: self.move_absolute(serial, abs_input.value()))
        row2.addWidget(abs_go_button)

        # Spacer
        row2.addItem(QtWidgets.QSpacerItem(20, 0, QtWidgets.QSizePolicy.Fixed))

        # Relative position control (picoseconds)
        rel_label = QtWidgets.QLabel("Rel (ps):")
        rel_label.setFixedWidth(60)
        row2.addWidget(rel_label)

        rel_input = QtWidgets.QDoubleSpinBox()
        rel_input.setRange(-10000, 10000)
        rel_input.setDecimals(1)
        rel_input.setSuffix(" ps")
        rel_input.setFixedWidth(100)
        row2.addWidget(rel_input)

        rel_go_button = QtWidgets.QPushButton("Go")
        rel_go_button.setFixedWidth(40)
        rel_go_button.clicked.connect(lambda: self.move_relative_picoseconds(serial, rel_input.value()))
        row2.addWidget(rel_go_button)

        # Spacer
        row2.addItem(QtWidgets.QSpacerItem(20, 0, QtWidgets.QSizePolicy.Fixed))

        # Add stretch before delay display to push it to the right
        row2.addStretch()

        # Delay display (right-aligned)
        delay_label = QtWidgets.QLabel("Delay:")
        delay_label.setFixedWidth(50)
        row2.addWidget(delay_label)

        delay_display = QtWidgets.QLabel("-- ps")
        delay_display.setFixedWidth(80)
        delay_display.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        delay_display.setStyleSheet("background-color: lightyellow; padding: 2px; border: 1px solid orange;")
        row2.addWidget(delay_display)
        main_layout.addLayout(row2)

        self.layout.addWidget(main_frame)

        # Store widget references
        self.widgets[serial] = {
            'pos_display': pos_display,
            'status_label': status_label,
            'home_button': home_button,
            'zero_display': zero_display,
            'delay_display': delay_display,
            'abs_input': abs_input,
            'rel_input': rel_input
        }

        # Initialize zero position if not set
        if serial not in self.zero_positions:
            self.zero_positions[serial] = None

    def set_zero_position(self, serial):
        """Set current position as new zero reference"""
        current_pos = self.get_position(serial)
        self.zero_positions[serial] = current_pos
        self.update_zero_display(serial)

    def update_zero_display(self, serial):
        """Update the zero position display"""
        if serial in self.widgets:
            zero_display = self.widgets[serial]['zero_display']
            if self.zero_positions[serial] is not None:
                zero_display.setText(f"{self.zero_positions[serial]:.3f} mm")
                zero_display.setStyleSheet("background-color: blue; padding: 2px; border: 1px solid blue;")
            else:
                zero_display.setText("not set")
                zero_display.setStyleSheet("background-color: lightgray; padding: 2px; border: 1px solid gray;")

    def move_relative_picoseconds(self, serial, picoseconds):
        """Move relative to set zero position, specified in picoseconds"""
        if self.zero_positions[serial] is None:
            QtWidgets.QMessageBox.warning(None, "Warning", "Zero position not set for this motor!")
            return

        # Convert picoseconds to mm displacement
        mm_displacement = self.picoseconds_to_mm(picoseconds)
        target_position = self.zero_positions[serial] + mm_displacement

        self.move_absolute(serial, target_position)

    def updateSlot(self, status):
        # Create widgets for hardcoded delay lines if they exist
        available_devices = status.get("apt_devices", [])
        for serial in self.hardcoded_delaylines:
            if serial in available_devices and serial not in self.widgets:
                self.appendRow(serial)

        # Update existing widgets
        for serial in self.widgets:
            if serial in available_devices:
                motor_status = status.get("apt_{0}".format(serial), {})
                widgets = self.widgets[serial]

                # Update position display
                position = motor_status.get("position", 0)
                widgets['pos_display'].display(f"{position:.3f}")

                # Update status indicator
                if motor_status.get("stopped", True):
                    widgets['status_label'].setText("STOPPED")
                    widgets['status_label'].setStyleSheet("background-color: green; color: white; padding: 4px; border-radius: 5px;")
                else:
                    widgets['status_label'].setText("MOVING")
                    widgets['status_label'].setStyleSheet("background-color: red; color: white; padding: 4px; border-radius: 5px;")

                # Update homing button
                is_homed = motor_status.get("homed", False)
                widgets['home_button'].setEnabled(not is_homed)
                if is_homed:
                    widgets['home_button'].setText("Homed")
                else:
                    widgets['home_button'].setText("Home")

                # Keep absolute position input empty for easier typing
                # (no need to update with current position)

                # Update zero display
                self.update_zero_display(serial)

                # Update delay display
                self.update_delay_display(serial, position)

    def update_delay_display(self, serial, current_position):
        """Update the delay display showing picoseconds relative to zero"""
        if serial in self.widgets:
            delay_display = self.widgets[serial]['delay_display']
            if self.zero_positions[serial] is not None:
                # Calculate delay in mm relative to zero
                delay_mm = current_position - self.zero_positions[serial]
                # Convert to picoseconds
                delay_ps = self.mm_to_picoseconds(delay_mm)
                delay_display.setText(f"{delay_ps:.1f} ps")
                delay_display.setStyleSheet("background-color: darkyellow; padding: 2px; border: 1px solid orange;")
            else:
                delay_display.setText("-- ps")
                delay_display.setStyleSheet("background-color: lightgray; padding: 2px; border: 1px solid gray;")
