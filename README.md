# ServoShutter Setup Guide

## Installation Instructions

To connect the SERVO controller, follow these steps:

### 1. Copy Python File
Copy the `ServoShutter.py` file to the `pylums/devices/misc` folder.

### 2. Configure Serial Number
Open the `ServoShutter.py` file and replace `<SERIAL NUMBER>` with the HWID number corresponding to your microcontroller:

```python
class ShutterWorker(DeviceWorker):
   def __init__(self, *args, hwid="SER=<SERIAL NUMBER>", com=None, baud=115200, **kwargs):
```

#### Finding the HWID
You can find the HWID by running the following PowerShell command in Windows Terminal (and looking for STM controllers):

```powershell
Get-WmiObject -Class Win32_PnPEntity | Where-Object {$_.Name -match "COM\d+"} | ForEach-Object {
   $hwid = $_.HardwareID[0]
   $vendorId = if ($hwid -match "VID_([0-9A-F]{4})") { $matches[1] } else { "N/A" }
   $productId = if ($hwid -match "PID_([0-9A-F]{4})") { $matches[1] } else { "N/A" }
   [PSCustomObject]@{
       Port = ($_.Name -replace ".*\((COM\d+)\).*", '$1')
       VID = $vendorId
       PID = $productId
       HWID = $hwid
       Description = $_.Name
   }
} | Format-Table -AutoSize
```

### 3. Update Configuration Files
Update the `devices.ini` and `local_devices.ini` files according to the templates provided in the `ini_files_entries.txt` file.

### 4. Verify Setup
After completing the above steps, both `DeviceServer` and `InteractiveControl` should now detect the controller and display the control widget.

### 5. Console Commands
Console commands can be found and tested from the Python file.

## ⚠️ Important Warnings

- **SERVO CONNECTION**: Make sure the servo is connected to the controller in the correct orientation. If it doesn't work, try flipping the 3-pin connector 180 degrees and test again.

- **⚡ POWER SUPPLY**: The servo accepts up to **6V DC** supply voltage only!
