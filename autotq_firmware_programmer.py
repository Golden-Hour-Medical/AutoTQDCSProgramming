#!/usr/bin/env python3
"""
AutoTQ Firmware Programmer - ESP32-S3 Firmware Flashing Tool
Automatically locates esptool, detects ESP32-S3 devices, and programs firmware.
"""

import os
import sys
import json
import time
import argparse
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import shutil
import platform

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


class AutoTQFirmwareProgrammer:
    """AutoTQ Firmware Programmer for ESP32-S3 devices"""
    
    # ESP32-S3 specific settings
    CHIP_TYPE = "esp32s3"
    BAUD_RATE = 921600  # High speed for firmware flashing
    ERASE_BAUD_RATE = 921600  # High speed for erase operations too
    FLASH_SIZE = "4MB"
    FLASH_MODE = "dio"
    FLASH_FREQ = "80m"
    
    @classmethod
    def get_platform_specific_paths(cls):
        """Get platform-specific esptool search paths"""
        current_platform = platform.system().lower()
        
        base_paths = [
            # Python package installations (cross-platform)
            "esptool.py",
            "esptool",
            # Common pip install locations (cross-platform)
            os.path.expanduser("~/.local/bin/esptool.py"),
            os.path.expanduser("~/.local/bin/esptool"),
            # ESP-IDF installations (cross-platform)
            os.path.expanduser("~/esp/esp-idf/components/esptool_py/esptool/esptool.py"),
            os.path.expanduser("~/.espressif/python_env/*/bin/esptool.py"),
            # Conda installations (cross-platform)
            os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin", "esptool.py") if os.environ.get("CONDA_PREFIX") else None,
        ]
        
        if current_platform == "windows":
            windows_paths = [
                # Python Scripts directory (Windows)
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Python", "Python*", "Scripts", "esptool.py"),
                # Arduino ESP32 core installations (Windows)
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Arduino15", "packages", "esp32", "tools", "esptool_py", "*", "esptool.py"),
                # Windows ESP-IDF
                os.path.expanduser("~/.espressif/python_env/*/Scripts/esptool.py"),
            ]
            base_paths.extend(windows_paths)
            
        elif current_platform == "linux":
            linux_paths = [
                # System-wide installations (Linux)
                "/usr/local/bin/esptool.py",
                "/usr/bin/esptool.py",
                "/opt/local/bin/esptool.py",
                # Package manager installations (Linux)
                "/usr/share/esptool/esptool.py",
                "/opt/esptool/esptool.py",
                # Snap installations (Linux)
                "/snap/bin/esptool",
                "/var/lib/snapd/snap/bin/esptool",
                # Flatpak installations (Linux)
                os.path.expanduser("~/.local/share/flatpak/exports/bin/esptool"),
                "/var/lib/flatpak/exports/bin/esptool",
                # AppImage installations (Linux)
                os.path.expanduser("~/Applications/esptool"),
                "/opt/appimages/esptool",
                # Custom installations (Linux)
                "/usr/local/share/esptool/esptool.py",
                # Development installations (Linux)
                os.path.expanduser("~/dev/esp-idf/components/esptool_py/esptool/esptool.py"),
                os.path.expanduser("~/esp32/esp-idf/components/esptool_py/esptool/esptool.py"),
            ]
            base_paths.extend(linux_paths)
            
        elif current_platform == "darwin":  # macOS
            macos_paths = [
                # Homebrew installations (macOS)
                "/usr/local/bin/esptool.py",
                "/opt/homebrew/bin/esptool.py",
                "/usr/local/Cellar/esptool/*/bin/esptool.py",
                "/opt/homebrew/Cellar/esptool/*/bin/esptool.py",
                # MacPorts installations (macOS)
                "/opt/local/bin/esptool.py",
                # Application installations (macOS)
                "/Applications/Arduino.app/Contents/Java/hardware/esp32/*/tools/esptool_py/*/esptool.py",
            ]
            base_paths.extend(macos_paths)
        
        # Filter out None values
        return [path for path in base_paths if path is not None]
    
    # Common esptool locations (will be populated by get_platform_specific_paths)
    ESPTOOL_SEARCH_PATHS = []
    
    def __init__(self, firmware_dir: str = None, port: str = None):
        """
        Initialize the AutoTQ Firmware Programmer
        
        Args:
            firmware_dir: Directory containing firmware files (default: ./firmware)
            port: Serial port (if None, will auto-detect)
        """
        # Initialize platform-specific search paths
        self.ESPTOOL_SEARCH_PATHS = self.get_platform_specific_paths()
        
        self.firmware_dir = Path(firmware_dir) if firmware_dir else Path("firmware")
        self.port_name = port
        self.esptool_path = None
        self.latest_firmware = None
        
        current_platform = platform.system()
        print(f"🔧 AutoTQ Firmware Programmer initialized ({current_platform})")
        print(f"📁 Firmware directory: {self.firmware_dir.absolute()}")
        
        # Find esptool
        self.find_esptool()
        
        # Find latest firmware
        self.find_latest_firmware()
    
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
            "FLASH": "⚡ "
        }
        emoji = emoji_map.get(level, "")
        print(f"[{timestamp}] {emoji} {message}")
    
    def find_esptool(self) -> Optional[str]:
        """Find esptool.py on the system"""
        self.log("Searching for esptool.py...")
        
        # First try to find esptool as a Python module (preferred method)
        try:
            result = subprocess.run([sys.executable, "-m", "esptool", "version"], 
                                  capture_output=True, timeout=10)
            if result.returncode == 0:
                self.esptool_path = f"{sys.executable} -m esptool"
                self.log("Found esptool as Python module", "SUCCESS")
                return self.esptool_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Try to find in PATH
        for cmd in ["esptool.py", "esptool"]:
            esptool_path = shutil.which(cmd)
            if esptool_path:
                # Test if this esptool works
                try:
                    result = subprocess.run([esptool_path, "version"], capture_output=True, timeout=10)
                    if result.returncode == 0:
                        self.esptool_path = esptool_path
                        self.log(f"Found working esptool in PATH: {esptool_path}", "SUCCESS")
                        return esptool_path
                except:
                    continue
        
        # If not found, try to install esptool
        self.log("esptool not found in current Python environment. Attempting to install...", "WARNING")
        
        # Create a simple spinner for installation progress
        def spinner_animation():
            spinner_chars = "|/-\\"
            i = 0
            while not install_done:
                print(f"\r⏳ Installing esptool... {spinner_chars[i % len(spinner_chars)]}", end="", flush=True)
                time.sleep(0.1)
                i += 1
        
        install_done = False
        spinner_thread = threading.Thread(target=spinner_animation, daemon=True)
        spinner_thread.start()
        
        try:
            install_result = subprocess.run([sys.executable, "-m", "pip", "install", "esptool"], 
                                          capture_output=True, timeout=120, text=True)
            install_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            
            if install_result.returncode == 0:
                self.log("Successfully installed esptool", "SUCCESS")
                # Test the newly installed esptool
                try:
                    result = subprocess.run([sys.executable, "-m", "esptool", "version"], 
                                          capture_output=True, timeout=10)
                    if result.returncode == 0:
                        self.esptool_path = f"{sys.executable} -m esptool"
                        self.log("Verified newly installed esptool works", "SUCCESS")
                        return self.esptool_path
                except:
                    pass
            else:
                self.log(f"Failed to install esptool: {install_result.stderr}", "ERROR")
        except Exception as e:
            install_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            self.log(f"Could not install esptool: {e}", "ERROR")
        
        # Search in common locations as fallback
        for search_path in self.ESPTOOL_SEARCH_PATHS:
            if not search_path:
                continue
                
            # Handle wildcard paths
            if "*" in search_path:
                import glob
                matches = glob.glob(search_path)
                for match in matches:
                    if os.path.isfile(match):
                        # Test if this esptool works with its expected Python environment
                        if self._test_esptool_file(match):
                            self.esptool_path = match
                            self.log(f"Found working esptool: {match}", "SUCCESS")
                            return match
            else:
                if os.path.isfile(search_path):
                    if self._test_esptool_file(search_path):
                        self.esptool_path = search_path
                        self.log(f"Found working esptool: {search_path}", "SUCCESS")
                        return search_path
        
        self.log("❌ esptool.py not found and could not be installed! Please install it with: pip install esptool", "ERROR")
        return None
    
    def _test_esptool_file(self, esptool_path: str) -> bool:
        """Test if an esptool file works"""
        try:
            # Try with current Python interpreter
            result = subprocess.run([sys.executable, esptool_path, "version"], 
                                  capture_output=True, timeout=10)
            if result.returncode == 0:
                return True
            
            # If it's in ESP-IDF, try to find the ESP-IDF Python environment
            if "esp-idf" in esptool_path.lower():
                # Look for ESP-IDF Python executable
                esp_idf_root = Path(esptool_path).parents[4]  # Go up from components/esptool_py/esptool/esptool.py
                
                # Common ESP-IDF Python locations
                possible_python_paths = [
                    esp_idf_root / ".espressif" / "python_env" / "idf*" / "Scripts" / "python.exe",
                    esp_idf_root / ".espressif" / "python_env" / "idf*" / "bin" / "python",
                    Path.home() / ".espressif" / "python_env" / "idf*" / "Scripts" / "python.exe",
                    Path.home() / ".espressif" / "python_env" / "idf*" / "bin" / "python",
                ]
                
                for python_pattern in possible_python_paths:
                    if "*" in str(python_pattern):
                        import glob
                        matches = glob.glob(str(python_pattern))
                        for python_path in matches:
                            if os.path.isfile(python_path):
                                try:
                                    result = subprocess.run([python_path, esptool_path, "version"], 
                                                          capture_output=True, timeout=10)
                                    if result.returncode == 0:
                                        # Update the esptool path to include the correct Python
                                        return True
                                except:
                                    continue
                    else:
                        if python_pattern.exists():
                            try:
                                result = subprocess.run([str(python_pattern), esptool_path, "version"], 
                                                      capture_output=True, timeout=10)
                                if result.returncode == 0:
                                    return True
                            except:
                                continue
            
            return False
        except:
            return False
    
    def find_latest_firmware(self) -> Optional[Dict[str, Any]]:
        """Find the latest firmware version in the firmware directory"""
        if not self.firmware_dir.exists():
            self.log(f"Firmware directory not found: {self.firmware_dir}", "ERROR")
            return None
        
        version_dirs = []
        for item in self.firmware_dir.iterdir():
            if item.is_dir() and item.name.startswith('v'):
                try:
                    # Parse version number for sorting
                    version_str = item.name[1:]  # Remove 'v' prefix
                    version_parts = [int(x) for x in version_str.split('.')]
                    version_dirs.append((version_parts, item))
                except ValueError:
                    continue
        
        if not version_dirs:
            self.log("No firmware versions found", "ERROR")
            return None
        
        # Sort by version number and get the latest
        version_dirs.sort(key=lambda x: x[0], reverse=True)
        latest_dir = version_dirs[0][1]
        
        # Look for firmware files in the latest version directory
        bin_files = list(latest_dir.glob("*.bin"))
        manifest_files = list(latest_dir.glob("manifest*.json"))
        
        if not bin_files:
            self.log(f"No .bin files found in {latest_dir}", "ERROR")
            return None
        
        firmware_info = {
            "version": latest_dir.name,
            "directory": latest_dir,
            "binary_file": bin_files[0],
            "manifest_file": manifest_files[0] if manifest_files else None
        }
        
        # Load manifest if available
        if firmware_info["manifest_file"]:
            try:
                with open(firmware_info["manifest_file"], 'r') as f:
                    manifest = json.load(f)
                    firmware_info["manifest"] = manifest
            except Exception as e:
                self.log(f"Failed to load manifest: {e}", "WARNING")
        
        self.latest_firmware = firmware_info
        self.log(f"Latest firmware found: {firmware_info['version']} ({firmware_info['binary_file'].name})", "SUCCESS")
        return firmware_info
    
    def list_available_ports(self) -> List[Tuple[str, str]]:
        """List available serial ports that might be ESP32-S3 devices"""
        ports = []
        current_platform = platform.system().lower()
        
        self.log("Scanning for available serial ports...")
        for port in serial.tools.list_ports.comports():
            # Look for ESP32-S3 specific identifiers
            is_esp32 = any(keyword in port.description.lower() for keyword in 
                          ['esp32', 'esp32-s3', 'usb serial', 'cdc', 'uart', 'ch340', 'cp210', 'ft232', 'silicon labs'])
            
            # Check for common ESP32-S3 USB vendor/product IDs
            esp32_s3_ids = [
                (0x303A, 0x1001),  # Espressif ESP32-S3
                (0x10C4, 0xEA60),  # Silicon Labs CP2102/CP2109
                (0x1A86, 0x7523),  # QinHeng Electronics CH340
                (0x0403, 0x6001),  # FTDI FT232R
                (0x067B, 0x2303),  # Prolific PL2303
            ]
            
            vid_pid_match = False
            if port.vid is not None and port.pid is not None:
                vid_pid_match = (port.vid, port.pid) in esp32_s3_ids
            
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
            
            # Include device if it matches ESP32 criteria or has USB identifiers
            if is_esp32 or vid_pid_match or (port.vid is not None and port.pid is not None):
                vid_pid_str = f"VID:PID={port.vid:04X}:{port.pid:04X}" if port.vid else "Unknown"
                port_description = f"{device_description} [{port.device}] {vid_pid_str}"
                
                # Mark potential ESP32-S3 devices
                if vid_pid_match or 'esp32' in device_description.lower():
                    port_description = f"🎯 {port_description}"
                elif is_esp32:
                    port_description = f"📟 {port_description}"
                else:
                    port_description = f"❓ {port_description}"
                
                ports.append((port.device, port_description))
                self.log(f"Found potential device: {port.device} - {device_description}")
        
        if not ports:
            self.log("No potential ESP32-S3 devices found", "WARNING")
            if current_platform == "linux":
                self.log("💡 On Linux, ensure user is in 'dialout' group: sudo usermod -a -G dialout $USER", "INFO")
                self.log("💡 Then logout and login again, or run: newgrp dialout", "INFO")
        
        return ports
    
    def auto_detect_port(self) -> Optional[str]:
        """Auto-detect ESP32-S3 device port"""
        ports = self.list_available_ports()
        
        if len(ports) == 1:
            selected_port = ports[0][0]
            self.log(f"Auto-detected ESP32-S3: {ports[0][1]}")
            return selected_port
        elif len(ports) > 1:
            self.log("Multiple devices found. Please specify which one to use:")
            for i, (port, desc) in enumerate(ports, 1):
                print(f"  {i}. {desc}")
            
            try:
                choice = input("Enter device number (1-{}): ".format(len(ports)))
                index = int(choice) - 1
                if 0 <= index < len(ports):
                    return ports[index][0]
                else:
                    self.log("Invalid selection", "ERROR")
                    return None
            except (ValueError, KeyboardInterrupt):
                self.log("Selection cancelled", "WARNING")
                return None
        
        return None
    
    def test_esptool_connection(self, port: str) -> bool:
        """Test if esptool can connect to the device"""
        if not self.esptool_path:
            self.log("esptool not found", "ERROR")
            return False
        
        try:
            self.log(f"Testing connection to {port}...")
            
            # Build command based on esptool type
            if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                # Python module format: "python -m esptool"
                cmd = [sys.executable, "-m", "esptool", "--port", port, "--baud", "115200", "chip_id"]
            elif os.path.isfile(self.esptool_path):
                # Direct file path
                cmd = [sys.executable, self.esptool_path, "--port", port, "--baud", "115200", "chip_id"]
            else:
                # Executable in PATH
                cmd = [self.esptool_path, "--port", port, "--baud", "115200", "chip_id"]
            
            self.log(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, timeout=10, text=True)
            
            if result.returncode == 0:
                # Check if it's actually an ESP32-S3
                if "ESP32-S3" in result.stdout:
                    self.log(f"Confirmed ESP32-S3 on {port}", "SUCCESS")
                    return True
                else:
                    self.log(f"Device on {port} is not ESP32-S3", "WARNING")
                    return False
            else:
                self.log(f"Connection test failed: {result.stderr}", "ERROR")
                return False
                
        except subprocess.TimeoutExpired:
            self.log(f"Connection test timed out for {port}", "ERROR")
            return False
        except Exception as e:
            self.log(f"Connection test error: {e}", "ERROR")
            return False
    
    def erase_flash(self, port: str, smart_erase: bool = False, erase_size: str = None) -> bool:
        """Erase the device flash memory
        
        Args:
            port: Serial port
            smart_erase: If True, only erase the region needed for firmware (faster)
            erase_size: Specific size to erase (e.g., '1MB') instead of full chip
        """
        if not self.esptool_path:
            self.log("esptool not found", "ERROR")
            return False
        
        try:
            if smart_erase and self.latest_firmware:
                # Calculate the size needed for firmware + some buffer
                firmware_size = self.latest_firmware["binary_file"].stat().st_size
                # Round up to nearest 64KB sector + 64KB buffer
                erase_sectors = ((firmware_size + 64*1024 + 64*1024 - 1) // (64*1024))
                erase_end = erase_sectors * 64*1024
                
                self.log(f"Smart erase: firmware size {firmware_size:,} bytes, erasing {erase_end:,} bytes")
                
                # Use erase_region instead of erase_flash for speed
                if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                    cmd = [sys.executable, "-m", "esptool", "--port", port, "--baud", str(self.ERASE_BAUD_RATE), 
                           "erase_region", "0x0", hex(erase_end)]
                elif os.path.isfile(self.esptool_path):
                    cmd = [sys.executable, self.esptool_path, "--port", port, "--baud", str(self.ERASE_BAUD_RATE),
                           "erase_region", "0x0", hex(erase_end)]
                else:
                    cmd = [self.esptool_path, "--port", port, "--baud", str(self.ERASE_BAUD_RATE),
                           "erase_region", "0x0", hex(erase_end)]
                
                operation_name = "Smart erasing"
            else:
                self.log("Full chip erase (this may take 30-60 seconds)...")
                
                # Build command based on esptool type
                if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                    # Python module format: "python -m esptool"
                    cmd = [sys.executable, "-m", "esptool", "--port", port, "--baud", str(self.ERASE_BAUD_RATE), "erase_flash"]
                elif os.path.isfile(self.esptool_path):
                    # Direct file path
                    cmd = [sys.executable, self.esptool_path, "--port", port, "--baud", str(self.ERASE_BAUD_RATE), "erase_flash"]
                else:
                    # Executable in PATH
                    cmd = [self.esptool_path, "--port", port, "--baud", str(self.ERASE_BAUD_RATE), "erase_flash"]
                
                operation_name = "Erasing flash"
            
            # Create spinner for erase progress
            def erase_spinner():
                spinner_chars = "|/-\\"
                i = 0
                start_time = time.time()
                while not erase_done:
                    elapsed = int(time.time() - start_time)
                    print(f"\r🔥 {operation_name}... {spinner_chars[i % len(spinner_chars)]} ({elapsed}s)", end="", flush=True)
                    time.sleep(0.2)
                    i += 1
            
            erase_done = False
            spinner_thread = threading.Thread(target=erase_spinner, daemon=True)
            spinner_thread.start()
            
            result = subprocess.run(cmd, capture_output=True, timeout=120, text=True)  # Increased timeout for full erase
            erase_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            
            if result.returncode == 0:
                self.log("Flash erase completed successfully", "SUCCESS")
                return True
            else:
                self.log(f"Flash erase failed: {result.stderr}", "ERROR")
                return False
                
        except subprocess.TimeoutExpired:
            erase_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            self.log("Flash erase timed out", "ERROR")
            return False
        except Exception as e:
            erase_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            self.log(f"Flash erase error: {e}", "ERROR")
            return False
    
    def flash_firmware(self, port: str, firmware_info: Dict[str, Any] = None, erase_first: bool = True, 
                      smart_erase: bool = True, production_mode: bool = False) -> bool:
        """Flash firmware to the ESP32-S3 device
        
        Args:
            port: Serial port
            firmware_info: Firmware information dict
            erase_first: Whether to erase before flashing
            smart_erase: Use faster sectored erase instead of full chip erase
            production_mode: Skip non-essential steps for maximum speed
        """
        if not self.esptool_path:
            self.log("esptool not found", "ERROR")
            return False
        
        if not firmware_info:
            firmware_info = self.latest_firmware
        
        if not firmware_info:
            self.log("No firmware available", "ERROR")
            return False
        
        try:
            binary_file = firmware_info["binary_file"]
            
            if production_mode:
                self.log(f"🏭 PRODUCTION MODE: Flashing {firmware_info['version']} to {port}", "FLASH")
            else:
                self.log(f"Flashing firmware {firmware_info['version']} to {port}...", "FLASH")
            
            self.log(f"Firmware file: {binary_file.name} ({binary_file.stat().st_size:,} bytes)")
            
            # Erase flash first if requested
            if erase_first:
                if not self.erase_flash(port, smart_erase=smart_erase):
                    return False
                time.sleep(0.5)  # Reduced pause after erase
            
            # Build flash command
            if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                # Python module format: "python -m esptool"
                cmd = [
                    sys.executable, "-m", "esptool",
                    "--chip", self.CHIP_TYPE,
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "write_flash"
                ]
                
                # Add production mode optimizations
                if production_mode:
                    cmd.extend(["--compress"])  # Enable compression for faster transfer
                
                cmd.extend([
                    "--flash_mode", self.FLASH_MODE,
                    "--flash_freq", self.FLASH_FREQ,
                    "--flash_size", self.FLASH_SIZE,
                    "0x0",  # Flash offset - typically 0x0 for ESP32-S3
                    str(binary_file)
                ])
            elif os.path.isfile(self.esptool_path):
                # Direct file path
                cmd = [
                    sys.executable, self.esptool_path,
                    "--chip", self.CHIP_TYPE,
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "write_flash"
                ]
                
                if production_mode:
                    cmd.extend(["--compress"])
                
                cmd.extend([
                    "--flash_mode", self.FLASH_MODE,
                    "--flash_freq", self.FLASH_FREQ,
                    "--flash_size", self.FLASH_SIZE,
                    "0x0",
                    str(binary_file)
                ])
            else:
                # Executable in PATH
                cmd = [
                    self.esptool_path,
                    "--chip", self.CHIP_TYPE,
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "write_flash"
                ]
                
                if production_mode:
                    cmd.extend(["--compress"])
                
                cmd.extend([
                    "--flash_mode", self.FLASH_MODE,
                    "--flash_freq", self.FLASH_FREQ,
                    "--flash_size", self.FLASH_SIZE,
                    "0x0",
                    str(binary_file)
                ])
            
            if production_mode:
                self.log(f"🚀 FAST MODE: Using compression and optimized settings")
            
            self.log(f"Executing: {' '.join(cmd)}")
            
            # Start flashing with progress tracking
            self.log("Starting firmware flash operation...", "PROGRESS")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, universal_newlines=True)
            
            # Track progress if tqdm is available
            if HAS_TQDM:
                print("📤 Initializing flash operation...")
                with tqdm(total=100, desc="Flashing", unit="%", ncols=80, 
                         bar_format='{l_bar}{bar}| {n:.0f}% [{elapsed}<{remaining}]') as pbar:
                    last_progress = 0
                    
                    for line in process.stdout:
                        print(line.strip())  # Print esptool output
                        
                        # Look for progress indicators in esptool output
                        if "%" in line and "(" in line:
                            try:
                                # Extract percentage from lines like "Writing at 0x00008000... (12 %)"
                                percent_pos = line.find("(") + 1
                                percent_end = line.find("%", percent_pos)
                                if percent_pos > 0 and percent_end > percent_pos:
                                    progress = int(line[percent_pos:percent_end].strip())
                                    pbar.update(progress - last_progress)
                                    last_progress = progress
                            except (ValueError, IndexError):
                                pass
            else:
                # Simple progress without tqdm with spinner for initial phase
                print("📤 Initializing flash operation...")
                initial_phase = True
                
                def simple_spinner():
                    spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
                    i = 0
                    while initial_phase:
                        print(f"\r⏳ Preparing to flash... {spinner_chars[i % len(spinner_chars)]}", end="", flush=True)
                        time.sleep(0.1)
                        i += 1
                
                spinner_thread = threading.Thread(target=simple_spinner, daemon=True)
                spinner_thread.start()
                
                for line in process.stdout:
                    if initial_phase and ("Writing at" in line or "%" in line):
                        initial_phase = False
                        print("\r" + " " * 50 + "\r", end="")  # Clear spinner
                    print(line.strip())
                
                initial_phase = False
            
            process.wait()
            
            if process.returncode == 0:
                self.log("Firmware flashed successfully!", "SUCCESS")
                self.log("Device will now reboot with new firmware", "INFO")
                return True
            else:
                self.log("Firmware flashing failed", "ERROR")
                return False
                
        except Exception as e:
            self.log(f"Firmware flashing error: {e}", "ERROR")
            return False
    
    def verify_flash(self, port: str, firmware_info: Dict[str, Any] = None) -> bool:
        """Verify the flashed firmware"""
        if not self.esptool_path:
            self.log("esptool not found", "ERROR")
            return False
        
        if not firmware_info:
            firmware_info = self.latest_firmware
        
        if not firmware_info:
            self.log("No firmware available for verification", "ERROR")
            return False
        
        try:
            binary_file = firmware_info["binary_file"]
            
            self.log("Verifying flashed firmware...")
            
            if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                # Python module format: "python -m esptool"
                cmd = [
                    sys.executable, "-m", "esptool",
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "verify_flash",
                    "0x0",
                    str(binary_file)
                ]
            elif os.path.isfile(self.esptool_path):
                # Direct file path
                cmd = [
                    sys.executable, self.esptool_path,
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "verify_flash",
                    "0x0",
                    str(binary_file)
                ]
            else:
                # Executable in PATH
                cmd = [
                    self.esptool_path,
                    "--port", port,
                    "--baud", str(self.BAUD_RATE),
                    "verify_flash",
                    "0x0",
                    str(binary_file)
                ]
            
            # Create spinner for verification progress
            def verify_spinner():
                spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
                i = 0
                start_time = time.time()
                while not verify_done:
                    elapsed = int(time.time() - start_time)
                    print(f"\r🔍 Verifying firmware... {spinner_chars[i % len(spinner_chars)]} ({elapsed}s)", end="", flush=True)
                    time.sleep(0.1)
                    i += 1
            
            verify_done = False
            spinner_thread = threading.Thread(target=verify_spinner, daemon=True)
            spinner_thread.start()
            
            result = subprocess.run(cmd, capture_output=True, timeout=120, text=True)
            verify_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            
            if result.returncode == 0:
                self.log("Firmware verification successful!", "SUCCESS")
                return True
            else:
                self.log(f"Firmware verification failed: {result.stderr}", "ERROR")
                return False
                
        except subprocess.TimeoutExpired:
            verify_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            self.log("Firmware verification timed out", "ERROR")
            return False
        except Exception as e:
            verify_done = True
            print("\r" + " " * 50 + "\r", end="")  # Clear spinner line
            self.log(f"Firmware verification error: {e}", "ERROR")
            return False
    
    def detect_flash_size(self, port: str) -> Optional[str]:
        """Detect the actual flash size of the ESP32-S3 device"""
        if not self.esptool_path:
            self.log("esptool not found", "ERROR")
            return None
        
        try:
            self.log(f"Detecting flash size on {port}...")
            
            # Build command based on esptool type
            if self.esptool_path.startswith(sys.executable) and "-m esptool" in self.esptool_path:
                cmd = [sys.executable, "-m", "esptool", "--port", port, "--baud", "115200", "flash_id"]
            elif os.path.isfile(self.esptool_path):
                cmd = [sys.executable, self.esptool_path, "--port", port, "--baud", "115200", "flash_id"]
            else:
                cmd = [self.esptool_path, "--port", port, "--baud", "115200", "flash_id"]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10, text=True)
            
            if result.returncode == 0:
                # Parse the flash size from output
                output = result.stdout
                
                # Look for flash size in the output
                if "Detected flash size: " in output:
                    # Extract size from "Detected flash size: 4MB"
                    size_line = [line for line in output.split('\n') if "Detected flash size:" in line][0]
                    flash_size = size_line.split("Detected flash size: ")[1].strip()
                    self.log(f"Detected flash size: {flash_size}", "SUCCESS")
                    return flash_size
                elif "flash size" in output.lower():
                    # Try to parse from other formats
                    lines = output.split('\n')
                    for line in lines:
                        if 'MB' in line and ('flash' in line.lower() or 'size' in line.lower()):
                            # Try to extract MB value
                            import re
                            mb_match = re.search(r'(\d+)MB', line)
                            if mb_match:
                                size = mb_match.group(1) + "MB"
                                self.log(f"Detected flash size: {size}", "SUCCESS")
                                return size
                
                # Fallback - try to determine from manufacturer/device ID
                if "Manufacturer:" in output and "Device:" in output:
                    self.log("Could not auto-detect flash size from output", "WARNING")
                    self.log("Flash detection output:", "INFO")
                    print(output)
                    return None
                    
            else:
                self.log(f"Flash detection failed: {result.stderr}", "ERROR")
                return None
                
        except subprocess.TimeoutExpired:
            self.log("Flash detection timed out", "ERROR")
            return None
        except Exception as e:
            self.log(f"Flash detection error: {e}", "ERROR")
            return None
    
    def recover_device(self, port: str) -> bool:
        """Attempt to recover a bricked device"""
        self.log("🚨 DEVICE RECOVERY MODE", "WARNING")
        self.log("Attempting to recover device with full chip erase and reflash...", "WARNING")
        
        # Force full chip erase (not smart erase)
        if not self.erase_flash(port, smart_erase=False):
            self.log("Recovery erase failed", "ERROR")
            return False
        
        # Detect the correct flash size
        detected_size = self.detect_flash_size(port)
        if detected_size:
            # Temporarily update flash size for this recovery
            original_size = self.FLASH_SIZE
            self.FLASH_SIZE = detected_size
            self.log(f"Using detected flash size: {detected_size} for recovery", "SUCCESS")
            
            # Flash with correct settings
            result = self.flash_firmware(port, erase_first=False, smart_erase=False, production_mode=False)
            
            # Restore original setting
            self.FLASH_SIZE = original_size
            return result
        else:
            # Try with common flash sizes
            for flash_size in ["4MB", "8MB", "16MB"]:
                self.log(f"Trying recovery with {flash_size} flash size...", "WARNING")
                original_size = self.FLASH_SIZE
                self.FLASH_SIZE = flash_size
                
                result = self.flash_firmware(port, erase_first=False, smart_erase=False, production_mode=False)
                
                self.FLASH_SIZE = original_size
                
                if result:
                    self.log(f"✅ Recovery successful with {flash_size} flash size!", "SUCCESS")
                    self.log(f"💡 Update FLASH_SIZE to '{flash_size}' in the code for this device type", "INFO")
                    return True
                else:
                    self.log(f"Recovery with {flash_size} failed, trying next size...", "WARNING")
            
            return False
    
    def program_device(self, port: str = None, erase_first: bool = True, verify: bool = True, 
                      smart_erase: bool = True, production_mode: bool = False) -> bool:
        """Program a device with the latest firmware
        
        Args:
            port: Serial port (auto-detect if None)
            erase_first: Whether to erase before flashing
            verify: Whether to verify after flashing
            smart_erase: Use faster sectored erase
            production_mode: Enable production optimizations
        """
        # Determine port
        if not port:
            port = self.port_name or self.auto_detect_port()
            if not port:
                self.log("No device port specified or detected", "ERROR")
                return False
        
        # Test connection
        if not self.test_esptool_connection(port):
            self.log(f"Cannot connect to ESP32-S3 on {port}", "ERROR")
            return False
        
        # Flash firmware
        if not self.flash_firmware(port, erase_first=erase_first, smart_erase=smart_erase, 
                                  production_mode=production_mode):
            return False
        
        # Verify firmware if requested (skip in production mode for speed)
        if verify and not production_mode:
            if not self.verify_flash(port):
                self.log("Verification failed, but firmware may still work", "WARNING")
        elif production_mode:
            self.log("🏭 PRODUCTION MODE: Skipping verification for speed", "INFO")
        
        if production_mode:
            self.log("🏭 PRODUCTION MODE: Device programming completed in FAST mode!", "SUCCESS")
        else:
            self.log("Device programming completed successfully!", "SUCCESS")
        return True
    
    def batch_program_devices(self, ports: List[str], production_mode: bool = True) -> Dict[str, bool]:
        """Program multiple devices in batch mode
        
        Args:
            ports: List of serial ports to program
            production_mode: Use production mode optimizations
            
        Returns:
            Dict mapping port names to success status
        """
        if not self.esptool_path or not self.latest_firmware:
            self.log("Missing esptool or firmware for batch operation", "ERROR")
            return {}
        
        results = {}
        total_devices = len(ports)
        
        self.log(f"🚀 BATCH MODE: Starting programming of {total_devices} devices", "INFO")
        self.log(f"📦 Firmware: {self.latest_firmware['version']}", "INFO")
        if production_mode:
            self.log("🏭 Using PRODUCTION MODE optimizations", "INFO")
        
        # Test all connections first
        self.log("🔍 Testing connections to all devices...", "PROGRESS")
        valid_ports = []
        for i, port in enumerate(ports, 1):
            self.log(f"Testing device {i}/{total_devices}: {port}")
            if self.test_esptool_connection(port):
                valid_ports.append(port)
                self.log(f"✅ Device {i} ({port}): Connection OK", "SUCCESS")
            else:
                self.log(f"❌ Device {i} ({port}): Connection failed", "ERROR")
                results[port] = False
        
        if not valid_ports:
            self.log("❌ No valid devices found for batch programming", "ERROR")
            return results
        
        self.log(f"📊 Programming {len(valid_ports)}/{total_devices} devices", "INFO")
        
        # Program each device sequentially (safer than parallel for USB bandwidth)
        for i, port in enumerate(valid_ports, 1):
            self.log(f"🔄 Programming device {i}/{len(valid_ports)}: {port}", "PROGRESS")
            
            start_time = time.time()
            success = self.program_device(
                port=port, 
                erase_first=True, 
                verify=not production_mode,  # Skip verification in production mode
                smart_erase=True, 
                production_mode=production_mode
            )
            end_time = time.time()
            duration = end_time - start_time
            
            results[port] = success
            
            if success:
                self.log(f"✅ Device {i} ({port}): Programming completed in {duration:.1f}s", "SUCCESS")
            else:
                self.log(f"❌ Device {i} ({port}): Programming failed after {duration:.1f}s", "ERROR")
                
                # Ask user if they want to continue with remaining devices
                if i < len(valid_ports):
                    try:
                        continue_choice = input(f"❓ Device {port} failed. Continue with remaining devices? (y/n): ")
                        if continue_choice.lower() not in ['y', 'yes']:
                            self.log("🛑 Batch operation cancelled by user", "WARNING")
                            # Mark remaining devices as not attempted
                            for remaining_port in valid_ports[i:]:
                                if remaining_port not in results:
                                    results[remaining_port] = False
                            break
                    except KeyboardInterrupt:
                        self.log("🛑 Batch operation cancelled", "WARNING")
                        break
            
            # Small delay between devices to avoid USB issues
            if i < len(valid_ports):
                time.sleep(1)
        
        # Summary
        successful_devices = sum(1 for success in results.values() if success)
        failed_devices = len(results) - successful_devices
        
        self.log("📊 BATCH PROGRAMMING SUMMARY:", "INFO")
        self.log(f"   ✅ Successful: {successful_devices} devices", "SUCCESS" if successful_devices > 0 else "INFO")
        self.log(f"   ❌ Failed: {failed_devices} devices", "ERROR" if failed_devices > 0 else "INFO")
        self.log(f"   📈 Success rate: {successful_devices/len(results)*100:.1f}%" if results else "0%", "INFO")
        
        # List results by device
        for port, success in results.items():
            status = "✅ SUCCESS" if success else "❌ FAILED"
            self.log(f"   {port}: {status}")
        
        return results
    
    def interactive_menu(self):
        """Interactive menu for firmware operations"""
        while True:
            print("\n" + "="*60)
            print("⚡ AutoTQ Firmware Programmer")
            print("="*60)
            
            if self.esptool_path:
                print(f"🔧 esptool: {self.esptool_path}")
            else:
                print("❌ esptool: Not found")
            
            if self.latest_firmware:
                fw = self.latest_firmware
                print(f"💾 Latest firmware: {fw['version']} ({fw['binary_file'].name})")
            else:
                print("❌ No firmware found")
            
            ports = self.list_available_ports()
            if ports:
                print(f"📟 Detected devices: {len(ports)}")
                for port, desc in ports:
                    print(f"   • {desc}")
            else:
                print("📟 No devices detected")
            
            print("\nOptions:")
            print("  1. Auto-detect and program device")
            print("  2. Program specific device")
            print("  3. Test device connection")
            print("  4. Erase device flash")
            print("  5. List available firmware versions")
            print("  6. Refresh device list")
            print("  7. Find esptool")
            print("  8. 🏭 PRODUCTION MODE: Fast program (auto-detect)")
            print("  9. 🏭 PRODUCTION MODE: Fast program (select device)")
            print("  b. 🚀 BATCH MODE: Program multiple devices")
            print("  r. 🚨 RECOVERY MODE: Detect flash size and recover device")
            print("  d. 🔍 Detect flash size on device")
            print("  0. Exit")
            
            try:
                choice = input("\nEnter your choice: ").strip()
                
                if choice == '0':
                    break
                elif choice == '1':
                    if self.esptool_path and self.latest_firmware:
                        self.program_device()
                    else:
                        print("❌ Missing esptool or firmware")
                elif choice == '2':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    self.program_device(port=selected_port)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == '3':
                    if ports:
                        print("\nTesting device connections...")
                        for port, desc in ports:
                            print(f"Testing {port}...")
                            if self.test_esptool_connection(port):
                                print(f"✅ {port}: ESP32-S3 confirmed")
                            else:
                                print(f"❌ {port}: Connection failed or not ESP32-S3")
                    else:
                        print("❌ No devices to test")
                elif choice == '4':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number to erase: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                confirm = input(f"⚠️  Are you sure you want to erase {selected_port}? (yes/no): ")
                                if confirm.lower() == 'yes':
                                    self.erase_flash(selected_port)
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == '5':
                    self.list_firmware_versions()
                elif choice == '6':
                    ports = self.list_available_ports()
                elif choice == '7':
                    self.find_esptool()
                elif choice == '8':
                    if self.esptool_path and self.latest_firmware:
                        print("🏭 PRODUCTION MODE: Programming device with fast settings...")
                        self.program_device(production_mode=True)
                    else:
                        print("❌ Missing esptool or firmware")
                elif choice == '9':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    print("🏭 PRODUCTION MODE: Programming device with fast settings...")
                                    self.program_device(port=selected_port, production_mode=True)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == 'b':
                    if ports:
                        print("\n🚀 BATCH MODE: Program multiple devices")
                        print("Available devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        print("\nSelect devices to program:")
                        print("  • Enter device numbers separated by commas (e.g., 1,3,4)")
                        print("  • Enter 'all' to program all devices")
                        print("  • Enter 'auto' to program all ESP32-S3 devices (🎯 marked)")
                        
                        try:
                            selection = input("Device selection: ").strip().lower()
                            
                            selected_ports = []
                            if selection == 'all':
                                selected_ports = [port for port, desc in ports]
                                print(f"📋 Selected all {len(selected_ports)} devices")
                            elif selection == 'auto':
                                selected_ports = [port for port, desc in ports if '🎯' in desc]
                                print(f"📋 Auto-selected {len(selected_ports)} ESP32-S3 devices")
                            else:
                                # Parse comma-separated numbers
                                device_numbers = [int(x.strip()) for x in selection.split(',')]
                                selected_ports = []
                                for num in device_numbers:
                                    if 1 <= num <= len(ports):
                                        selected_ports.append(ports[num-1][0])
                                    else:
                                        print(f"⚠️ Invalid device number: {num}")
                                print(f"📋 Selected {len(selected_ports)} devices")
                            
                            if selected_ports and self.esptool_path and self.latest_firmware:
                                self.batch_program_devices(selected_ports)
                            elif not selected_ports:
                                print("❌ No devices selected")
                            else:
                                print("❌ Missing esptool or firmware")
                                
                        except (ValueError, IndexError) as e:
                            print(f"❌ Invalid selection: {e}")
                    else:
                        print("❌ No devices available")
                elif choice == 'r':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    print("🚨 RECOVERY MODE: Detecting flash size and recovering device...")
                                    self.recover_device(selected_port)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == 'd':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    print("🔍 Detecting flash size on device...")
                                    self.detect_flash_size(selected_port)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == 'b' or choice == 'r':
                    if ports:
                        print("\n🚀 BATCH MODE: Program multiple devices")
                        print("Available devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        print("\nSelect devices to program:")
                        print("  • Enter device numbers separated by commas (e.g., 1,3,4)")
                        print("  • Enter 'all' to program all devices")
                        print("  • Enter 'auto' to program all ESP32-S3 devices (🎯 marked)")
                        
                        try:
                            selection = input("Device selection: ").strip().lower()
                            
                            selected_ports = []
                            if selection == 'all':
                                selected_ports = [port for port, desc in ports]
                                print(f"📋 Selected all {len(selected_ports)} devices")
                            elif selection == 'auto':
                                selected_ports = [port for port, desc in ports if '🎯' in desc]
                                print(f"📋 Auto-selected {len(selected_ports)} ESP32-S3 devices")
                            else:
                                # Parse comma-separated numbers
                                device_numbers = [int(x.strip()) for x in selection.split(',')]
                                selected_ports = []
                                for num in device_numbers:
                                    if 1 <= num <= len(ports):
                                        selected_ports.append(ports[num-1][0])
                                    else:
                                        print(f"⚠️ Invalid device number: {num}")
                                print(f"📋 Selected {len(selected_ports)} devices")
                            
                            if selected_ports and self.esptool_path and self.latest_firmware:
                                self.batch_program_devices(selected_ports)
                            elif not selected_ports:
                                print("❌ No devices selected")
                            else:
                                print("❌ Missing esptool or firmware")
                                
                        except (ValueError, IndexError) as e:
                            print(f"❌ Invalid selection: {e}")
                    else:
                        print("❌ No devices available")
                elif choice == 'r':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    print("🚨 RECOVERY MODE: Detecting flash size and recovering device...")
                                    self.recover_device(selected_port)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                elif choice == 'd':
                    if ports:
                        print("\nAvailable devices:")
                        for i, (port, desc) in enumerate(ports, 1):
                            print(f"  {i}. {desc}")
                        
                        try:
                            device_choice = int(input("Enter device number: ")) - 1
                            if 0 <= device_choice < len(ports):
                                selected_port = ports[device_choice][0]
                                if self.esptool_path and self.latest_firmware:
                                    print("🔍 Detecting flash size on device...")
                                    self.detect_flash_size(selected_port)
                                else:
                                    print("❌ Missing esptool or firmware")
                        except (ValueError, IndexError):
                            print("❌ Invalid selection")
                    else:
                        print("❌ No devices available")
                else:
                    print("❌ Invalid option")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def list_firmware_versions(self):
        """List all available firmware versions"""
        if not self.firmware_dir.exists():
            print(f"❌ Firmware directory not found: {self.firmware_dir}")
            return
        
        version_dirs = []
        for item in self.firmware_dir.iterdir():
            if item.is_dir() and item.name.startswith('v'):
                bin_files = list(item.glob("*.bin"))
                if bin_files:
                    version_dirs.append((item.name, item, bin_files[0]))
        
        if not version_dirs:
            print("❌ No firmware versions found")
            return
        
        print("\nAvailable firmware versions:")
        for version, dir_path, bin_file in sorted(version_dirs, reverse=True):
            size = bin_file.stat().st_size
            print(f"  📦 {version}: {bin_file.name} ({size:,} bytes)")
            if version == self.latest_firmware['version']:
                print("     ⭐ (Latest)")


def main():
    """Command line interface"""
    parser = argparse.ArgumentParser(
        description="AutoTQ Firmware Programmer - Flash ESP32-S3 devices with AutoTQ firmware",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_firmware_programmer.py                     # Interactive mode
  python autotq_firmware_programmer.py --port COM3        # Flash specific port
  python autotq_firmware_programmer.py --auto-program     # Auto-detect and program
  python autotq_firmware_programmer.py --auto-program --production  # FAST production mode
  python autotq_firmware_programmer.py --list-ports       # List available ports
  python autotq_firmware_programmer.py --test-connection COM3  # Test connection
  python autotq_firmware_programmer.py --erase COM3       # Erase flash only
  python autotq_firmware_programmer.py --no-verify        # Skip verification
  python autotq_firmware_programmer.py --full-erase       # Force full chip erase
        """
    )
    
    parser.add_argument("--port", help="Serial port (e.g., COM3, /dev/ttyUSB0)")
    parser.add_argument("--firmware-dir", default="firmware", 
                       help="Directory containing firmware files (default: firmware)")
    parser.add_argument("--auto-program", action="store_true",
                       help="Auto-detect device and program it")
    parser.add_argument("--list-ports", action="store_true",
                       help="List available serial ports and exit")
    parser.add_argument("--test-connection", metavar="PORT",
                       help="Test connection to specified port")
    parser.add_argument("--erase", metavar="PORT",
                       help="Erase flash on specified port")
    parser.add_argument("--no-erase", action="store_true",
                       help="Skip flash erase before programming")
    parser.add_argument("--no-verify", action="store_true",
                       help="Skip firmware verification after flashing")
    parser.add_argument("--production", action="store_true",
                       help="Enable production mode: fast erase, compression, skip verification")
    parser.add_argument("--full-erase", action="store_true",
                       help="Force full chip erase instead of smart sectored erase")
    parser.add_argument("--recover", metavar="PORT",
                       help="Attempt to recover a bricked device on specified port")
    parser.add_argument("--detect-flash-size", metavar="PORT",
                       help="Detect flash size on specified port")
    parser.add_argument("--list-firmware", action="store_true",
                       help="List available firmware versions and exit")
    parser.add_argument("--batch-program", action="store_true",
                       help="Batch program all detected ESP32-S3 devices")
    parser.add_argument("--batch-ports", nargs="+",
                       help="Specify exact ports for batch programming (e.g., COM3 COM4)")
    
    args = parser.parse_args()
    
    # Initialize programmer
    programmer = AutoTQFirmwareProgrammer(
        firmware_dir=args.firmware_dir,
        port=args.port
    )
    
    try:
        if args.list_ports:
            programmer.list_available_ports()
        elif args.list_firmware:
            programmer.list_firmware_versions()
        elif args.test_connection:
            if programmer.test_esptool_connection(args.test_connection):
                print(f"✅ Connection successful: {args.test_connection}")
            else:
                print(f"❌ Connection failed: {args.test_connection}")
                sys.exit(1)
        elif args.erase:
            if programmer.erase_flash(args.erase):
                print(f"✅ Flash erased: {args.erase}")
            else:
                print(f"❌ Flash erase failed: {args.erase}")
                sys.exit(1)
        elif args.recover:
            if programmer.recover_device(args.recover):
                print(f"✅ Device recovery successful: {args.recover}")
            else:
                print(f"❌ Device recovery failed: {args.recover}")
                sys.exit(1)
        elif args.detect_flash_size:
            detected_size = programmer.detect_flash_size(args.detect_flash_size)
            if detected_size:
                print(f"✅ Flash size detected: {detected_size} on {args.detect_flash_size}")
                print(f"💡 Update FLASH_SIZE = \"{detected_size}\" in the code for this device type")
            else:
                print(f"❌ Flash size detection failed: {args.detect_flash_size}")
                sys.exit(1)
        elif args.auto_program:
            # Set up production mode options
            production_mode = args.production
            smart_erase = not args.full_erase  # Use smart erase unless full erase is forced
            verify = not args.no_verify and not production_mode  # Skip verify in production mode
            
            if production_mode:
                print("🏭 PRODUCTION MODE ENABLED")
                print("   ⚡ Using smart sectored erase (faster)")
                print("   🗜️  Using compression")
                print("   ⏭️  Skipping verification")
                print("   🚀 Optimized for maximum speed")
            
            if programmer.program_device(erase_first=not args.no_erase, verify=verify, 
                                       smart_erase=smart_erase, production_mode=production_mode):
                if production_mode:
                    print("🏭✅ PRODUCTION: Device programmed successfully in FAST mode")
                else:
                    print("✅ Device programmed successfully")
            else:
                print("❌ Device programming failed")
                sys.exit(1)
        elif args.batch_program or args.batch_ports:
            if args.batch_ports:
                # Use specified ports
                selected_ports = args.batch_ports
                print(f"🚀 BATCH MODE: Programming specified ports: {', '.join(selected_ports)}")
                results = programmer.batch_program_devices(selected_ports, production_mode=args.production)
            else:
                # Auto-detect ESP32-S3 devices  
                ports = programmer.list_available_ports()
                esp32_ports = [port for port, desc in ports if '🎯' in desc]
                
                if esp32_ports:
                    print(f"🚀 BATCH MODE: Auto-detected {len(esp32_ports)} ESP32-S3 devices")
                    for port in esp32_ports:
                        matching_desc = next(desc for p, desc in ports if p == port)
                        print(f"   • {matching_desc}")
                    
                    results = programmer.batch_program_devices(esp32_ports, production_mode=args.production)
                else:
                    print("❌ No ESP32-S3 devices auto-detected")
                    sys.exit(1)
            
            # Check results
            successful = sum(1 for success in results.values() if success)
            total = len(results)
            if successful == total and total > 0:
                print(f"✅ All {total} devices programmed successfully")
            elif successful > 0:
                print(f"⚠️ {successful}/{total} devices programmed successfully")
                sys.exit(1)
            else:
                print("❌ All devices failed")
                sys.exit(1)
        else:
            # Interactive mode
            programmer.interactive_menu()
    
    except KeyboardInterrupt:
        programmer.log("Operation cancelled by user", "WARNING")
    except Exception as e:
        programmer.log(f"Unexpected error: {e}", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main() 