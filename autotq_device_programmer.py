#!/usr/bin/env python3
"""
AutoTQ Device Programmer - Direct ESP32-S3 Audio File Transfer
Connects to AutoTQ devices via USB serial and transfers audio files
using the optimized protocol based on JavaScript implementation.
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

# ANSI color codes for clear output formatting
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class AutoTQDeviceProgrammer:
    """
    AutoTQ Device Programmer for ESP32-S3 devices.
    Optimized audio file transfer system based on JavaScript implementation.
    """
    
    # Required audio files for AutoTQ devices
    REQUIRED_AUDIO_FILES = [
        'tightenStrap.wav',
        'bleedingContinues.wav', 
        'pullStrapTighter.wav',
        'inflating.wav',
        'timeRemaining.wav',
        'reattachStrap.wav'
    ]
    
    # Serial communication parameters - optimized for reliability
    SERIAL_PARAMS = {
        'baudrate': 115200,
        'bytesize': serial.EIGHTBITS,
        'parity': serial.PARITY_NONE,
        'stopbits': serial.STOPBITS_ONE,
        'xonxoff': False,
        'rtscts': False,
        'dsrdtr': False,
        'timeout': 5
    }
    
    # Transfer parameters - Conservative settings to prevent CRC failures
    CHUNK_SIZE = 1024  # Small chunks to avoid overwhelming device
    SEND_SIZE = 128    # Small pieces for reliable transfer
    PIECE_DELAY = 0.005  # 5ms delay for device flash write processing
    
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
        
        # Transfer speed parameters (instance attributes for compatibility)
        self.write_chunk_size = self.SEND_SIZE
        self.write_delay = self.PIECE_DELAY
        self.file_chunk_size = self.CHUNK_SIZE
        
        # Threading for reading responses - optimized like JavaScript
        self.reader_thread: Optional[threading.Thread] = None
        self.running = False
        self.device_responses = []
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
        """Log messages with timestamp like JavaScript."""
        timestamp = time.strftime("%H:%M:%S")
        if level == "ERROR":
            color = Colors.FAIL
            prefix = "❌"
        elif level == "WARNING":  
            color = Colors.WARNING
            prefix = "⚠️"
        elif level == "SUCCESS":
            color = Colors.OKGREEN
            prefix = "✅"
        elif level == "TRANSFER":
            color = Colors.OKCYAN
            prefix = "📤"
        elif level == "DEVICE":
            color = Colors.OKBLUE
            prefix = "📟"
        elif level == "PROGRESS":
            color = Colors.OKCYAN
            prefix = "🔄"
        else:
            color = Colors.OKCYAN
            prefix = "📱"
            
        print(f"{color}[{timestamp}] {prefix} {message}{Colors.ENDC}")
        
    def calculate_crc32(self, data: bytes) -> int:
        """Calculate CRC32 checksum for data integrity verification."""
        return zlib.crc32(data) & 0xffffffff

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
            
            if len(esp32_ports) == 1:
                selected_port = esp32_ports[0][0]
                self.log(f"Auto-selected ESP32-S3 device: {esp32_ports[0][1]}", "SUCCESS")
                return selected_port
            else:
                # Multiple ESP32 devices or mixed devices - require manual selection
                self.log("Multiple compatible devices found - manual selection required", "WARNING")
                return None
        else:
            self.log("No compatible devices detected", "ERROR")
            return None

    def connect(self) -> bool:
        """Establish serial connection with the device like JavaScript."""
        if not self.port_name:
            self.port_name = self.auto_detect_port()
            if not self.port_name:
                self.log("No device port specified and auto-detection failed", "ERROR")
                return False
                
        try:
            self.log(f"🔗 Connecting to {self.port_name}...")
            self.serial_port = serial.Serial(self.port_name, **self.SERIAL_PARAMS)
            time.sleep(2)  # Allow connection to stabilize
            
            # Start reader thread like JavaScript
            self.running = True
            self.reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self.reader_thread.start()
            
            self.is_connected = True
            self.log(f"✅ Connected to {self.port_name}")
            return True
            
        except serial.SerialException as e:
            self.log(f"Failed to connect to {self.port_name}: {e}", "ERROR")
            return False
            
    def _serial_reader(self):
        """Background thread to read serial data like JavaScript readLoop."""
        buffer = ""
        
        while self.running and self.serial_port and self.serial_port.is_open:
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
                                
                time.sleep(0.01)
                
            except Exception as e:
                if self.running:
                    self.log(f"Serial read error: {e}", "ERROR")
                break
                
    def _process_device_message(self, line: str):
        """Process device messages like JavaScript processDeviceMessage."""
        try:
            response = json.loads(line)
            self.log(f"📱 Device: {json.dumps(response)}")
            
            with self.response_lock:
                self.device_responses.append({
                    'data': response,
                    'timestamp': time.time(),
                    'type': 'json'
                })
                
        except json.JSONDecodeError:
            # Non-JSON message - device debug/diagnostic messages
            if len(line) > 0 and not line.startswith('[Audio') and not line.startswith('[Timing]'):
                self.log(f"📱 Device: {line}")
                
                with self.response_lock:
                    self.device_responses.append({
                        'data': line,
                        'timestamp': time.time(),
                        'type': 'text'
                    })

    def send_command(self, command: Dict[str, Any]) -> bool:
        """Send JSON command to device like JavaScript sendCommand."""
        if not self.serial_port or not self.serial_port.is_open:
            self.log("No serial connection!", "ERROR")
            return False
            
        try:
            command_json = json.dumps(command) + '\n'
            self.serial_port.write(command_json.encode('utf-8'))
            self.log(f"📤 Sent: {json.dumps(command)}")
            return True
        except Exception as e:
            self.log(f"Failed to send command: {e}", "ERROR")
            return False

    def _send_command(self, command: Dict[str, Any]) -> bool:
        """Compatibility wrapper for send_command"""
        return self.send_command(command)
            
    def wait_for_response(self, response_type: str, timeout: float = 15.0) -> Optional[Dict]:
        """Wait for specific device response like JavaScript."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.response_lock:
                # Check recent responses
                for response in self.device_responses[-10:]:
                    if response['type'] == 'json':
                        data = response['data']
                        
                        if response_type == 'binary_transfer_ready':
                            if (data.get('command') == 'download_file' and 
                                data.get('response') == 'binary_transfer_ready'):
                                return data
                                
                        elif response_type == 'chunk_received':
                            if data.get('response') == 'chunk_received':
                                return data
                                
                        elif response_type == 'binary_transfer_complete':
                            if data.get('response') == 'binary_transfer_complete':
                                return data
                                
                        elif response_type == 'binary_transfer_aborted':
                            if data.get('response') == 'binary_transfer_aborted':
                                return data
                                
            time.sleep(0.1)
            
        return None

    def disconnect(self):
        """Clean up and disconnect from device."""
        self.running = False
        
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
            
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.is_connected = False
            self.log("🔌 Serial connection closed")

    def transfer_file_to_device(self, file_path: Path, show_progress: bool = True) -> bool:
        """
        Transfer a single audio file to the device using optimized JavaScript-style protocol
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
        
        self.log(f"📤 Starting binary transfer of {filename}", "TRANSFER")
        self.log(f"📊 File size: {file_size} bytes ({file_size / 1024:.1f} KB)")
        self.log(f"🔐 CRC32: 0x{file_crc:08X}")
        
        # Step 1: Send initial download command like JavaScript
        start_command = {
            "command": "download_file",
            "filename": filename,
            "size": file_size,
            "chunk_size": self.CHUNK_SIZE,
            "crc32": file_crc
        }
        
        if not self.send_command(start_command):
            return False
            
        self.log("✅ Successfully sent download_file command to device")
        
        # Step 2: Wait for device ready signal like JavaScript
        self.log("⏳ Waiting for device ready signal...")
        ready_response = self.wait_for_response('binary_transfer_ready', timeout=10.0)
        
        if not ready_response:
            self.log("❌ Device did not signal ready for binary transfer!", "ERROR")
            return False
            
        self.log("✅ Device ready for binary transfer, sending data...")
        time.sleep(0.1)  # Small delay like JavaScript
        
        # Step 3: Send file in chunks like JavaScript
        sent_bytes = 0
        chunk_count = 0
        
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
            while sent_bytes < file_size:
                current_chunk_size = min(self.CHUNK_SIZE, file_size - sent_bytes)
                chunk_data = file_data[sent_bytes:sent_bytes + current_chunk_size]
                chunk_count += 1
                
                self.log(f"📦 Sending chunk {chunk_count}: {current_chunk_size} bytes")
                
                # Send chunk in small pieces like JavaScript to avoid buffer overflow
                for i in range(0, len(chunk_data), self.SEND_SIZE):
                    piece = chunk_data[i:i + self.SEND_SIZE]
                    try:
                        bytes_written = self.serial_port.write(piece)
                        if self.PIECE_DELAY > 0:
                            time.sleep(self.PIECE_DELAY)
                    except Exception as e:
                        self.log(f"Failed to send data piece: {e}", "ERROR")
                        if progress_bar:
                            progress_bar.close()
                        return False
                        
                sent_bytes += current_chunk_size
                percent = round((sent_bytes / file_size) * 100)
                
                # Update progress
                if progress_bar:
                    progress_bar.update(current_chunk_size)
                else:
                    self.log(f"📊 Progress: {percent}% ({sent_bytes}/{file_size} bytes)")
                
                # Check for abort signals
                abort_response = self.wait_for_response('binary_transfer_aborted', timeout=0.1)
                if abort_response:
                    reason = abort_response.get('reason', 'Unknown')
                    self.log(f"❌ Transfer aborted by device: {reason}", "ERROR")
                    if progress_bar:
                        progress_bar.close()
                    return False
                    
            if progress_bar:
                progress_bar.close()
                
            self.log("✅ Binary transfer completed, waiting for device processing...")
            
            # Step 4: Wait for completion like JavaScript
            processing_time = max(2.0, min(8.0, file_size / 1024 * 0.1))  # 2-8 seconds based on file size
            self.log(f"⏳ Allowing {processing_time:.1f}s for device to process file...")
            
            # Check for both completion and abort responses
            start_time = time.time()
            completion_response = None
            while time.time() - start_time < processing_time + 5:
                completion_response = self.wait_for_response('binary_transfer_complete', timeout=0.5)
                if completion_response:
                    break
                    
                abort_response = self.wait_for_response('binary_transfer_aborted', timeout=0.5)
                if abort_response:
                    reason = abort_response.get('reason', 'Unknown')
                    self.log(f"❌ Transfer aborted by device: {reason}", "ERROR")
                    return False
            
            if completion_response:
                crc_check = completion_response.get('crc_check', None)
                
                # Arduino may not send explicit CRC status but still indicate success
                if crc_check == 'passed':
                    self.log("✅ CRC verification passed!")
                    self.log(f"✅ Successfully transferred {filename}", "SUCCESS")
                    return True
                elif crc_check == 'failed':
                    self.log(f"❌ CRC verification failed: {crc_check}", "ERROR")
                    return False
                else:
                    # Arduino sent completion but no explicit CRC status - assume success
                    self.log("✅ Transfer completed (CRC verification not reported by device)")
                    self.log(f"✅ Successfully transferred {filename}", "SUCCESS")
                    return True
            else:
                self.log("⚠️ No completion response received within timeout", "WARNING")
                return False
                
        except Exception as e:
            if progress_bar:
                progress_bar.close()
            self.log(f"Transfer failed: {e}", "ERROR")
            return False

    def transfer_required_files(self, skip_existing: bool = True) -> Tuple[int, int]:
        """
        Transfer all required audio files to the device like JavaScript downloadAllAudioFiles
        
        Returns:
            Tuple of (successful_transfers, failed_transfers)
        """
        if not self.is_connected:
            self.log("Device not connected", "ERROR")
            return 0, len(self.REQUIRED_AUDIO_FILES)

        results = {}
        success_count = 0
        failure_count = 0
        
        self.log("📥 Starting download of all required audio files...")
        self.log("🔍 Will transfer files from local storage to device...")
        
        for i, filename in enumerate(self.REQUIRED_AUDIO_FILES):
            file_path = self.audio_dir / filename
            
            if file_path.exists():
                try:
                    self.log(f"📥 Processing {filename} ({i + 1}/{len(self.REQUIRED_AUDIO_FILES)})...")
                    
                    # Transfer file to device
                    success = self.transfer_file_to_device(file_path)
                    results[filename] = success
                    
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1
                        
                    # Add delay between files like JavaScript
                    if i < len(self.REQUIRED_AUDIO_FILES) - 1:
                        self.log("⏸️ Waiting 2 seconds before next file...")
                        time.sleep(2)
                        
                except Exception as e:
                    self.log(f"❌ Exception during transfer of {filename}: {e}", "ERROR")
                    results[filename] = False
                    failure_count += 1
            else:
                self.log(f"❌ {filename} not available locally!", "ERROR")
                results[filename] = False
                failure_count += 1
                
        # Final status like JavaScript
        final_message = f"Audio transfer complete: {success_count} succeeded, {failure_count} failed"
        self.log(final_message, "SUCCESS" if failure_count == 0 else "WARNING")
        
        return success_count, failure_count

    def list_device_files(self) -> Optional[List[str]]:
        """Request list of files from device"""
        if not self.is_connected:
            return None
            
        self.log("🔄 Requesting file list from device...")
        if self.send_command({"command": "list_files"}):
            time.sleep(2)  # Allow time for response
            return []  # Would need to parse device response
        return None

    def check_local_files(self) -> Tuple[List[str], List[str]]:
        """Check which required files are available locally"""
        available = []
        missing = []
        
        for filename in self.REQUIRED_AUDIO_FILES:
            file_path = self.audio_dir / filename
            if file_path.exists():
                available.append(filename)
            else:
                missing.append(filename)
        
        return available, missing

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

    def set_transfer_speed(self, mode: str = "normal"):
        """
        Set transfer speed parameters 
        
        Args:
            mode: "fast", "normal", or "slow"
        """
        if mode == "fast":
            # Moderately fast settings - still reliable
            self.CHUNK_SIZE = 2048
            self.SEND_SIZE = 256
            self.PIECE_DELAY = 0.002
            self.log("🏭 Production mode: Using moderately fast settings (2KB chunks, 256B pieces, 2ms delay)", "SUCCESS")
        elif mode == "slow":
            # Very conservative settings for problematic devices
            self.CHUNK_SIZE = 512
            self.SEND_SIZE = 64
            self.PIECE_DELAY = 0.010
            self.log("🐌 Conservative mode: Using very slow, ultra-safe transfer settings", "SUCCESS")
        else:
            # Normal mode - conservative but reasonable
            self.CHUNK_SIZE = 1024
            self.SEND_SIZE = 128
            self.PIECE_DELAY = 0.005
            self.log("⚖️ Normal mode: Using conservative transfer settings", "SUCCESS")
        
        # Update instance attributes for compatibility
        self.write_chunk_size = self.SEND_SIZE
        self.write_delay = self.PIECE_DELAY
        self.file_chunk_size = self.CHUNK_SIZE

    def transfer_file_fast(self, file_path: Path, show_progress: bool = True) -> bool:
        """
        Fast transfer method - compatibility wrapper
        """
        return self.transfer_file_to_device(file_path, show_progress)

    def interactive_menu(self):
        """Interactive menu for manual device operations"""
        if not self.is_connected:
            self.log("Not connected to device", "ERROR")
            return
            
        while True:
            print(f"\n{Colors.WARNING}🎯 Available Operations:{Colors.ENDC}")
            print("1. 📥 Transfer all required files")
            print("2. 📁 Transfer specific file")
            print("3. 📋 Request device file list")
            print("4. 🔍 Request missing audio files")
            print("5. 🏓 Test device communication")
            print("6. 🚪 Exit")
            
            try:
                choice = input(f"\n{Colors.OKCYAN}Select operation (1-6): {Colors.ENDC}").strip()
                
                if choice == '1':
                    self.transfer_required_files(skip_existing=False)
                    
                elif choice == '2':
                    available, missing = self.check_local_files()
                    if not available:
                        print(f"{Colors.FAIL}No audio files found locally!{Colors.ENDC}")
                        continue
                        
                    print(f"\n{Colors.WARNING}📂 Available files:{Colors.ENDC}")
                    for i, filename in enumerate(available):
                        print(f"  {i+1}. {filename}")
                        
                    try:
                        file_choice = int(input("Select file number: ")) - 1
                        if 0 <= file_choice < len(available):
                            filename = available[file_choice]
                            file_path = self.audio_dir / filename
                            self.transfer_file_to_device(file_path)
                        else:
                            print(f"{Colors.FAIL}Invalid file selection!{Colors.ENDC}")
                    except ValueError:
                        print(f"{Colors.FAIL}Invalid input!{Colors.ENDC}")
                        
                elif choice == '3':
                    self.list_device_files()
                    
                elif choice == '4':
                    self.send_command({"command": "list_missing_audio"})
                    time.sleep(2)  # Allow time for response
                    
                elif choice == '5':
                    test_command = {"command": "ping", "timestamp": int(time.time())}
                    self.send_command(test_command)
                    time.sleep(1)
                    
                elif choice == '6':
                    break
                    
                else:
                    print(f"{Colors.FAIL}Invalid choice!{Colors.ENDC}")
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.WARNING}Operation interrupted by user.{Colors.ENDC}")
                break
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")


def main():
    """Command line interface"""
    parser = argparse.ArgumentParser(
        description="AutoTQ Device Programmer - Transfer audio files to ESP32-S3 devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_device_programmer.py                          # Auto-detect device and run interactive menu
  python autotq_device_programmer.py --port COM3              # Use specific COM port
  python autotq_device_programmer.py --transfer-all           # Auto-transfer all required files
  python autotq_device_programmer.py --audio-dir ./audio      # Use custom audio directory
  python autotq_device_programmer.py --list-ports             # Show available serial ports

Transfer Modes:
  --fast                                                       # Use fastest transfer settings
  --normal                                                     # Use balanced settings (default)
  --slow                                                       # Use conservative settings
        """
    )
    
    parser.add_argument("--port", "-p", 
                       help="Serial port (e.g., COM3, /dev/ttyUSB0)")
    parser.add_argument("--audio-dir", "-a", default="audio",
                       help="Directory containing audio files (default: ./audio)")
    parser.add_argument("--server-url", "-s",
                       help="Server URL for downloading audio files")
    parser.add_argument("--transfer-all", action="store_true",
                       help="Automatically transfer all required files and exit")
    parser.add_argument("--list-ports", action="store_true",
                       help="List available serial ports and exit")
    parser.add_argument("--fast", action="store_true",
                       help="Use fastest transfer settings")
    parser.add_argument("--slow", action="store_true",
                       help="Use slowest/safest transfer settings")
    
    args = parser.parse_args()
    
    if args.list_ports:
        programmer = AutoTQDeviceProgrammer()
        ports = programmer.list_available_ports()
        if ports:
            print("\n📟 Available serial ports:")
            for port, desc in ports:
                print(f"  {desc}")
        else:
            print("❌ No compatible devices found")
        return 0
    
    try:
        # Initialize programmer
        programmer = AutoTQDeviceProgrammer(
            port=args.port,
            audio_dir=args.audio_dir,
            server_url=args.server_url
        )
        
        # Set transfer speed
        if args.fast:
            programmer.set_transfer_speed("fast")
        elif args.slow:
            programmer.set_transfer_speed("slow")
        
        # Connect to device
        if not programmer.connect():
            print(f"{Colors.FAIL}❌ Failed to connect to device{Colors.ENDC}")
            return 1
        
        try:
            if args.transfer_all:
                # Auto-transfer mode
                successful, failed = programmer.transfer_required_files(skip_existing=False)
                if failed == 0:
                    print(f"{Colors.OKGREEN}✅ All files transferred successfully!{Colors.ENDC}")
                    return 0
                else:
                    print(f"{Colors.FAIL}❌ {failed} files failed to transfer{Colors.ENDC}")
                    return 1
            else:
                # Interactive mode
                print(f"\n{Colors.HEADER}🎵 AutoTQ Device Programmer - Interactive Mode{Colors.ENDC}")
                programmer.interactive_menu()
                
        finally:
            programmer.disconnect()
            
        return 0
        
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}⚠️ Program interrupted by user{Colors.ENDC}")
        return 1
    except Exception as e:
        print(f"{Colors.FAIL}❌ Unexpected error: {e}{Colors.ENDC}")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 