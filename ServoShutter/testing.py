import serial
import serial.tools.list_ports

from time import sleep


def find_port_by_pid(pid):
	pid = int(pid, 16) if isinstance(pid, str) else pid

	ports = serial.tools.list_ports.comports()

	for p in ports:
		if p.vid and p.pid:
			if p.pid == pid:
				return p.device

	return None


def servo_shutter(action, *axes, listen=None):
	letters = [['q', 'a', 'z'], ['w', 's', 'x'], ['e', 'd', 'c'], ['r', 'f', 'v']]
	for ax in axes:
		match action:
			case 'close':
				pos = letters[ax-1][0]
			case 'open':
				pos = letters[ax-1][1]
			case 'w_open':
				pos = letters[ax-1][2]
			case 'state':
				pos = f'?{ax}'
			case 'conn':
				pos = f'?conn{ax}'
			case 'ct':
				pos = '?connectivity'
			case _:
				print("WRONG INPUT! ONLY: 'open' / 'close' / 'w_open' / 'state'")
				break

		full_command = pos.strip()
		print(f"Sending: '{full_command}'")

		ser.reset_input_buffer()
		ser.write(full_command.encode('ascii'))
		ser.flush()

		if listen:
			ser.timeout = 1
			odp = ser.readline().strip()
			try:
				decoded = odp.decode('ascii', errors='replace')
				print(f"\t'{decoded}'")
			except Exception as e:
				print(f"\tDecode Error: {e}")
				print(f"\tRaw Bytes: {odp}")


if __name__ == '__main__':
	target_pid = 0x374b
	port = find_port_by_pid(target_pid)
	if port:
		print(f"Device with PID {hex(target_pid)} found on port: {port}")
	else:
		print(f"No device with PID {hex(target_pid)} found.")
	ser = serial.Serial(port, 9600, timeout=2)

	# servo_shutter('conn', 1, listen=True)
	# sleep(.5)
	# servo_shutter('conn', 2, listen=True)
	# sleep(.5)
	# servo_shutter('conn', 3, listen=True)
	# sleep(.5)
	# servo_shutter('conn', 4, listen=True)

	sleep(1)

	servo_shutter("close", 4)
	sleep(1)
	servo_shutter("state", 4, listen=True)
	sleep(1)
	servo_shutter("open", 4)
	sleep(1)
	servo_shutter("state", 4, listen=True)
	sleep(1)
	servo_shutter("w_open", 4)
	sleep(1)
	servo_shutter("state", 4, listen=True)
	sleep(1)
	servo_shutter("close", 4)
	sleep(1)
	servo_shutter("state", 4, listen=True)
