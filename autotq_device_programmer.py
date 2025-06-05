#!/usr/bin/env python3
"""
AutoTQ Device Programmer - Direct ESP32-S3 Audio File Transfer
Connects to AutoTQ devices via USB serial and transfers audio files
using the same protocol as the manufacturer portal.
"""

import os
import sys
import json
import time
import argparse
import threading
import platform
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import zlib  # For CRC32 calculation

# Third-party imports
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("❌ Error: pyserial not installed. Install with: pip install pyserial")
    sys.exit(1)

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("⚠️  Warning: tqdm not installed. Progress bars will be basic.")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("⚠️  Warning: requests not installed. Cannot download from server.")


class AutoTQDeviceProgrammer:
    """AutoTQ Device Programmer for ESP32-S3 devices"""
    
    # Required audio files for AutoTQ devices
    REQUIRED_AUDIO_FILES = [
        "tightenStrap.wav",
        "bleedingContinues.wav", 
        "pullStrapTighter.wav",
        "inflating.wav",
        "timeRemaining.wav"
    ]
    
    # Serial communication settings
    BAUD_RATE = 115200
    TIMEOUT = 5.0
    WRITE_CHUNK_SIZE = 256  # ESP32 write size per operation
    WRITE_DELAY = 0.001   # 2ms delay between writes
    FILE_CHUNK_SIZE = 2048  # File transfer chunk size
    
    def __init__(self, port: str = None, audio_dir: str = None, server_url: str = None):
        """
        Initialize the AutoTQ Device Programmer
        
        Args:
            port: Serial port (if None, will auto-detect)
            audio_dir: Directory containing audio files
            server_url: Server URL to download audio files from
        """
        self.port_name = port
        self.serial_port = None
        self.audio_dir = Path(audio_dir) if audio_dir else Path("audio")
        self.server_url = server_url
        self.is_connected = False
        self.device_info = {}
        
        # Transfer speed parameters (instance attributes)
        self.write_chunk_size = self.WRITE_CHUNK_SIZE
        self.write_delay = self.WRITE_DELAY
        self.file_chunk_size = self.FILE_CHUNK_SIZE
        
        # Threading for reading responses
        self.read_thread = None
        self.stop_reading = False
        self.response_buffer = []
        self.response_lock = threading.Lock()
        
        # Create audio directory
        self.audio_dir.mkdir(exist_ok=True)
        
        current_platform = platform.system()
        print(f"🔧 AutoTQ Device Programmer initialized ({current_platform})")
        print(f"📁 Audio directory: {self.audio_dir.absolute()}")
        
        # Platform-specific setup hints
        if current_platform.lower() == "linux":
            print("💡 Linux detected - ensure user has serial port permissions")
        elif current_platform.lower() == "windows":
            print("💡 Windows detected - COM ports will be used")
        elif current_platform.lower() == "darwin":
            print("💡 macOS detected - USB devices will appear as /dev/cu.* or /dev/tty.*")
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp and emoji"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        emoji_map = {
            "INFO": "ℹ️ ",
            "SUCCESS": "✅ ",
            "WARNING": "⚠️ ",
            "ERROR": "❌ ",
            "PROGRESS": "🔄 ",
            "DEVICE": "📟 ",
            "TRANSFER": "📤 "
        }
        emoji = emoji_map.get(level, "")
        print(f"[{timestamp}] {emoji} {message}")
    
    def list_available_ports(self) -> List[Tuple[str, str]]:
        """List available serial ports that might be ESP32 devices"""
        ports = []
        current_platform = platform.system().lower()
        
        self.log("Scanning for available serial ports...")
        for port in serial.tools.list_ports.comports():
            # Look for ESP32/USB CDC devices with expanded keywords
            is_esp32 = any(keyword in port.description.lower() for keyword in 
                          ['esp32', 'esp32-s3', 'usb serial', 'cdc', 'uart', 'ch340', 'cp210', 'ft232', 'silicon labs'])
            
            # Check for common ESP32/Arduino USB vendor/product IDs
            esp32_device_ids = [
                (0x303A, 0x1001),  # Espressif ESP32-S3
                (0x10C4, 0xEA60),  # Silicon Labs CP2102/CP2109
                (0x1A86, 0x7523),  # QinHeng Electronics CH340
                (0x0403, 0x6001),  # FTDI FT232R
                (0x067B, 0x2303),  # Prolific PL2303
                (0x2341, 0x0043),  # Arduino Uno
                (0x2341, 0x0001),  # Arduino Mega
            ]
            
            vid_pid_match = False
            if port.vid is not None and port.pid is not None:
                vid_pid_match = (port.vid, port.pid) in esp32_device_ids
            
            # Enhanced device description for different platforms
            device_description = port.description
            
            # Add platform-specific device information
            if current_platform == "linux":
                # On Linux, add device path information
                device_path = getattr(port, 'device_path', None)
                if device_path and '/dev/serial/by-id/' in device_path:
                    device_description += f" (ID: {os.path.basename(device_path)})"
                elif hasattr(port, 'location') and port.location:
                    device_description += f" (USB: {port.location})"
                
                # Add device node information
                if port.device.startswith('/dev/ttyUSB'):
                    device_description += " (USB-Serial)"
                elif port.device.startswith('/dev/ttyACM'):
                    device_description += " (USB-CDC)"
            
            # Include device if it matches criteria or has USB identifiers
            if is_esp32 or vid_pid_match or (port.vid is not None and port.pid is not None):
                vid_pid_str = f"VID:PID={port.vid:04X}:{port.pid:04X}" if port.vid else "Unknown"
                port_description = f"{device_description} [{port.device}] {vid_pid_str}"
                
                # Mark likely AutoTQ/ESP32 devices
                if vid_pid_match or 'esp32' in device_description.lower():
                    port_description = f"🎯 {port_description}"
                elif is_esp32:
                    port_description = f"📟 {port_description}"
                else:
                    port_description = f"❓ {port_description}"
                
                ports.append((port.device, port_description))
                self.log(f"Found potential device: {port.device} - {device_description}")
        
        if not ports:
            self.log("No potential ESP32/AutoTQ devices found", "WARNING")
            if current_platform == "linux":
                self.log("💡 On Linux, ensure user is in 'dialout' group: sudo usermod -a -G dialout $USER", "INFO")
                self.log("💡 Then logout and login again, or run: newgrp dialout", "INFO")
                self.log("💡 Check if device is connected and detected: lsusb | grep -E '(ESP32|CP210|CH340|FT232)'", "INFO")
        
        return ports
    
    def auto_detect_port(self) -> Optional[str]:
        """Auto-detect ESP32 device port with enhanced multi-device support"""
        ports = self.list_available_ports()
        
        if len(ports) == 1:
            selected_port = ports[0][0]
            self.log(f"Auto-detected device: {ports[0][1]}", "SUCCESS")
            return selected_port
        elif len(ports) > 1:
            self.log("Multiple devices found. Please specify which one to use:", "INFO")
            
            # Separate ESP32-specific devices from others
            esp32_ports = [(port, desc) for port, desc in ports if '🎯' in desc]
            other_ports = [(port, desc) for port, desc in ports if '🎯' not in desc]
            
            print("\n📟 Available devices:")
            device_index = 1
            
            if esp32_ports:
                print("  ESP32/AutoTQ devices (recommended):")
                for port, desc in esp32_ports:
                    print(f"    {device_index}. {desc}")
                    device_index += 1
                
                if other_ports:
                    print("  Other USB serial devices:")
                    for port, desc in other_ports:
                        print(f"    {device_index}. {desc}")
                        device_index += 1
            else:
                for port, desc in ports:
                    print(f"  {device_index}. {desc}")
                    device_index += 1
            
            # Smart default suggestion
            if esp32_ports:
                suggested = 1
                print(f"\n💡 Suggestion: Device {suggested} appears to be an ESP32/AutoTQ device")
            
            try:
                choice = input(f"\nEnter device number (1-{len(ports)}): ").strip()
                
                # Allow 'auto' to select first ESP32 device
                if choice.lower() == 'auto' and esp32_ports:
                    selected_port = esp32_ports[0][0]
                    self.log(f"Auto-selected ESP32 device: {esp32_ports[0][1]}", "SUCCESS")
                    return selected_port
                
                index = int(choice) - 1
                if 0 <= index < len(ports):
                    selected_port = ports[index][0]
                    self.log(f"Selected device: {ports[index][1]}", "SUCCESS")
                    return selected_port
                else:
                    self.log("Invalid selection", "ERROR")
                    return None
            except (ValueError, KeyboardInterrupt):
                self.log("Selection cancelled", "WARNING")
                return None
        
        return None
    
    def connect(self) -> bool:
        """Connect to the ESP32 device with enhanced platform support"""
        if self.is_connected:
            self.log("Already connected", "WARNING")
            return True
        
        # Determine port
        if not self.port_name:
            self.port_name = self.auto_detect_port()
            if not self.port_name:
                self.log("No device port specified or detected", "ERROR")
                return False
        
        try:
            self.log(f"Connecting to device on {self.port_name}...")
            
            # Platform-specific connection checks
            current_platform = platform.system().lower()
            if current_platform == "linux":
                # Check if port exists
                if not os.path.exists(self.port_name):
                    self.log(f"Device {self.port_name} not found. Check if device is connected.", "ERROR")
                    return False
                
                # Check read permissions
                try:
                    os.access(self.port_name, os.R_OK | os.W_OK)
                except PermissionError:
                    self.log(f"Permission denied accessing {self.port_name}", "ERROR")
                    self.log("💡 Add user to dialout group: sudo usermod -a -G dialout $USER", "INFO")
                    self.log("💡 Then logout and login again, or run: newgrp dialout", "INFO")
                    return False
            
            # Open serial port
            self.serial_port = serial.Serial(
                port=self.port_name,
                baudrate=self.BAUD_RATE,
                timeout=self.TIMEOUT,
                write_timeout=self.TIMEOUT
            )
            
            # Wait for device to stabilize
            self.log("Waiting for device to stabilize...")
            time.sleep(2.0)
            
            # Start reading thread
            self.stop_reading = False
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()
            
            # Test communication
            if self._test_communication():
                self.is_connected = True
                self.log("Successfully connected to AutoTQ device", "SUCCESS")
                return True
            else:
                self.log("Device communication test failed", "ERROR")
                self.log("💡 Make sure the device is in the correct mode and firmware supports USB commands", "INFO")
                self.disconnect()
                return False
                
        except serial.SerialException as e:
            error_msg = str(e).lower()
            if "permission denied" in error_msg or "access denied" in error_msg:
                self.log(f"Permission denied: {e}", "ERROR")
                if current_platform == "linux":
                    self.log("💡 Add user to dialout group: sudo usermod -a -G dialout $USER", "INFO")
                    self.log("💡 Then logout and login again, or run: newgrp dialout", "INFO")
                elif current_platform == "windows":
                    self.log("💡 Close any other programs using this COM port", "INFO")
            elif "device not found" in error_msg or "file not found" in error_msg:
                self.log(f"Device not found: {e}", "ERROR")
                self.log("💡 Check if device is connected and try refreshing the port list", "INFO")
            elif "busy" in error_msg or "in use" in error_msg:
                self.log(f"Port in use: {e}", "ERROR")
                self.log("💡 Close any other programs using this port", "INFO")
            else:
                self.log(f"Serial connection failed: {e}", "ERROR")
            return False
        except Exception as e:
            self.log(f"Unexpected error during connection: {e}", "ERROR")
            return False
    
    def _read_loop(self):
        """Background thread to read device responses"""
        buffer = ""
        
        while not self.stop_reading and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if line:
                            self._process_device_message(line)
                
                time.sleep(0.01)  # Small delay to prevent busy waiting
                
            except Exception as e:
                if not self.stop_reading:
                    self.log(f"Read error: {e}", "ERROR")
                break
    
    def _process_device_message(self, message: str):
        """Process a message received from the device"""
        try:
            # Try to parse as JSON
            response = json.loads(message)
            self.log(f"Device response: {json.dumps(response)}", "DEVICE")
            
            with self.response_lock:
                self.response_buffer.append(response)
            
            # Handle specific responses
            if response.get('command') == 'wifi_get_mac' and 'mac' in response:
                self.device_info['mac_address'] = response['mac']
                self.log(f"Device MAC: {response['mac']}", "SUCCESS")
            elif response.get('command') == 'list_files' and 'files' in response:
                self.device_info['files'] = response['files']
                self.log(f"Device has {len(response['files'])} files", "SUCCESS")
            elif response.get('command') == 'binary_transfer_complete':
                self.log(f"Transfer complete: {response.get('filename', 'unknown')}", "SUCCESS")
                
        except json.JSONDecodeError:
            # Non-JSON message (debug output, etc.)
            # Filter out verbose debug messages but keep important ones
            if not any(filter_word in message.lower() for filter_word in 
                      ['audiotask', 'i2s config', 'audiohdr', 'timing', 'flash dbg']):
                self.log(f"Device: {message}", "DEVICE")
    
    def _test_communication(self) -> bool:
        """Test communication with the device"""
        try:
            # Clear any existing responses
            with self.response_lock:
                self.response_buffer.clear()
            
            # Send MAC address request
            self.log("Testing device communication...")
            if not self._send_command({'command': 'wifi_get_mac'}):
                return False
            
            # Wait for response
            max_wait = 3.0
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                with self.response_lock:
                    for response in self.response_buffer:
                        if response.get('command') == 'wifi_get_mac':
                            return True
                time.sleep(0.1)
            
            # Try getting status as backup test
            self.log("MAC request timeout, trying status command...")
            if not self._send_command({'command': 'get_status'}):
                return False
            
            time.sleep(1.0)  # Give some time for any response
            return True  # Assume success if no serial errors
            
        except Exception as e:
            self.log(f"Communication test error: {e}", "ERROR")
            return False
    
    def _send_command(self, command: Dict[str, Any]) -> bool:
        """Send a JSON command to the device"""
        if not self.serial_port or not self.serial_port.is_open:
            self.log("Device not connected", "ERROR")
            return False
        
        try:
            command_str = json.dumps(command) + '\n'
            self.serial_port.write(command_str.encode('utf-8'))
            self.serial_port.flush()
            self.log(f"Sent command: {json.dumps(command)}")
            return True
        except Exception as e:
            self.log(f"Failed to send command: {e}", "ERROR")
            return False
    
    def disconnect(self):
        """Disconnect from the device"""
        self.log("Disconnecting from device...")
        
        # Stop reading thread
        self.stop_reading = True
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1.0)
        
        # Close serial port
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception as e:
                self.log(f"Error closing serial port: {e}", "WARNING")
        
        self.serial_port = None
        self.is_connected = False
        self.device_info.clear()
        
        self.log("Disconnected", "SUCCESS")
    
    def calculate_crc32(self, data: bytes) -> int:
        """Calculate CRC32 checksum for data integrity"""
        return zlib.crc32(data) & 0xffffffff
    
    def list_device_files(self) -> Optional[List[str]]:
        """Get list of files on the device"""
        if not self.is_connected:
            self.log("Device not connected", "ERROR")
            return None
        
        # Clear previous responses
        with self.response_lock:
            self.response_buffer.clear()
        
        self.log("Requesting file list from device...")
        if not self._send_command({'command': 'list_files'}):
            return None
        
        # Wait for response
        max_wait = 5.0
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            with self.response_lock:
                for response in self.response_buffer:
                    if (response.get('command') == 'list_files' and 
                        response.get('response') == 'file_list' and 
                        'files' in response):
                        files = response['files']
                        self.log(f"Device has {len(files)} files: {files}", "SUCCESS")
                        return files
            time.sleep(0.1)
        
        self.log("Timeout waiting for file list", "WARNING")
        return []
    
    def transfer_file_to_device(self, file_path: Path, show_progress: bool = True) -> bool:
        """
        Transfer a single audio file to the device using optimized settings
        """
        if not self.is_connected:
            self.log("Device not connected", "ERROR")
            return False
        
        if not file_path.exists():
            self.log(f"File not found: {file_path}", "ERROR")
            return False
        
        # Read file data
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
        except Exception as e:
            self.log(f"Failed to read file {file_path}: {e}", "ERROR")
            return False
        
        filename = file_path.name
        file_size = len(file_data)
        file_crc = self.calculate_crc32(file_data)
        
        self.log(f"Starting transfer: {filename} ({file_size:,} bytes, CRC32: {file_crc:08x})", "TRANSFER")
        
        # Send initial download command
        download_cmd = {
            "command": "download_file",
            "filename": filename,
            "size": file_size,
            "chunk_size": 1024,  # Optimal chunk size
            "crc": file_crc
        }
        
        if not self._send_command(download_cmd):
            return False
        
        # Brief pause for device to process command
        time.sleep(0.1)
        
        # Setup progress tracking
        if show_progress and HAS_TQDM:
            progress_bar = tqdm(
                total=file_size,
                desc=f"Transferring {filename}",
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                ncols=80
            )
        else:
            progress_bar = None
        
        try:
            bytes_sent = 0
            chunk_size = 1024  # Optimal chunk size
            write_size = 64    # Optimal write size
            
            while bytes_sent < file_size:
                # Calculate chunk size
                remaining = file_size - bytes_sent
                current_chunk_size = min(chunk_size, remaining)
                chunk_data = file_data[bytes_sent:bytes_sent + current_chunk_size]
                
                # Send chunk in small pieces with minimal delays
                chunk_pos = 0
                while chunk_pos < len(chunk_data):
                    piece_size = min(write_size, len(chunk_data) - chunk_pos)
                    piece = chunk_data[chunk_pos:chunk_pos + piece_size]
                    
                    try:
                        self.serial_port.write(piece)
                        self.serial_port.flush()
                        chunk_pos += piece_size
                        
                        # Minimal delay - optimal for ESP32
                        time.sleep(0.0001)  # 0.1ms
                        
                    except Exception as e:
                        self.log(f"Write error at position {bytes_sent + chunk_pos}: {e}", "ERROR")
                        if progress_bar:
                            progress_bar.close()
                        return False
                
                bytes_sent += current_chunk_size
                
                # Update progress
                if progress_bar:
                    progress_bar.update(current_chunk_size)
                elif show_progress:
                    percent = (bytes_sent / file_size) * 100
                    print(f"\r🔄 Progress: {percent:.1f}% ({bytes_sent:,}/{file_size:,} bytes)", end='', flush=True)
            
            if progress_bar:
                progress_bar.close()
            elif show_progress:
                print()  # New line after progress
            
            # Wait for device to finish
            time.sleep(0.5)
            
            self.log(f"Transfer completed: {filename}", "SUCCESS")
            return True
            
        except Exception as e:
            if progress_bar:
                progress_bar.close()
            self.log(f"Transfer failed: {e}", "ERROR")
            return False
    
    def transfer_required_files(self, skip_existing: bool = True) -> Tuple[int, int]:
        """
        Transfer all required audio files to the device
        
        Returns:
            Tuple of (successful_transfers, failed_transfers)
        """
        if not self.is_connected:
            self.log("Device not connected", "ERROR")
            return 0, len(self.REQUIRED_AUDIO_FILES)
        
        # Get current device files if checking for existing
        device_files = []
        if skip_existing:
            device_files = self.list_device_files() or []
        
        successful = 0
        failed = 0
        
        self.log(f"Starting transfer of {len(self.REQUIRED_AUDIO_FILES)} required audio files", "TRANSFER")
        
        for i, filename in enumerate(self.REQUIRED_AUDIO_FILES, 1):
            self.log(f"Processing file {i}/{len(self.REQUIRED_AUDIO_FILES)}: {filename}", "PROGRESS")
            
            # Check if file already exists on device
            if skip_existing and filename in device_files:
                self.log(f"File {filename} already exists on device, skipping", "INFO")
                successful += 1
                continue
            
            # Find file in audio directory
            file_path = self.audio_dir / filename
            
            if not file_path.exists():
                self.log(f"Local file not found: {filename}", "ERROR")
                failed += 1
                continue
            
            # Transfer file
            if self.transfer_file_to_device(file_path):
                successful += 1
                # Brief pause between files
                if i < len(self.REQUIRED_AUDIO_FILES):
                    time.sleep(0.5)
            else:
                failed += 1
        
        # Summary
        total = len(self.REQUIRED_AUDIO_FILES)
        self.log(f"Transfer complete: {successful}/{total} succeeded, {failed}/{total} failed", 
                "SUCCESS" if failed == 0 else "WARNING")
        
        return successful, failed
    
    def download_audio_from_server(self, filename: str) -> bool:
        """Download audio file from server to local audio directory"""
        if not HAS_REQUESTS:
            self.log("Requests library not available for server downloads", "ERROR")
            return False
        
        if not self.server_url:
            self.log("No server URL configured", "ERROR")
            return False
        
        try:
            url = f"{self.server_url}/audio/file/{filename}"
            self.log(f"Downloading {filename} from server...")
            
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            file_path = self.audio_dir / filename
            total_size = int(response.headers.get('content-length', 0))
            
            if HAS_TQDM and total_size > 0:
                with tqdm(total=total_size, desc=f"Downloading {filename}", 
                         unit='B', unit_scale=True, unit_divisor=1024) as pbar:
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
            else:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            
            self.log(f"Downloaded {filename} successfully", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Failed to download {filename}: {e}", "ERROR")
            return False
    
    def check_local_files(self) -> Tuple[List[str], List[str]]:
        """
        Check which required files are available locally
        
        Returns:
            Tuple of (available_files, missing_files)
        """
        available = []
        missing = []
        
        for filename in self.REQUIRED_AUDIO_FILES:
            file_path = self.audio_dir / filename
            if file_path.exists():
                available.append(filename)
            else:
                missing.append(filename)
        
        return available, missing
    
    def interactive_menu(self):
        """Interactive menu for device operations"""
        while True:
            print("\n" + "="*60)
            print("🎵 AutoTQ Device Programmer")
            print("="*60)
            
            if self.is_connected:
                mac = self.device_info.get('mac_address', 'Unknown')
                print(f"📟 Connected to device: {mac} on {self.port_name}")
            else:
                print("📟 No device connected")
                
                # Show available ports info when not connected
                ports = self.list_available_ports()
                if ports:
                    esp32_count = len([p for p, d in ports if '🎯' in d])
                    other_count = len(ports) - esp32_count
                    
                    if esp32_count > 0:
                        print(f"📱 Detected {esp32_count} ESP32/AutoTQ device(s)")
                    if other_count > 0:
                        print(f"❓ Detected {other_count} other USB serial device(s)")
                    
                    if esp32_count > 1:
                        print("💡 Multiple ESP32 devices detected - will show selection menu on connect")
                else:
                    current_platform = platform.system().lower()
                    print("⚠️  No devices detected")
                    if current_platform == "linux":
                        print("💡 Linux: Check permissions and device connection")
            
            available_files, missing_files = self.check_local_files()
            print(f"📁 Local files: {len(available_files)}/{len(self.REQUIRED_AUDIO_FILES)} available")
            
            if missing_files:
                print(f"⚠️  Missing files: {', '.join(missing_files)}")
            
            print("\nOptions:")
            if not self.is_connected:
                print("  1. Connect to device")
            else:
                print("  1. Disconnect from device")
                print("  2. List files on device")
                print("  3. Transfer all required files (skip existing)")
                print("  4. Force transfer all files (overwrite existing)")
                print("  5. Transfer single file")
                print("  6. Transfer all files (fast!)")
                print("  7. Transfer single file (fast transfer)")
            
            if missing_files and self.server_url:
                print("  8. Download missing files from server")
            
            print("  l. List available ports")
            print("  0. Exit")
            
            try:
                choice = input("\nEnter your choice: ").strip()
                
                if choice == '0':
                    break
                elif choice == '1':
                    if not self.is_connected:
                        self.connect()
                    else:
                        self.disconnect()
                elif choice == '2' and self.is_connected:
                    files = self.list_device_files()
                    if files:
                        print(f"\nFiles on device ({len(files)}):")
                        for f in files:
                            status = "✅ Required" if f in self.REQUIRED_AUDIO_FILES else "📄 Other"
                            print(f"  {status} {f}")
                elif choice == '3' and self.is_connected:
                    if available_files:
                        self.transfer_required_files(skip_existing=True)
                    else:
                        print("❌ No local audio files available")
                elif choice == '4' and self.is_connected:
                    if available_files:
                        print("🔄 Force transferring all files (will overwrite existing files)...")
                        self.transfer_required_files(skip_existing=False)
                    else:
                        print("❌ No local audio files available")
                elif choice == '5' and self.is_connected:
                    if available_files:
                        print("\nAvailable files:")
                        for i, f in enumerate(available_files, 1):
                            print(f"  {i}. {f}")
                        
                        try:
                            file_choice = int(input("Enter file number: ")) - 1
                            if 0 <= file_choice < len(available_files):
                                filename = available_files[file_choice]
                                file_path = self.audio_dir / filename
                                self.transfer_file_to_device(file_path)
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No local audio files available")
                elif choice == '6' and self.is_connected:
                    if available_files:
                        print("🔄 Fast transfer of all files (faster, waits for device acks)...")
                        successful = 0
                        failed = 0
                        for filename in self.REQUIRED_AUDIO_FILES:
                            if filename in available_files:
                                file_path = self.audio_dir / filename
                                if self.transfer_file_fast(file_path):
                                    successful += 1
                                else:
                                    failed += 1
                        print(f"✅ Fast transfer complete: {successful} succeeded, {failed} failed")
                    else:
                        print("❌ No local audio files available")
                elif choice == '7' and self.is_connected:
                    if available_files:
                        print("\nAvailable files:")
                        for i, f in enumerate(available_files, 1):
                            print(f"  {i}. {f}")
                        
                        try:
                            file_choice = int(input("Enter file number: ")) - 1
                            if 0 <= file_choice < len(available_files):
                                filename = available_files[file_choice]
                                file_path = self.audio_dir / filename
                                self.transfer_file_fast(file_path)
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No local audio files available")
                elif choice == '8' and missing_files and self.server_url:
                    print(f"\nDownloading {len(missing_files)} missing files...")
                    for filename in missing_files:
                        self.download_audio_from_server(filename)
                elif choice == 'l':
                    self.list_available_ports()
                else:
                    print("❌ Invalid option or device not connected")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def set_transfer_speed(self, mode: str = "normal"):
        """
        Set transfer speed mode
        
        Args:
            mode: "normal", "fast", "ultra", or "ludicrous"
        """
        if mode == "normal":
            self.write_chunk_size = self.WRITE_CHUNK_SIZE  # 64 bytes
            self.write_delay = self.WRITE_DELAY            # 2ms
            self.file_chunk_size = self.FILE_CHUNK_SIZE    # 1024 bytes
            speed_desc = "Normal (64B writes, 2.0ms delay, 1KB chunks)"
        elif mode == "fast":
            self.write_chunk_size = 256     # 4x larger writes
            self.write_delay = 0.001        # 50% faster timing
            self.file_chunk_size = 2048     # 2x larger chunks
            speed_desc = "Fast (256B writes, 1.0ms delay, 2KB chunks)"
        elif mode == "ultra":
            self.write_chunk_size = 512     # 8x larger writes  
            self.write_delay = 0.0005       # 75% faster timing
            self.file_chunk_size = 4096     # 4x larger chunks
            speed_desc = "Ultra (512B writes, 0.5ms delay, 4KB chunks)"
        elif mode == "ludicrous":
            self.write_chunk_size = 1024    # 16x larger writes
            self.write_delay = 0.0001       # 95% faster timing
            self.file_chunk_size = 8192     # 8x larger chunks
            speed_desc = "Ludicrous (1KB writes, 0.1ms delay, 8KB chunks) ⚠️ Experimental!"
        else:
            self.log(f"Unknown speed mode: {mode}", "ERROR")
            return
        
        self.log(f"Transfer speed set to {mode} mode: {speed_desc}", "SUCCESS")
    
    def transfer_file_fast(self, file_path: Path, show_progress: bool = True) -> bool:
        """
        Transfer a file with minimal delays (much faster than original)
        Uses continuous data flow that the device firmware expects
        """
        if not self.is_connected:
            self.log("Device not connected", "ERROR")
            return False
        
        if not file_path.exists():
            self.log(f"File not found: {file_path}", "ERROR")
            return False
        
        # Read file data
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
        except Exception as e:
            self.log(f"Failed to read file {file_path}: {e}", "ERROR")
            return False
        
        filename = file_path.name
        file_size = len(file_data)
        file_crc = self.calculate_crc32(file_data)
        
        self.log(f"Starting fast transfer: {filename} ({file_size:,} bytes, CRC32: {file_crc:08x})", "TRANSFER")
        
        # Send initial download command
        download_cmd = {
            "command": "download_file",
            "filename": filename,
            "size": file_size,
            "chunk_size": self.file_chunk_size,
            "crc": file_crc
        }
        
        if not self._send_command(download_cmd):
            return False
        
        # Brief pause for device to process command
        time.sleep(0.1)
        
        # Setup progress tracking
        if show_progress and HAS_TQDM:
            progress_bar = tqdm(
                total=file_size,
                desc=f"Transferring {filename} (fast)",
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                ncols=80
            )
        else:
            progress_bar = None
        
        try:
            bytes_sent = 0
            
            while bytes_sent < file_size:
                # Calculate chunk size
                remaining = file_size - bytes_sent
                chunk_size = min(self.file_chunk_size, remaining)
                chunk_data = file_data[bytes_sent:bytes_sent + chunk_size]
                
                # Send chunk in small pieces with minimal delays
                chunk_pos = 0
                while chunk_pos < len(chunk_data):
                    piece_size = min(self.write_chunk_size, len(chunk_data) - chunk_pos)
                    piece = chunk_data[chunk_pos:chunk_pos + piece_size]
                    
                    try:
                        self.serial_port.write(piece)
                        self.serial_port.flush()
                        chunk_pos += piece_size
                        
                        # Minimal delay - just enough for device to process
                        time.sleep(0.0001)  # 0.1ms instead of 2ms (20x faster!)
                        
                    except Exception as e:
                        self.log(f"Write error at position {bytes_sent + chunk_pos}: {e}", "ERROR")
                        if progress_bar:
                            progress_bar.close()
                        return False
                
                bytes_sent += chunk_size
                
                # Update progress
                if progress_bar:
                    progress_bar.update(chunk_size)
                elif show_progress:
                    percent = (bytes_sent / file_size) * 100
                    print(f"\r🔄 Progress: {percent:.1f}% ({bytes_sent:,}/{file_size:,} bytes)", end='', flush=True)
            
            if progress_bar:
                progress_bar.close()
            elif show_progress:
                print()  # New line after progress
            
            # Wait a moment for device to finish processing
            time.sleep(0.5)
            
            self.log(f"Fast transfer completed: {filename}", "SUCCESS")
            return True
            
        except Exception as e:
            if progress_bar:
                progress_bar.close()
            self.log(f"Transfer failed: {e}", "ERROR")
            return False


def main():
    """Command line interface"""
    parser = argparse.ArgumentParser(
        description="AutoTQ Device Programmer - Transfer audio files to ESP32-S3 devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_device_programmer.py                          # Interactive mode
  python autotq_device_programmer.py --port COM3              # Specific port (Windows)
  python autotq_device_programmer.py --port /dev/ttyUSB0      # Specific port (Linux)
  python autotq_device_programmer.py --transfer-all           # Auto-transfer all files
  python autotq_device_programmer.py --transfer-all --force   # Force re-transfer all files
  python autotq_device_programmer.py --transfer-all --fast    # Fast transfer mode
  python autotq_device_programmer.py --ultra                  # Enable ultra-fast mode
  python autotq_device_programmer.py --list-ports             # List available ports
  python autotq_device_programmer.py --audio-dir ./downloads  # Custom audio directory

Linux users:
  Make sure you're in the dialout group: sudo usermod -a -G dialout $USER
  Then logout and login again, or run: newgrp dialout
  Check connected devices: lsusb | grep -E '(ESP32|CP210|CH340|FT232)'
        """
    )
    
    parser.add_argument("--port", help="Serial port (e.g., COM3, /dev/ttyUSB0)")
    parser.add_argument("--audio-dir", default="audio", 
                       help="Directory containing audio files (default: audio)")
    parser.add_argument("--server-url", 
                       help="Server URL to download audio files from")
    parser.add_argument("--transfer-all", action="store_true",
                       help="Connect and transfer all required files automatically")
    parser.add_argument("--force", action="store_true",
                       help="Force transfer files even if they already exist on device")
    parser.add_argument("--fast", action="store_true",
                       help="Enable fast transfer mode (larger chunks, reduced delays)")
    parser.add_argument("--ultra", action="store_true", 
                       help="Enable ultra-fast transfer mode (maximum speed, may be unstable)")
    parser.add_argument("--ludicrous", action="store_true",
                       help="Enable ludicrous speed mode (experimental, maximum performance)")
    parser.add_argument("--response-based", action="store_true",
                       help="Use response-based flow control (wait for device acks instead of delays)")
    parser.add_argument("--list-ports", action="store_true",
                       help="List available serial ports and exit")
    parser.add_argument("--no-progress", action="store_true",
                       help="Disable progress bars")
    
    args = parser.parse_args()
    
    # List ports and exit
    if args.list_ports:
        print("🔍 Scanning for available AutoTQ/ESP32 devices...")
        programmer = AutoTQDeviceProgrammer()
        ports = programmer.list_available_ports()
        
        if ports:
            current_platform = platform.system().lower()
            print(f"\n📟 Available serial ports ({current_platform}):")
            
            esp32_ports = [(port, desc) for port, desc in ports if '🎯' in desc]
            other_ports = [(port, desc) for port, desc in ports if '🎯' not in desc]
            
            if esp32_ports:
                print("\n  ESP32/AutoTQ devices (recommended):")
                for port, desc in esp32_ports:
                    print(f"    {desc}")
            
            if other_ports:
                print("\n  Other USB serial devices:")
                for port, desc in other_ports:
                    print(f"    {desc}")
            
            print(f"\n💡 Use --port <device> to specify a particular device")
            if current_platform == "linux":
                print("💡 On Linux, ensure you're in the dialout group for access")
        else:
            print("\n❌ No serial ports found")
            if platform.system().lower() == "linux":
                print("💡 Check if device is connected: lsusb | grep -E '(ESP32|CP210|CH340|FT232)'")
                print("💡 Ensure user permissions: sudo usermod -a -G dialout $USER")
        return
    
    # Validate arguments - remove the firmware_only and audio_only validation
    if args.fast and args.ultra:
        print("❌ Cannot specify both --fast and --ultra")
        sys.exit(1)
    
    # Disable tqdm if requested
    if args.no_progress:
        global HAS_TQDM
        HAS_TQDM = False
    
    # Determine speed mode
    speed_mode = "normal"
    if args.ultra:
        speed_mode = "ultra"
    elif args.fast:
        speed_mode = "fast"
    
    # Initialize programmer
    programmer = AutoTQDeviceProgrammer(
        port=args.port,
        audio_dir=args.audio_dir,
        server_url=args.server_url
    )
    
    # Set speed mode if ultra was requested
    if speed_mode != "normal":
        programmer.set_transfer_speed(speed_mode)
    
    try:
        if args.transfer_all:
            # Automatic mode
            if programmer.connect():
                available, missing = programmer.check_local_files()
                if available:
                    # Use force flag to determine whether to skip existing files
                    skip_existing = not args.force
                    if args.force:
                        programmer.log("Force mode enabled - will overwrite existing files", "WARNING")
                    
                    # Use response-based transfer if requested
                    if args.response_based:
                        programmer.log("Using response-based transfer (faster!)", "SUCCESS")
                        successful = 0
                        failed = 0
                        for filename in programmer.REQUIRED_AUDIO_FILES:
                            if filename in available:
                                file_path = programmer.audio_dir / filename
                                if programmer.transfer_file_fast(file_path):
                                    successful += 1
                                else:
                                    failed += 1
                        programmer.log(f"Fast transfer complete: {successful} succeeded, {failed} failed", 
                                     "SUCCESS" if failed == 0 else "WARNING")
                    else:
                        programmer.transfer_required_files(skip_existing=skip_existing)
                else:
                    programmer.log("No local audio files found", "ERROR")
                programmer.disconnect()
            else:
                programmer.log("Failed to connect to device", "ERROR")
                sys.exit(1)
        else:
            # Interactive mode
            programmer.interactive_menu()
    
    except KeyboardInterrupt:
        programmer.log("Operation cancelled by user", "WARNING")
    finally:
        if programmer.is_connected:
            programmer.disconnect()


if __name__ == "__main__":
    main() 