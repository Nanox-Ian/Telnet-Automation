# Telnet Command Automation and Screenshot Capture

This python script automates the process of connecting to network devices via telnet commands, and capturing both textual and image-based screenshot of the output

## Overview
The Script performs the following tasks:
1. Connects to a gateway device.
2. Logs into a list of target devices via Telnet.
3. Executes a configured command on each target devices.
4. Captures the output of the command both as text logs and as images (screenshots).
5. Saves the text logs and screenshots to specified directories.

The Script uses `telnetlib` for Telnet communication and `Pillow` for generating image screenshots from the text output.

# Configuration
The Script uses a configuration directory `CONFIG` that controls the following parameters:
- `gateway_ip`: The IP addresss of the gateway device.
- `username`: Username for login on both gateway and target devices
- `password`: Password fro login both gateways and target devices
- `enable_password`: Optional password for entering priviledge mode on the target devices (set to `None` if not required).
- `devices_file`: file containing a list of target IP addresses (one per line).
- `command`: Command to run on each target device (e.g., `show interface status`).
- `output_dir`: Directory where text logs will be saved (optional)
- `img_dir`: Directory where screenshot images will be saved.
- `telnet_port`: Port used for Telnet connection (default is 23).
- `connect_timeout`: Timeout for establishing a Telnet connection.
- `op_timeout`: Timeout for reading outputs and interacting with the device.
- `sleep_short`: Small delay between reads/writes to avoid overwhelming the devices.
- `save_text_logs`: If set to `True`, saves text logs in addition to the images.

# Requirements
- Python 3.6+
- The `Pillow` library for image processsing:
```
pip install Pillow
```
- A list of target devices saved in a text file (`devices.txt`).

# Functions
1. `ensure_dirs()` - Ensures that the output directories for text logs and images exist. If not, it creates them.
2. `read_until_prompt()` - Reads Telnet output until a prompt (`>`, `#`, ir `$`) is encountered or a timeout occures
3. `send_and_collect()` - Sends a command via Telnet and collects the output until the prompts is reached, handing pagination if necessary
4. `negotiate_login()` - Handles the login process including banners, username/password prompts, and final device prompt detection.
5. `enter_enable_if_needed()` - Handles entering privileged mode on device if an `enable_password` is specified.
6. `disable_paging()` - Disables paging for Cisco devices to prevent prompts like `--More--`.
7. `save_text()` - Saves text content to a specified file path.
8. `text_to_image()` - Converts text output to an image and saves it to the specified file path
9. `run()` - The main function that orchestrates the Telnet Connections, command execution, output collectionm and saving of text and images logs. it:
    - Connects to the gateway.
    - Logs into each target device.
    - Executes the command.
    - Collects the output, cleans it up, and saves it as both text and images

# Execution Flow
1. **Load Target Devices**: The script loads the IP addresses of target devices from the file specified in `CONFIG["device_file"]`.
2. **Telnet to Gateway**: The script connects to the gateway device using the credentials provided in `CONFIG`.
3. **Login Process**: The script negotiates the login on the gateway and any subsequent target devices.
4. **Execute Command**: For each target device, the script sends the specified command and collects the output.
5. **Save Output**: the output is saved as:
   - A text file in `output_dir`
   - A PNG image in `img_dir`
6. **Exit**: The script safely closes the connection after processsing all devices.

# Example Usage
1. Modify the configuration dictionary (`CONFIG`) to reflect your environment including the gateway device IP, usernames, passwords, target device list, and directories.
2. Save your target devices IPs in a text file (one IP per line)
3. Run the script:
   ```
   python telnet_script.py
   ```
## Output
For each target device:
-  A text log is created in the specified `output_dir`.
-  A PNG screenshot image is created in the `img_dir`.
The text and image files are named using the format:
```
<device_ip>_<timestamp>.txt
<device_ip>_<timestamp>.png
```
## Notes
- Ensure that the devices in the `devices.txt` file are reachable and that you have the appropriate login scredentials for both the gateway and target devices.
- The script assumes the devices use Cisco-like login prompts. If your devices use different prompts, you may need to adjust the regular expresssions.

# License
*This script is provided under MIT License. Feel free to modify and use it as needed for your use case.*
