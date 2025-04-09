import queue
import threading
import time

import serial
import serial.tools.list_ports
from devices.zeromq_device import (
    DeviceOverZeroMQ,
    DeviceWorker,
    include_remote_methods,
    remote,
)
from PyQt5 import QtCore, QtWidgets


class ShutterWorker(DeviceWorker):
    def __init__(self, *args, hwid="SER=066EFF343433464757222518", com=None, baud=115200, **kwargs):
        super().__init__(*args, **kwargs)
        self.baud = baud
        self.com = com
        self.hwid = hwid
        self._connected = False
        self._command_lock = threading.Lock()
        
        # New binary protocol constants
        self.CMD_START = 0xFF
        self.CMD_END = 0xFE
        self.CMD_MOVE = 0x01
        self.CMD_QUERY = 0x02
        self.RESP_STATUS_OK = 0x00
        
        # Response handling
        self.response_queue = queue.Queue()
        self.response_thread = None
        self.running = False

    def init_device(self):
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            if port.vid and port.hwid:
                if port.hwid.__contains__(self.hwid):
                    self.com = port.device
                    self.comp = serial.Serial(self.com, self.baud, timeout=0.5)
                    self.comp.reset_input_buffer()
                    print("Device initialized on:", self.comp.name)
                    self._connected = True
                    
                    # Start response reading thread
                    self.running = True
                    self.response_thread = threading.Thread(target=self._read_responses)
                    self.response_thread.daemon = True
                    self.response_thread.start()

    def _read_responses(self):
        """Background thread to continuously read and process responses"""
        buffer = bytearray()
        in_response = False
        
        while self.running:
            if self.comp.in_waiting:
                try:
                    data = self.comp.read(self.comp.in_waiting)
                    for byte in data:
                        if byte == self.CMD_START:
                            buffer = bytearray([byte])
                            in_response = True
                        elif byte == self.CMD_END and in_response:
                            buffer.append(byte)
                            # Process completed response
                            if len(buffer) >= 6:  # Minimum valid response length
                                self.response_queue.put(bytes(buffer))
                            in_response = False
                            buffer = bytearray()
                        elif in_response:
                            buffer.append(byte)
                except Exception as e:
                    print(f"Error reading response: {e}")
            else:
                time.sleep(0.01)  # Small delay to prevent CPU hogging

    def close(self):
        """Clean shutdown of worker"""
        self.running = False
        if self.response_thread:
            self.response_thread.join(timeout=1.0)
        if hasattr(self, 'comp') and self.comp:
            self.comp.close()
        super().close()

    def _send_binary_command(self, cmd_type, servo, position=0):
        """Send a binary protocol command and wait for response if needed"""
        with self._command_lock:
            try:
                # Create command packet: START + CMD_TYPE + PARAM + END
                param_byte = ((servo & 0x0F) << 4) | (position & 0x0F)
                packet = bytes([self.CMD_START, cmd_type, param_byte, self.CMD_END])
                
                # Clear any old responses
                while not self.response_queue.empty():
                    self.response_queue.get_nowait()
                
                # Send command
                self.comp.write(packet)
                
                # If this is a query, wait for response
                if cmd_type == self.CMD_QUERY:
                    try:
                        # Wait for response with timeout
                        response = self.response_queue.get(timeout=0.5)
                        
                        # Parse response
                        if (len(response) >= 6 and 
                            response[0] == self.CMD_START and 
                            response[1] == self.RESP_STATUS_OK and
                            response[5] == self.CMD_END):
                            
                            # Extract servo position data
                            servo_id = response[2]
                            position = (response[3] << 8) | response[4]
                            
                            return position
                    except queue.Empty:
                        print("Response timeout")
                        return None
                return True
            except Exception as e:
                print(f"Error sending command: {e}")
                return None

    def status(self):
        d = super().status()
        for axis in [1, 2, 3, 4]:
            d[f"open{axis}"] = self.state(axis)
        # print(d)
        return d

    @remote
    def state(self, ax):
        """Query the state of a servo using binary protocol"""
        if not self._connected:
            return False
            
        # Convert to 0-based index for protocol
        servo_index = ax - 1
        if servo_index < 0 or servo_index > 3:
            return False
            
        # Send query and get position
        position = self._send_binary_command(self.CMD_QUERY, servo_index)
        
        if position is None:
            return False
            
        # Return True if position is greater than LOW
        return position > 1100

    @remote
    def move(self, action, *axes):
        """Move servos using binary protocol"""
        if not self._connected:
            return False
            
        try:
            for ax in axes:
                # Convert to 0-based index
                servo = ax - 1
                if servo < 0 or servo > 3:
                    continue
                    
                # Map action to position
                position = 0  # Default to LOW (close)
                if action == 'open':
                    position = 1  # MID
                elif action == 'w_open':
                    position = 2  # HIGH
                    
                # Send binary command
                self._send_binary_command(self.CMD_MOVE, servo, position)
                
            return True
        except Exception as e:
            print(f"Error moving shutter: {e}")
            return False
            
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
