import serial
import serial.tools.list_ports
import threading
import queue
from time import sleep
from PyQt5 import QtWidgets, QtCore

from devices.zeromq_device import DeviceWorker, DeviceOverZeroMQ, remote, include_remote_methods

class ShutterWorker(DeviceWorker):
    def __init__(self, *args, hwid="USB VID:PID=0483:374B SER=0667FF343433464757221713 LOCATION=1-8:x.2", com=None, baud=115200, **kwargs):
        super().__init__(*args, **kwargs)
        self.baud = baud
        self.com = com
        self.hwid = hwid
        self.states = []
        self._command_lock = threading.Lock()
        self._command_queue = queue.Queue()
        self._command_thread = None
        self._running = False
        self._last_status = {}

    def init_device(self):
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            if port.vid and port.hwid:
                if port.hwid == self.hwid:
                    self.com = port.device
                    self.comp = serial.Serial(self.com, self.baud, timeout=0.5)
                    self.comp.reset_input_buffer()
                    print("Device initialized on:", self.comp.name)
                    
                    # Start command processing thread
                    self._running = True
                    self._command_thread = threading.Thread(target=self._process_command_queue, daemon=True)
                    self._command_thread.start()
                    
                    # Wait for device to stabilize
                    sleep(0.5)
                    
                    return True
        print("Device not found!")
        return False

    def _process_command_queue(self):
        """Background thread to process commands in order"""
        while self._running:
            try:
                # Get command with timeout to allow thread to exit
                cmd, callback = self._command_queue.get(timeout=0.5)
                
                with self._command_lock:
                    result = self._execute_command(cmd)
                    
                if callback:
                    callback(result)
                    
                # Allow a small delay between commands
                sleep(0.05)
                
                self._command_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                print(f"Command processing error: {e}")

    def _execute_command(self, cmd):
        """Execute a single command and get response"""
        tries = 0
        max_tries = 3
        
        while tries < max_tries:
            try:
                self.comp.reset_input_buffer()
                self.comp.write(cmd.encode('ascii'))
                self.comp.flush()
                
                # Give device time to respond
                sleep(0.02)
                
                # Read response
                response = self.comp.readline()
                
                if response:
                    return response.strip().decode('ascii', errors='replace')
                else:
                    print(f"No response for command: {cmd}")
            except Exception as e:
                print(f"Command execution error: {e}")
            
            tries += 1
            sleep(0.1)  # Wait before retry
            
        return None

    def shutdown(self):
        self._running = False
        if self._command_thread:
            self._command_thread.join(timeout=1.0)
        if hasattr(self, 'comp') and self.comp:
            self.comp.close()

    def _parse_position_response(self, response, expected_axis):
        """Parse position response with better error handling"""
        if not response:
            return None
            
        try:
            parts = response.split(':')
            if len(parts) != 2:
                print(f"Invalid response format: {response}")
                return None
                
            axis = int(parts[0].strip())
            position = int(parts[1].strip())
            
            if axis != expected_axis:
                print(f"Axis mismatch: expected {expected_axis}, got {axis}")
                return None
                
            return position
        except Exception as e:
            print(f"Parse error: {e} on response: {response}")
            return None

    def status(self):
        """Cache status to reduce queries"""
        # Only update status every second at most
        current_time = QtCore.QDateTime.currentMSecsSinceEpoch()
        if hasattr(self, '_last_status_time') and current_time - self._last_status_time < 1000:
            return self._last_status
            
        d = super().status()
        for axis in [1, 2, 3, 4]:
            d[f"open{axis}"] = self._get_cached_shutter_state(axis)
        
        self._last_status = d
        self._last_status_time = current_time
        
        return d

    def _get_cached_shutter_state(self, axis):
        """Get cached state or fetch new state"""
        key = f"open{axis}"
        if hasattr(self, '_state_cache') and key in self._state_cache:
            cache_time, state = self._state_cache[key]
            current_time = QtCore.QDateTime.currentMSecsSinceEpoch()
            # Cache servo states for 2 seconds
            if current_time - cache_time < 2000:
                return state
                
        # Not in cache or expired, fetch new state
        state = self.shutter_state(axis)
        
        if not hasattr(self, '_state_cache'):
            self._state_cache = {}
            
        self._state_cache[key] = (QtCore.QDateTime.currentMSecsSinceEpoch(), state)
        return state

    @remote
    def shutter_state(self, ax):
        """Get state of a shutter (using command queue)"""
        future = []
        
        def callback(response):
            if response:
                position = self._parse_position_response(response, ax)
                if position is not None:
                    future.append(position > 1100)
                else:
                    future.append(False)
            else:
                future.append(False)
                
        self._command_queue.put((f'?{ax}', callback))
        
        # Wait for response with timeout
        start_time = QtCore.QDateTime.currentMSecsSinceEpoch()
        while not future and QtCore.QDateTime.currentMSecsSinceEpoch() - start_time < 500:
            sleep(0.01)
            
        return future[0] if future else False

    @remote
    def move_shutter(self, action, *axes):
        """Move shutters (using command queue)"""
        letters = [['q', 'a', 'z'], ['w', 's', 'x'], ['e', 'd', 'c'], ['r', 'f', 'v']]
        
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
                    continue
                    
            # Clear any cached state
            if hasattr(self, '_state_cache'):
                key = f"open{ax}"
                if key in self._state_cache:
                    del self._state_cache[key]
                    
            # Queue the command (no callback needed)
            self._command_queue.put((pos, None))


@include_remote_methods(ShutterWorker)
class Shutter(DeviceOverZeroMQ):
    status_updated = QtCore.pyqtSignal(dict)  # Add signal for status updates

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_interval = 1000  # Changed from 500ms to 1000ms
        self._update_timer = None
        self._last_status = {}
        self._button_states = {}

    def _generate_func(self, number):
        def change_shutter_state(on):
            if on:
                self.move_shutter('w_open', number)
                # Update UI immediately to feel responsive
                self._button_states[number] = True
                self.buttons[number].setText(f"Servo {number} - OPEN")
            else:
                self.move_shutter('close', number)
                # Update UI immediately to feel responsive
                self._button_states[number] = False
                self.buttons[number].setText(f"Servo {number} - CLOSED")
        return change_shutter_state

    def update_status(self):
        """Update status with reduced frequency"""
        try:
            status = self.status()
            self.update_ui(status)
        except Exception as e:
            print(f"Status update error: {e}")

    def update_ui(self, status):
        """Update UI based on status, only changing what's needed"""
        for axis in [1, 2, 3, 4]:
            try:
                state_key = f"open{axis}"
                if state_key in status:
                    current_state = status[state_key]
                    
                    # Only update button if state changed
                    if axis not in self._button_states or self._button_states[axis] != current_state:
                        self._button_states[axis] = current_state
                        if current_state:
                            self.buttons[axis].setText(f"Servo {axis} - OPEN")
                        else:
                            self.buttons[axis].setText(f"Servo {axis} - CLOSED")
            except Exception as e:
                print(f"Error updating status for axis {axis}: {e}")

    def createDock(self, parentWidget, menu=None):
        dock = QtWidgets.QDockWidget("ServoShutter", parentWidget)
        widget = QtWidgets.QWidget(parentWidget)
        layout = QtWidgets.QVBoxLayout()
        widget.setLayout(layout)

        self.buttons = {}
        self._button_states = {}

        for axis in [1, 2, 3, 4]:
            button = QtWidgets.QPushButton(f"Servo {axis} - Unknown")
            button.setCheckable(True)
            button.clicked.connect(self._generate_func(axis))
            self.buttons[axis] = button
            layout.addWidget(button)

        # Add status indicator
        self.status_label = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status_label)

        dock.setWidget(widget)
        dock.setAllowedAreas(QtCore.Qt.TopDockWidgetArea | QtCore.Qt.BottomDockWidgetArea)
        parentWidget.addDockWidget(QtCore.Qt.TopDockWidgetArea, dock)
        if menu:
            menu.addAction(dock.toggleViewAction())

        # Setup timer for status updates with reduced frequency
        self._update_timer = QtCore.QTimer()
        self._update_timer.timeout.connect(self.update_status)
        self._update_timer.start(self._update_interval)
