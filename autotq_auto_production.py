#!/usr/bin/env python3
"""
AutoTQ Auto Production Tool

Detects new devices, flashes firmware, and transfers missing audio files.
Designed for high-throughput production environment.
Includes a web dashboard on port 9090.
"""

import sys
import time
import json
import argparse
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import serial.tools.list_ports
import csv
import glob
import re
import webbrowser
import requests
from datetime import datetime

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

try:
    from flask import Flask, render_template, jsonify, request
except ImportError:
    print("❌ Flask not installed. Install with: pip install flask")
    sys.exit(1)

try:
    from autotq_device_programmer import AutoTQDeviceProgrammer, Colors
    from autotq_firmware_programmer import AutoTQFirmwareProgrammer
    from autotq_client import AutoTQClient
    from autotq_quick_check import ensure_pcb_stage
    from autotq_setup import AutoTQSetup
except ImportError as e:
    print(f"❌ Error: Required modules not found: {e}")
    sys.exit(1)

# Status constants
STATUS_DETECTED = "DETECTED"
STATUS_FLASHING = "FLASHING"
STATUS_CONNECTING = "CONNECTING"
STATUS_CHECKING = "CHECKING"
STATUS_REGISTERING = "REGISTERING"
STATUS_TRANSFERRING = "TRANSFERRING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_REMOVED = "REMOVED"
STATUS_NEEDS_BATTERY = "NEEDS_BATTERY"
STATUS_WAITING_RETRY = "WAITING_RETRY"
STATUS_AWAITING_SERIAL = "AWAITING_SERIAL"  # New: waiting for user to enter serial number

# Status display info
STATUS_INFO = {
    STATUS_DETECTED: {"icon": "🔍", "color": "#3498db", "label": "Detected"},
    STATUS_FLASHING: {"icon": "⚡", "color": "#9b59b6", "label": "Flashing Firmware"},
    STATUS_CONNECTING: {"icon": "🔌", "color": "#f39c12", "label": "Connecting"},
    STATUS_CHECKING: {"icon": "📋", "color": "#1abc9c", "label": "Checking Files"},
    STATUS_REGISTERING: {"icon": "☁️", "color": "#3498db", "label": "Registering"},
    STATUS_TRANSFERRING: {"icon": "📤", "color": "#e67e22", "label": "Transferring Audio"},
    STATUS_COMPLETED: {"icon": "✅", "color": "#27ae60", "label": "Completed"},
    STATUS_FAILED: {"icon": "❌", "color": "#e74c3c", "label": "Failed"},
    STATUS_REMOVED: {"icon": "🔌", "color": "#95a5a6", "label": "Removed"},
    STATUS_NEEDS_BATTERY: {"icon": "🔋", "color": "#e74c3c", "label": "Battery Required"},
    STATUS_WAITING_RETRY: {"icon": "⏳", "color": "#f39c12", "label": "Waiting for Replug"},
    STATUS_AWAITING_SERIAL: {"icon": "📝", "color": "#9b59b6", "label": "Enter Serial Number"},
}

class DeviceTask:
    def __init__(self, port: str, device_number: int = 0, usb_location: str = ""):
        self.port = port
        self.device_number = device_number # Sequential number within this session
        self.usb_location = usb_location # USB hub/port location info
        self.status = STATUS_DETECTED
        self.start_time = time.time()
        self.end_time = 0.0
        self.message = "Initializing..."
        self.progress = 0
        self.firmware_version = None
        self.hardware_version = None
        self.mac_address = None
        self.battery_level = None
        self.pcb_id = None
        self.files_transferred = 0
        self.files_skipped = 0
        self.files_total = 6
        self.errors = []
        self.needs_user_action = False
        self.user_action_message = ""
        self.retry_requested = False
        self.i2c_error_count = 0
        self.firmware_flashed = False
        self.resumed_from_battery_error = False
        self.force_action = None # 'flash_firmware' or 'flash_audio' or None
        
        # Device creation fields
        self.serial_number = None  # 4-digit serial number entered by user
        self.gs1_barcode = None    # 14-digit GS1 (lot + serial)
        self.device_id = None      # Backend device ID after creation
        self.device_api_key = None # Device API key (shown only once)
        
        # Detailed Step Status
        self.step_firmware = "pending" # pending, skipped, flashed, failed
        self.step_backend = "pending"  # pending, registered_new, registered_existing, failed
        self.step_audio = "pending"    # pending, skipped, transferred, failed
        self.step_device = "pending"   # pending, created, updated, failed, awaiting_serial

    def to_dict(self) -> dict:
        elapsed = (self.end_time or time.time()) - self.start_time
        info = STATUS_INFO.get(self.status, STATUS_INFO[STATUS_DETECTED])
        return {
            "port": self.port,
            "device_number": self.device_number,
            "usb_location": self.usb_location,
            "status": self.status,
            "status_label": info["label"],
            "status_icon": info["icon"],
            "status_color": info["color"],
            "message": self.message,
            "progress": self.progress,
            "firmware_version": self.firmware_version,
            "hardware_version": self.hardware_version,
            "mac_address": self.mac_address,
            "battery_level": self.battery_level,
            "pcb_id": self.pcb_id,
            "serial_number": self.serial_number,
            "gs1_barcode": self.gs1_barcode,
            "device_id": self.device_id,
            "files_transferred": self.files_transferred,
            "files_skipped": self.files_skipped,
            "files_total": self.files_total,
            "elapsed_seconds": round(elapsed, 1),
            "errors": self.errors,
            "is_complete": self.status in [STATUS_COMPLETED, STATUS_FAILED, STATUS_REMOVED],
            "needs_user_action": self.needs_user_action,
            "user_action_message": self.user_action_message,
            "steps": {
                "firmware": self.step_firmware,
                "backend": self.step_backend,
                "audio": self.step_audio,
                "device": self.step_device
            }
        }

class AutoProductionManager:
    def __init__(self, audio_dir: str = "audio", firmware_dir: str = "firmware", 
                 flash_firmware: bool = True, production_mode: bool = True,
                 register_backend: bool = True):
        self.audio_dir = Path(audio_dir)
        self.firmware_dir = Path(firmware_dir)
        self.flash_firmware_flag = flash_firmware
        self.production_mode = production_mode
        self.register_backend = register_backend
        
        self.active_devices: Dict[str, DeviceTask] = {}
        self.completed_history: List[DeviceTask] = []
        self.pending_resumes: Dict[str, DeviceTask] = {} # Store tasks waiting for replug
        self.port_locks: Dict[str, threading.Lock] = {} # Per-port locks to prevent concurrent access
        self.active_threads: Dict[str, threading.Thread] = {} # Track running threads per port
        self.lock = threading.RLock()  # RLock allows same thread to acquire multiple times (reentrant)
        self.running = True
        self.stats = {"total_programmed": 0, "total_failed": 0}
        
        # Lot number for device creation (set via UI before starting)
        self.lot_number = None  # 10-digit lot number
        self.lot_number_set = False  # Whether user has confirmed lot number
        
        # Auth state
        self.auth_status = "checking" # checking, authenticated, failed, offline
        self.auth_error = None
        self.auth_user = None
        
        # Session tracking
        self.session_start_time = time.time()
        self.device_counter = 0 # Incremented for each new device
        self.completion_times: List[float] = [] # Track completion times for averages
        
        # Initialize session logging
        self.session_log_file = Path(f"session_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        self._init_csv_log()

        # Initialize programmers to check resources
        self.fw_programmer = AutoTQFirmwareProgrammer(firmware_dir=str(self.firmware_dir))
        self.firmware_version = None
        
        # Initialize Backend Client and Downloader
        self.client: Optional[AutoTQClient] = None
        self.setup_tool: Optional[AutoTQSetup] = None
        self.backend_url = "https://api.theautotq.com"
        
        if self.register_backend:
            self._init_backend()

        # Always try to refresh firmware cache on startup (after potential download)
        self.fw_programmer.find_latest_firmware()
        
        if self.flash_firmware_flag:
            if not self.fw_programmer.latest_firmware:
                print(f"{Colors.WARNING}⚠️  Re-scanning for firmware...{Colors.ENDC}")
                self.fw_programmer.find_latest_firmware()
                
            if not self.fw_programmer.latest_firmware:
                print(f"{Colors.FAIL}❌ No firmware found in {self.firmware_dir}!{Colors.ENDC}")
                sys.exit(1)
            else:
                fw = self.fw_programmer.latest_firmware
                self.firmware_version = fw['version']
                print(f"{Colors.OKGREEN}✅ Loaded Firmware: {fw['version']}{Colors.ENDC}")
            
        if not self.audio_dir.exists():
            print(f"{Colors.FAIL}❌ Audio directory not found: {self.audio_dir}!{Colors.ENDC}")
            sys.exit(1)

    def _init_csv_log(self):
        """Initialize the CSV log file with headers."""
        try:
            with open(self.session_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'Port', 'MAC Address', 'PCB ID', 'GS1 Barcode', 'Device ID', 'Firmware', 'Status', 'Step:Firmware', 'Step:Backend', 'Step:Audio', 'Step:Device', 'Duration (s)', 'Error'])
            print(f"{Colors.OKGREEN}📝 Session log initialized: {self.session_log_file}{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}❌ Failed to init session log: {e}{Colors.ENDC}")

    def _log_to_csv(self, task: DeviceTask):
        """Append a completed task to the CSV log."""
        try:
            with open(self.session_log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    task.port,
                    task.mac_address or 'Unknown',
                    task.pcb_id or 'N/A',
                    task.gs1_barcode or 'N/A',
                    task.device_id or 'N/A',
                    task.firmware_version or 'Unknown',
                    task.status,
                    task.step_firmware,
                    task.step_backend,
                    task.step_audio,
                    task.step_device,
                    f"{task.end_time - task.start_time:.1f}",
                    "; ".join(task.errors) if task.errors else ""
                ])
        except Exception as e:
            print(f"{Colors.FAIL}⚠️ Failed to write to log: {e}{Colors.ENDC}")

    def _play_sound(self, success: bool):
        """Play success or failure sound if available."""
        if HAS_WINSOUND:
            try:
                if success:
                    winsound.Beep(1000, 200) # High pitch, short
                    time.sleep(0.1)
                    winsound.Beep(1500, 300) # Higher pitch
                else:
                    winsound.Beep(300, 500) # Low pitch, long.
            except Exception:
                pass

    def _get_usb_location(self, port: str) -> str:
        """Try to extract USB hub/port location from port info."""
        try:
            # Method 1: PySerial standard attributes (works best on Linux/Mac)
            for p in serial.tools.list_ports.comports():
                if p.device == port:
                    if p.location:
                        return f"USB:{p.location}"
                    
                    # Method 2: PowerShell WMI lookup (Windows specific robust method)
                    if sys.platform == "win32":
                        try:
                            import subprocess
                            # Use PowerShell to find the PNPDeviceID for this COM port
                            # Win32_PnPEntity where Name contains 'COMx'
                            cmd = f'Get-WmiObject Win32_PnPEntity | Where-Object {{ $_.Name -match "\\({port}\\)" }} | Select-Object -ExpandProperty PNPDeviceID'
                            result = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True, timeout=2)
                            pnp_id = result.stdout.strip()
                            
                            if pnp_id:
                                # Parse typical USB path from PNP ID
                                # Example: USB\VID_10C4&PID_EA60\0001
                                # Example Hub: USB\VID_xxxx...&LOCATION_1-4.2
                                
                                # Try to get parent (Hub) info if possible, or just use the unique instance ID
                                # Extract the last part which is often the unique instance or location
                                parts = pnp_id.split('\\')
                                if len(parts) >= 3:
                                    unique_id = parts[-1]
                                    return f"USB ID:{unique_id}"
                        except Exception:
                            pass

                    # Method 3: Fallback to serial number
                    if p.serial_number:
                        return f"SN:{p.serial_number}"
                        
                    # Method 4: Generic fallback
                    desc = p.description
                    if "USB Serial Device" in desc:
                        return "USB Port"
                    return desc[:20]
        except Exception:
            pass
        return "Unknown"

    def _init_backend(self):
        """Initialize backend connection and check authentication."""
        try:
            self.client = AutoTQClient(base_url=self.backend_url)
            
            # Check if authentication is valid
            if self.client.is_authenticated():
                user = self.client.get_user_profile()
                self.auth_status = "authenticated"
                self.auth_user = user.get('username') if user else None
                print(f"{Colors.OKGREEN}✅ Backend authenticated as {self.auth_user}{Colors.ENDC}")
                
                # Initialize setup tool for firmware downloads
                self.setup_tool = AutoTQSetup(output_dir=str(Path.cwd()), base_url=self.backend_url)
                
                # Attempt to download latest firmware from backend
                self.download_latest_firmware_from_backend()
            else:
                self.auth_status = "failed"
                self.auth_error = "API key invalid or expired"
                print(f"{Colors.WARNING}⚠️ Backend authentication required.{Colors.ENDC}")
                print(f"{Colors.OKCYAN}💡 Login via the web dashboard at http://localhost:9090{Colors.ENDC}")
            
        except Exception as e:
            error_msg = str(e)
            if 'connection' in error_msg.lower() or 'refused' in error_msg.lower():
                self.auth_status = "offline"
                self.auth_error = "Server unreachable"
                print(f"{Colors.WARNING}⚠️ Backend server unreachable (offline mode){Colors.ENDC}")
            else:
                self.auth_status = "failed"
                self.auth_error = str(e)
                print(f"{Colors.WARNING}⚠️ Backend init failed: {e}{Colors.ENDC}")

    def authenticate(self, username: str, password: str) -> dict:
        """Authenticate with username/password, get API key, and save it."""
        import requests
        
        result = {"success": False, "error": None, "user": None}
        
        try:
            # Step 1: Login with username/password to get access token
            session = requests.Session()
            session.verify = True
            
            response = session.post(
                f"{self.backend_url}/auth/token",
                data={"username": username, "password": password},
                timeout=30
            )
            
            if response.status_code == 401:
                result["error"] = "Invalid username or password"
                return result
            elif response.status_code == 403:
                result["error"] = response.json().get('detail', 'Account locked or forbidden')
                return result
            elif response.status_code != 200:
                result["error"] = f"Login failed: {response.status_code}"
                return result
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                result["error"] = "No access token received"
                return result
            
            # Step 2: Create API key using the access token
            session.headers['Authorization'] = f"Bearer {access_token}"
            
            key_name = f"AutoTQ-Production-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            key_response = session.post(
                f"{self.backend_url}/users/me/api-keys",
                json={"name": key_name},
                timeout=30
            )
            
            if key_response.status_code not in (200, 201):
                result["error"] = f"Failed to create API key: {key_response.status_code}"
                return result
            
            key_data = key_response.json()
            api_key = key_data.get("key") or key_data.get("api_key")
            if not api_key:
                result["error"] = "No API key in response"
                return result
            
            # Step 3: Save the API key
            token_file = Path("autotq_token.json")
            with open(token_file, 'w') as f:
                json.dump({
                    "api_key": api_key,
                    "saved_at": datetime.now().isoformat() + "Z"
                }, f, indent=2)
            
            # Step 4: Re-initialize the client with the new key
            self.client = AutoTQClient(base_url=self.backend_url)
            if self.client.is_authenticated():
                user = self.client.get_user_profile()
                self.auth_status = "authenticated"
                self.auth_user = user.get('username') if user else username
                self.auth_error = None
                self.register_backend = True
                
                # Initialize setup tool
                self.setup_tool = AutoTQSetup(output_dir=str(Path.cwd()), base_url=self.backend_url)
                
                result["success"] = True
                result["user"] = self.auth_user
                print(f"{Colors.OKGREEN}✅ Authenticated as {self.auth_user}{Colors.ENDC}")
            else:
                result["error"] = "API key validation failed"
            
        except requests.exceptions.ConnectionError:
            result["error"] = "Cannot connect to server"
            self.auth_status = "offline"
        except Exception as e:
            result["error"] = str(e)
        
        return result

    def download_latest_firmware_from_backend(self):
        """Downloads the latest firmware from the backend API if available."""
        if not self.setup_tool or not self.client.is_authenticated():
            return

        print(f"{Colors.OKBLUE}☁️ Checking for latest firmware...{Colors.ENDC}")
        try:
            # Use get_latest_firmware_version instead of get_firmware_versions
            latest_fw = self.setup_tool.get_latest_firmware_version()
            if latest_fw:
                version_num = latest_fw.get('version_number')
                print(f"{Colors.OKCYAN}ℹ️ Found latest version: v{version_num}{Colors.ENDC}")
                
                # Download it
                if self.setup_tool.download_firmware(latest_fw):
                    print(f"{Colors.OKGREEN}✅ Firmware v{version_num} downloaded/verified.{Colors.ENDC}")
                else:
                    print(f"{Colors.FAIL}❌ Failed to download firmware v{version_num}.{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}⚠️ No firmware versions found on server.{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}❌ Firmware check failed: {e}{Colors.ENDC}")

    def get_state(self) -> dict:
        with self.lock:
            # Combine active and pending tasks for display
            all_active = list(self.active_devices.values()) + list(self.pending_resumes.values())
            devices = [task.to_dict() for task in all_active]
            recent = [task.to_dict() for task in self.completed_history[-10:]]
        
        # Calculate session stats
        session_duration = time.time() - self.session_start_time
        avg_time = sum(self.completion_times) / len(self.completion_times) if self.completion_times else 0
        
        # Get list of log files
        log_files = sorted(glob.glob("session_log_*.csv"), reverse=True)[:20]
        
        return {
            "devices": devices,
            "recent_completed": recent,
            "stats": self.stats,
            "firmware_version": self.firmware_version,
            "flash_enabled": self.flash_firmware_flag,
            "backend_enabled": self.register_backend,
            "production_mode": self.production_mode,
            "lot_number": self.lot_number,
            "lot_number_set": self.lot_number_set,
            "auth": {
                "status": self.auth_status,
                "user": self.auth_user,
                "error": self.auth_error,
            },
            "session": {
                "duration_seconds": round(session_duration, 0),
                "total_devices": self.device_counter,
                "avg_time_seconds": round(avg_time, 1),
                "devices_per_hour": round((self.stats["total_programmed"] / (session_duration / 3600)), 1) if session_duration > 60 else 0,
                "current_log_file": str(self.session_log_file),
            },
            "log_files": log_files,
        }

    def request_retry(self, port: str) -> bool:
        with self.lock:
            # Check pending resumes first
            if port in self.pending_resumes:
                task = self.pending_resumes[port]
                task.retry_requested = True
                task.needs_user_action = False
                # Move back to active if port is available (handled in scan loop)
                return True
                
            if port in self.active_devices:
                task = self.active_devices[port]
                if task.needs_user_action:
                    task.retry_requested = True
                    task.needs_user_action = False
                    return True
        return False
        
    def request_manual_action(self, port: str, action: str) -> bool:
        """Queue a manual action (flash_firmware or flash_audio) for a device"""
        with self.lock:
            # Only allow actions on active devices, not pending resumes (need to be plugged in)
            if port in self.active_devices:
                task = self.active_devices[port]
                if task.status in [STATUS_COMPLETED, STATUS_FAILED, STATUS_DETECTED]: # Can only restart if done or new
                    # Check if thread is already running (use our tracking)
                    if port in self.active_threads and self.active_threads[port].is_alive():
                        # Thread is still running
                        return False
                    
                    print(f"{Colors.OKCYAN}[{port}] Manual action requested: {action}{Colors.ENDC}")
                    
                    # Reset task state
                    task.status = STATUS_DETECTED
                    task.message = f"Manual start: {action}"
                    task.progress = 0
                    task.start_time = time.time()
                    task.end_time = 0.0
                    task.errors = []
                    task.force_action = action
                    
                    # Reset steps based on action
                    if action == 'flash_firmware':
                        task.firmware_flashed = False # Force re-flash
                        task.step_firmware = "pending"
                        task.step_audio = "pending"
                        task.step_backend = "pending"
                    elif action == 'flash_audio':
                        task.step_audio = "pending"
                        # Keep other states
                    
                    # Restart processing thread
                    t = threading.Thread(target=self.process_device, args=(port, task), daemon=True, name=f"thread-{port}")
                    self.active_threads[port] = t
                    t.start()
                    return True
        return False

    def log_status(self, port: str, status: str, message: str = "", progress: int = None):
        with self.lock:
            task = None
            if port in self.active_devices:
                task = self.active_devices[port]
            elif port in self.pending_resumes:
                task = self.pending_resumes[port]
                
            if task:
                task.status = status
                task.message = message
                if progress is not None:
                    task.progress = progress
                
                info = STATUS_INFO.get(status, STATUS_INFO[STATUS_DETECTED])
                color = Colors.OKCYAN
                if status == STATUS_COMPLETED: color = Colors.OKGREEN
                elif status == STATUS_FAILED: color = Colors.FAIL
                elif status == STATUS_FLASHING: color = Colors.HEADER
                elif status == STATUS_TRANSFERRING: color = Colors.OKBLUE
                elif status == STATUS_NEEDS_BATTERY: color = Colors.FAIL
                elif status == STATUS_WAITING_RETRY: color = Colors.WARNING
                    
                timestamp = time.strftime("%H:%M:%S")
                print(f"{color}[{timestamp}] [{port}] {info['icon']} {status}: {message}{Colors.ENDC}")

    def check_for_battery_error(self, programmer: AutoTQDeviceProgrammer, task: DeviceTask) -> bool:
        with programmer.response_lock:
            for response in programmer.device_responses:
                if response['type'] == 'text':
                    text = response['data']
                    if 'i2cWriteReadNonStop returned Error' in text or 'Wire.cpp' in text:
                        task.i2c_error_count += 1
                elif response['type'] == 'json':
                    data = response['data']
                    if data.get('response') == 'error' and 'rejected' in data.get('message', '').lower():
                        return True
        return task.i2c_error_count >= 3

    def get_device_file_list(self, programmer: AutoTQDeviceProgrammer) -> Optional[List[str]]:
        with programmer.response_lock:
            programmer.device_responses = []
        if not programmer.send_command({"command": "list_files"}):
            return None
        start_time = time.time()
        while time.time() - start_time < 5.0:
            with programmer.response_lock:
                for response in programmer.device_responses:
                    if response['type'] == 'json':
                        data = response['data']
                        if data.get('command') == 'list_files' and 'files' in data:
                            return data['files']
            time.sleep(0.1)
        return None

    def get_device_info(self, programmer: AutoTQDeviceProgrammer) -> Dict[str, Any]:
        """Retrieve comprehensive device info using get_status"""
        info = {
            "mac": None,
            "fw_version": None,
            "hw_version": None,
            "battery": None
        }
        
        with programmer.response_lock:
            programmer.device_responses = []
            
        # Primary command: get_status
        if not programmer.send_command({"command": "get_status"}):
            return info
            
        start_time = time.time()
        while time.time() - start_time < 3.0:
            with programmer.response_lock:
                for response in programmer.device_responses:
                    if response['type'] == 'json':
                        data = response['data']
                        # Extract fields if present in this or any response
                        if 'mac_address' in data: info["mac"] = data['mac_address']
                        if 'fw_version' in data: info["fw_version"] = data['fw_version']
                        if 'hw_version' in data: info["hw_version"] = data['hw_version']
                        if 'battery_soc' in data: info["battery"] = data['battery_soc']
                        
                        # Fallback parsing
                        if not info["mac"] and 'mac' in data: info["mac"] = data['mac']
                        if not info["fw_version"] and 'version' in data: info["fw_version"] = data['version']
                        
                        # Return early if we have the basics
                        if info["mac"] and info["fw_version"]:
                            return info
            time.sleep(0.1)
            
        # Fallback commands if get_status failed to return everything
        if not info["mac"]:
            programmer.send_command({"command": "wifi_get_mac"})
            # Brief wait for fallback
            time.sleep(0.5)
            with programmer.response_lock:
                for response in programmer.device_responses:
                    if response['type'] == 'json':
                        data = response['data']
                        if 'mac' in data: info["mac"] = data['mac']
                        
        return info

    def wait_for_port(self, port: str, timeout: float = 10.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            found_ports = [p.device for p in serial.tools.list_ports.comports()]
            if port in found_ports:
                return True
            time.sleep(0.5)
        return False
    
    def get_port_lock(self, port: str) -> threading.Lock:
        """Get or create a lock for a specific port to prevent concurrent access."""
        with self.lock:
            if port not in self.port_locks:
                self.port_locks[port] = threading.Lock()
            return self.port_locks[port]
    
    def safe_close_port(self, programmer, delay: float = 0.5):
        """Safely close a serial connection with delay to ensure port is released."""
        try:
            programmer.disconnect()
        except Exception:
            pass
        time.sleep(delay) # Give OS time to fully release the port
    
    def is_port_busy(self, port: str) -> bool:
        """Check if there's already an active processing thread for this port."""
        with self.lock:
            if port in self.active_threads:
                thread = self.active_threads[port]
                if thread.is_alive():
                    return True
                else:
                    # Thread finished, clean up
                    del self.active_threads[port]
            return False
    
    def start_device_thread(self, port: str, task: DeviceTask):
        """Start a processing thread for a device, with proper tracking."""
        if self.is_port_busy(port):
            self.log(f"[{port}] Thread already running, skipping...", "WARNING")
            return
        
        t = threading.Thread(target=self.process_device, args=(port, task), daemon=True, name=f"thread-{port}")
        with self.lock:
            self.active_threads[port] = t
        t.start()
        
    def register_device_backend(self, port: str, mac: str, fw_version: Optional[str], hw_version: Optional[str]) -> Tuple[Optional[int], bool]:
        if not self.client or not self.register_backend:
            return None, False
        self.log_status(port, STATUS_REGISTERING, "Checking PCB registration...", progress=85)
        try:
            pcb = ensure_pcb_stage(self.client, mac=mac, fw=fw_version, hw=hw_version, stage_label='factory', allow_create=True)
            if pcb and 'id' in pcb:
                is_new = pcb.get('_is_new', False)
                status_str = "Created" if is_new else "Existing"
                self.log_status(port, STATUS_REGISTERING, f"PCB ID: {pcb['id']} ({status_str})", progress=90)
                return pcb['id'], is_new
            return None, False
        except Exception as e:
            self.log_status(port, STATUS_REGISTERING, f"⚠️ Backend Error: {e}")
            return None, False

    def set_lot_number(self, lot_number: str) -> Tuple[bool, str]:
        """Set the lot number for device creation. Must be exactly 10 digits."""
        lot_number = lot_number.strip()
        
        # Validate format: exactly 10 digits
        if not lot_number.isdigit():
            return False, "Lot number must contain only digits"
        if len(lot_number) != 10:
            return False, f"Lot number must be exactly 10 digits (got {len(lot_number)})"
        
        with self.lock:
            self.lot_number = lot_number
            self.lot_number_set = True
        
        print(f"{Colors.OKGREEN}✅ Lot number set: {lot_number}{Colors.ENDC}")
        return True, f"Lot number set to {lot_number}"

    def submit_serial_number(self, port: str, serial_number: str) -> Tuple[bool, str]:
        """Submit serial number for a device awaiting it. Creates device on backend."""
        serial_number = serial_number.strip()
        
        # Validate format: exactly 4 digits
        if not serial_number.isdigit():
            return False, "Serial number must contain only digits"
        if len(serial_number) != 4:
            return False, f"Serial number must be exactly 4 digits (got {len(serial_number)})"
        
        if not self.lot_number:
            return False, "Lot number not set. Please set lot number first."
        
        with self.lock:
            if port not in self.active_devices:
                return False, f"Device on {port} not found"
            task = self.active_devices[port]
            
            # Allow serial submission for AWAITING_SERIAL or COMPLETED devices without GS1
            if task.status not in [STATUS_AWAITING_SERIAL, STATUS_COMPLETED]:
                return False, f"Device not ready for serial number (status: {task.status})"
            
            if task.gs1_barcode:
                return False, f"Device already has GS1 barcode: {task.gs1_barcode}"
            
            if not task.mac_address:
                return False, "Device MAC address not available"
        
        # Create GS1 barcode
        gs1_barcode = self.lot_number + serial_number
        
        print(f"{Colors.OKCYAN}[{port}] Creating device: GS1={gs1_barcode}, MAC={task.mac_address}{Colors.ENDC}")
        
        try:
            # Step 1: Create or update device
            success, message, device_id = self._create_device_on_backend(
                gs1_barcode=gs1_barcode,
                mac_address=task.mac_address,
                port=port
            )
            
            if not success:
                task.step_device = "failed"
                task.errors.append(f"Device creation failed: {message}")
                self.log_status(port, STATUS_FAILED, f"Device creation failed: {message}", progress=100)
                self._play_sound(success=False)
                return False, message
            
            # Determine if created new or verified existing
            is_existing = "already" in message.lower() or "updated" in message.lower()
            
            # Check if message contains existing GS1 (device was already registered with different GS1)
            actual_gs1 = gs1_barcode
            if "GS1:" in message:
                # Extract the existing GS1 from message like "Device already registered (GS1: xxxx)"
                match = re.search(r'GS1:\s*([^\s\)]+)', message)
                if match:
                    actual_gs1 = match.group(1)
                    print(f"{Colors.OKGREEN}[{port}] Using existing GS1: {actual_gs1}{Colors.ENDC}")
            
            # Step 2: Update task
            with self.lock:
                task.serial_number = serial_number
                task.gs1_barcode = actual_gs1  # Use actual GS1 (might be existing one)
                task.device_id = device_id
                task.step_device = "verified" if is_existing else "created"
                task.needs_user_action = False
                task.user_action_message = ""
            
            # Step 3: Verify device was created correctly
            verify_success, verify_msg = self._verify_device_on_backend(gs1_barcode, task.mac_address)
            if not verify_success:
                task.step_device = "failed"
                task.errors.append(f"Device verification failed: {verify_msg}")
                self.log_status(port, STATUS_FAILED, f"Device verification failed: {verify_msg}", progress=100)
                self._play_sound(success=False)
                return False, verify_msg
            
            # Success!
            duration = time.time() - task.start_time
            status_msg = "verified" if is_existing else "created"
            self.log_status(port, STATUS_COMPLETED, f"Device {gs1_barcode} {status_msg}! ({duration:.1f}s)", progress=100)
            self._play_sound(success=True)
            self._log_to_csv(task)
            
            with self.lock:
                self.stats["total_programmed"] += 1
                self.completion_times.append(duration)
            
            print(f"{Colors.OKGREEN}✅ [{port}] Device {status_msg}: GS1={gs1_barcode}, Device ID={device_id}{Colors.ENDC}")
            return True, f"Device {gs1_barcode} {status_msg} successfully"
            
        except Exception as e:
            task.step_device = "failed"
            task.errors.append(str(e))
            self.log_status(port, STATUS_FAILED, str(e), progress=100)
            self._play_sound(success=False)
            return False, str(e)

    def _safe_json(self, response) -> Optional[dict]:
        """Safely parse JSON from response, returning None if empty or invalid."""
        try:
            if response.text and response.text.strip():
                return response.json()
        except Exception:
            pass
        return None

    def _create_device_on_backend(self, gs1_barcode: str, mac_address: str, port: str) -> Tuple[bool, str, Optional[int]]:
        """Create device on backend with GS1 and MAC, handling existing devices."""
        if not self.client:
            return False, "Backend client not initialized", None
        
        # Debug: print the base URL being used
        # Note: base_url doesn't include /api/v1, we need to add it for device endpoints
        base = f"{self.client.base_url}/api/v1"
        print(f"{Colors.OKCYAN}[Device API] Using base URL: {base}{Colors.ENDC}")
        
        try:
            # First, check if a device with this MAC already exists
            mac_url = f"{base}/devices/by_mac/{mac_address}"
            print(f"{Colors.OKCYAN}[Device API] GET {mac_url}{Colors.ENDC}")
            mac_check_resp = self.client.session.get(mac_url, timeout=10)
            print(f"{Colors.OKCYAN}[Device API] Response: {mac_check_resp.status_code} - {mac_check_resp.text[:200] if mac_check_resp.text else '(empty)'}{Colors.ENDC}")
            
            if mac_check_resp.status_code == 200:
                # Device with this MAC already exists
                existing_by_mac = self._safe_json(mac_check_resp)
                if not existing_by_mac:
                    return False, f"Invalid JSON response from MAC check", None
                    
                existing_gs1 = existing_by_mac.get('gs1_barcode', '')
                existing_id = existing_by_mac.get('id')
                
                if existing_gs1 == gs1_barcode:
                    # Same GS1 - device already properly registered
                    print(f"{Colors.OKGREEN}✅ Device already exists with correct GS1: {gs1_barcode}{Colors.ENDC}")
                    return True, "Device already exists (verified)", existing_id
                else:
                    # Different GS1 - MAC is already used by another device
                    # This is OK - device was already registered previously, just return success
                    print(f"{Colors.OKGREEN}✅ Device already registered with GS1: {existing_gs1}{Colors.ENDC}")
                    return True, f"Device already registered (GS1: {existing_gs1})", existing_id
            
            elif mac_check_resp.status_code not in [404, 422]:
                # Unexpected error
                return False, f"MAC check failed ({mac_check_resp.status_code}): {mac_check_resp.text[:100]}", None
            
            # If MAC not found (404/422), proceed to check by GS1 or create new
            
            # Check if device exists by GS1
            gs1_url = f"{base}/devices/{gs1_barcode}"
            print(f"{Colors.OKCYAN}[Device API] GET {gs1_url}{Colors.ENDC}")
            check_resp = self.client.session.get(gs1_url, timeout=10)
            print(f"{Colors.OKCYAN}[Device API] Response: {check_resp.status_code} - {check_resp.text[:200] if check_resp.text else '(empty)'}{Colors.ENDC}")
            
            if check_resp.status_code == 200:
                # Device exists by GS1 - update MAC if needed
                existing = self._safe_json(check_resp)
                if not existing:
                    return False, f"Invalid JSON response from GS1 check", None
                    
                existing_mac = existing.get('mac_address', '')
                
                if existing_mac and existing_mac != mac_address:
                    # MAC mismatch - this is a potential issue
                    return False, f"GS1 {gs1_barcode} already exists with different MAC ({existing_mac})", None
                
                if not existing_mac or existing_mac != mac_address:
                    # Update MAC address
                    mac_update_url = f"{base}/devices/{gs1_barcode}/mac-address"
                    print(f"{Colors.OKCYAN}[Device API] PUT {mac_update_url}{Colors.ENDC}")
                    mac_resp = self.client.session.put(
                        mac_update_url,
                        json={"mac_address": mac_address},
                        timeout=10
                    )
                    print(f"{Colors.OKCYAN}[Device API] Response: {mac_resp.status_code}{Colors.ENDC}")
                    if mac_resp.status_code not in [200, 201]:
                        return False, f"Failed to associate MAC: {mac_resp.text}", None
                
                device_id = existing.get('id')
                return True, "Device updated", device_id
            
            elif check_resp.status_code == 404:
                # Device doesn't exist - create it
                create_url = f"{base}/devices/"
                create_data = {
                    "gs1_barcode": gs1_barcode,
                    "model_name": "AutoTQ",
                    "mac_address": mac_address,
                    "inventory_status": "received_pending_review"
                }
                print(f"{Colors.OKCYAN}[Device API] POST {create_url} with {create_data}{Colors.ENDC}")
                create_resp = self.client.session.post(create_url, json=create_data, timeout=10)
                print(f"{Colors.OKCYAN}[Device API] Response: {create_resp.status_code} - {create_resp.text[:200] if create_resp.text else '(empty)'}{Colors.ENDC}")
                
                if create_resp.status_code == 201:
                    data = self._safe_json(create_resp)
                    if data:
                        device_id = data.get('id')
                        api_key = data.get('api_key')
                        if api_key:
                            print(f"{Colors.WARNING}⚠️ Device API Key (save this!): {api_key}{Colors.ENDC}")
                        return True, "Device created", device_id
                    else:
                        return True, "Device created (no response body)", None
                elif create_resp.status_code == 409:
                    return False, "Device with this GS1 already exists (conflict)", None
                else:
                    return False, f"Create failed ({create_resp.status_code}): {create_resp.text[:100]}", None
            else:
                return False, f"Check failed ({check_resp.status_code}): {check_resp.text[:100]}", None
                
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", None
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"Error: {str(e)}", None

    def _verify_device_on_backend(self, gs1_barcode: str, expected_mac: str) -> Tuple[bool, str]:
        """Verify device exists on backend with correct MAC."""
        if not self.client:
            return False, "Backend client not initialized"
        
        try:
            # Note: base_url doesn't include /api/v1, we need to add it
            base = f"{self.client.base_url}/api/v1"
            resp = self.client.session.get(
                f"{base}/devices/{gs1_barcode}",
                timeout=10
            )
            
            if resp.status_code != 200:
                return False, f"Device not found after creation ({resp.status_code})"
            
            data = resp.json()
            actual_mac = data.get('mac_address', '')
            
            if actual_mac != expected_mac:
                return False, f"MAC mismatch: expected {expected_mac}, got {actual_mac}"
            
            return True, "Device verified"
            
        except Exception as e:
            return False, f"Verification error: {str(e)}"

    def handle_battery_pause(self, port: str, task: DeviceTask):
        """Handle the pause logic for battery insertion"""
        self.log_status(port, STATUS_NEEDS_BATTERY, "Battery Required - Waiting for unplug...", progress=task.progress)
        print(f"{Colors.WARNING}[{port}] 🔋 ACTION: Unplug USB -> Insert Battery -> Replug USB{Colors.ENDC}")
        
        task.needs_user_action = True
        task.user_action_message = "Unplug USB -> Insert Battery -> Replug USB"
        
        # Move task to pending resume queue so it persists when unplugged
        with self.lock:
            if port in self.active_devices:
                self.pending_resumes[port] = task
                del self.active_devices[port]
        
        # Task is now "dormant" in pending_resumes, waiting for scan_loop to pick it up when port reappears

    def process_device(self, port: str, task: DeviceTask):
        # Note: task is passed in, might be a resumed task
        
        # Acquire per-port lock to prevent concurrent operations on the same port
        port_lock = self.get_port_lock(port)
        
        # Try to acquire lock with timeout - if port is busy, wait
        lock_acquired = port_lock.acquire(timeout=30)
        if not lock_acquired:
            self.log_status(port, STATUS_FAILED, "Port busy - could not acquire lock", progress=0)
            task.status = STATUS_FAILED
            task.errors.append("Port lock timeout - another operation in progress")
            return
        
        try:
            # Determine what steps to run based on flags and manual overrides
            do_firmware = self.flash_firmware_flag
            do_audio = True
            
            # Manual override logic
            if task.force_action == 'flash_firmware':
                do_firmware = True
                do_audio = False # Just flash FW? User said "flash all the firmware files OR flash audio files"
                                 # usually FW flash implies system reset, so maybe check audio after?
                                 # Let's assume buttons mean "DO THIS SPECIFIC THING"
                                 # But if I flash firmware, I should probably also verify audio if it's a full provision.
                                 # Let's stick to "Auto" logic but force the specific step to happen even if skipped previously.
                task.firmware_flashed = False # Force it
                do_audio = True # Proceed to audio after FW
            elif task.force_action == 'flash_audio':
                do_firmware = False
                do_audio = True
            
            # --- PHASE 0: PRE-CHECK ---
            # If not already flashed by us in this session, check if we can skip flashing
            skip_flash = False
            pre_check_prog = None
            if do_firmware and not task.firmware_flashed and not task.resumed_from_battery_error:
                self.log_status(port, STATUS_CONNECTING, "Checking existing firmware...", progress=2)
                
                # Quick connect to check version (short timeout for blank devices)
                try:
                    pre_check_prog = AutoTQDeviceProgrammer(port=port, audio_dir=str(self.audio_dir), stabilize_ms=1500)
                    if pre_check_prog.connect():
                        # Use new consolidated info getter
                        info = self.get_device_info(pre_check_prog)
                        current_fw = info.get("fw_version")
                        
                        # ALWAYS close before proceeding
                        self.safe_close_port(pre_check_prog, delay=1.0)
                        pre_check_prog = None
                        
                        if current_fw:
                            # Normalize version strings (remove 'v' prefix for comparison)
                            target_v = self.firmware_version.replace('v', '') if self.firmware_version else ''
                            current_v = current_fw.replace('v', '')
                            
                            if target_v and current_v == target_v:
                                self.log_status(port, STATUS_DETECTED, f"Firmware up-to-date ({current_fw}). Skipping flash.", progress=5)
                                skip_flash = True
                                task.firmware_version = current_fw
                                task.firmware_flashed = True # Treat as done
                                task.step_firmware = "skipped"
                        else:
                            self.log_status(port, STATUS_CONNECTING, "No firmware detected. Will flash.", progress=3)
                    else:
                        # Could not connect - device might be blank or unresponsive
                        self.log_status(port, STATUS_CONNECTING, "Device may be blank. Proceeding to flash.", progress=3)
                        if pre_check_prog:
                            self.safe_close_port(pre_check_prog, delay=0.5)
                            pre_check_prog = None
                except Exception as pre_e:
                    self.log_status(port, STATUS_CONNECTING, f"Pre-check failed: {str(pre_e)[:30]}. Proceeding to flash.", progress=3)
                    if pre_check_prog:
                        try:
                            self.safe_close_port(pre_check_prog, delay=0.5)
                        except:
                            pass
                        pre_check_prog = None
            
            # FORCE OVERRIDE: If manual action was firmware, don't skip even if versions match
            if task.force_action == 'flash_firmware':
                skip_flash = False
                task.firmware_flashed = False # Also reset this since pre-check might have set it
                task.step_firmware = "pending"

            # --- PHASE 1: FIRMWARE ---
            # Only flash if enabled AND NOT skipped AND NOT already flashed
            if do_firmware and not task.firmware_flashed and not skip_flash:
                self.log_status(port, STATUS_FLASHING, "Preparing to flash...", progress=5)
                
                # Extra delay to ensure port is fully released from pre-check
                time.sleep(1.0)
                
                try:
                    fw_prog = AutoTQFirmwareProgrammer(firmware_dir=str(self.firmware_dir), port=port)
                    target_version = 'unknown'
                    if fw_prog.latest_firmware:
                        target_version = fw_prog.latest_firmware.get('version', 'unknown')
                        task.firmware_version = target_version
                        self.log_status(port, STATUS_FLASHING, f"Flashing {target_version}...", progress=10)
                    
                    success = fw_prog.program_device(erase_first=True, verify=True, smart_erase=True, production_mode=False) # Enable verify for safety
                    if not success:
                        task.step_firmware = "failed"
                        raise RuntimeError("Esptool reported failure")
                    
                    task.firmware_flashed = True 
                    task.step_firmware = "flashed"
                    
                except Exception as e:
                    task.step_firmware = "failed"
                    raise RuntimeError(f"Firmware flash failed: {str(e)}")

                self.log_status(port, STATUS_CONNECTING, "Device rebooting...", progress=55)
                time.sleep(2.0) # Longer delay to ensure clean reboot
                self.wait_for_port(port, timeout=15.0)
            elif task.resumed_from_battery_error:
                self.log_status(port, STATUS_CONNECTING, "Resuming after battery fix...", progress=55)

            # --- PHASE 2: CONNECTING ---
            self.log_status(port, STATUS_CONNECTING, "Connecting to device...", progress=60)
            
            # Wait a bit for port to stabilize after firmware flash
            time.sleep(0.5)
            
            dev_prog = AutoTQDeviceProgrammer(port=port, audio_dir=str(self.audio_dir), stabilize_ms=2500)
            
            connected = False
            last_error = None
            for i in range(5):
                try:
                    if dev_prog.connect():
                        connected = True
                        break
                except Exception as conn_err:
                    last_error = str(conn_err)
                
                # Try to release the port before retrying
                try:
                    dev_prog.disconnect()
                except:
                    pass
                
                if i < 4:
                    delay = 1.5 + (i * 0.5)
                    self.log_status(port, STATUS_CONNECTING, f"Retry {i+1} in {delay:.1f}s...", progress=60 + i*2)
                    time.sleep(delay)
                    # Recreate programmer for fresh connection
                    dev_prog = AutoTQDeviceProgrammer(port=port, audio_dir=str(self.audio_dir), stabilize_ms=2500)
            
            if not connected:
                err_msg = f"Could not connect after 5 attempts"
                if last_error:
                    err_msg += f": {last_error[:50]}"
                raise RuntimeError(err_msg)
                
            try:
                # --- PHASE 2.5: METADATA ---
                self.log_status(port, STATUS_CHECKING, "Fetching device info...", progress=70)
                
                # Consolidated metadata fetching using get_status
                info = self.get_device_info(dev_prog)
                
                # Update task with retrieved info
                if info["fw_version"]: task.firmware_version = info["fw_version"]
                if info["hw_version"]: task.hardware_version = info["hw_version"]
                if info["mac"]: task.mac_address = info["mac"]
                if info["battery"]: task.battery_level = info["battery"]
                
                # VALIDATION: Verify firmware version if we just flashed it
                if task.step_firmware == "flashed" and task.firmware_version:
                    # Clean versions for comparison
                    flashed_v = target_version.replace('v', '') if 'target_version' in locals() else ''
                    read_v = task.firmware_version.replace('v', '')
                    if flashed_v and read_v != flashed_v:
                         self.log_status(port, STATUS_FAILED, f"FW Mismatch! Exp:{flashed_v} Got:{read_v}", progress=70)
                         task.step_firmware = "failed"
                         raise RuntimeError(f"Firmware verification failed. Expected {flashed_v}, got {read_v}")
                
                if task.mac_address:
                    self.log_status(port, STATUS_CHECKING, f"MAC: {task.mac_address}", progress=75)
                    if self.register_backend:
                        pcb_id, is_new = self.register_device_backend(port, task.mac_address, task.firmware_version, task.hardware_version)
                        if pcb_id:
                            # VALIDATION: Verify backend record exists
                            # Try both /api/v1/pcbs and /pcbs endpoints
                            try:
                                verified = False
                                for prefix in ["/api/v1", ""]:
                                    verify_url = f"{self.client.base_url}{prefix}/pcbs/{pcb_id}"
                                    verify_pcb = self.client.session.get(verify_url, timeout=5)
                                    if verify_pcb.status_code == 200:
                                        verified = True
                                        break
                                
                                if verified:
                                    task.pcb_id = pcb_id
                                    task.step_backend = "registered_new" if is_new else "registered_existing"
                                else:
                                    # Upsert succeeded but verify failed - trust the upsert
                                    print(f"{Colors.WARNING}⚠️ PCB verify endpoint returned {verify_pcb.status_code}, but upsert succeeded. Continuing.{Colors.ENDC}")
                                    task.pcb_id = pcb_id
                                    task.step_backend = "registered_new" if is_new else "registered_existing"
                            except Exception as e:
                                # Verify failed but upsert succeeded - trust the upsert
                                print(f"{Colors.WARNING}⚠️ PCB verify failed ({e}), but upsert succeeded. Continuing.{Colors.ENDC}")
                                task.pcb_id = pcb_id
                                task.step_backend = "registered_new" if is_new else "registered_existing"
                        else:
                            task.step_backend = "failed"

                if do_audio:
                    # --- PHASE 3: CHECKING FILES ---
                    self.log_status(port, STATUS_CHECKING, "Checking files...", progress=90)
                    existing_files = self.get_device_file_list(dev_prog) or []
                    required_files = dev_prog.REQUIRED_AUDIO_FILES
                    task.files_total = len(required_files)
                    
                    if task.force_action == 'flash_audio':
                        # If forcing audio, we can't easily force overwrite without deleting first or having a "force" flag in download_file
                        # Standard check works fine unless files are corrupted but present.
                        files_to_transfer = [f for f in required_files if f not in existing_files]
                    else:
                        files_to_transfer = [f for f in required_files if f not in existing_files]
                        
                    task.files_skipped = len(required_files) - len(files_to_transfer)
                            
                    # --- PHASE 4: TRANSFERRING ---
                    if files_to_transfer:
                        self.log_status(port, STATUS_TRANSFERRING, f"0/{len(files_to_transfer)} files", progress=92)
                        if self.production_mode:
                            dev_prog.set_transfer_speed("fast")
                        
                        for i, filename in enumerate(files_to_transfer):
                            pct = 92 + int((i / len(files_to_transfer)) * 7)
                            self.log_status(port, STATUS_TRANSFERRING, f"{filename} ({i+1}/{len(files_to_transfer)})", progress=pct)
                            file_path = self.audio_dir / filename
                            
                            file_success = False
                            for attempt in range(3):
                                task.i2c_error_count = 0
                                if dev_prog.transfer_file_to_device(file_path, show_progress=False):
                                    file_success = True
                                    break
                                
                                # Check for battery error
                                if self.check_for_battery_error(dev_prog, task):
                                    dev_prog.disconnect()
                                    self.handle_battery_pause(port, task)
                                    return # Exit thread, scan_loop will resume task later
                                
                                time.sleep(1.0)
                            
                            if file_success:
                                task.files_transferred += 1
                            else:
                                task.step_audio = "failed"
                                raise RuntimeError(f"Failed to transfer {filename}")
                            if i < len(files_to_transfer) - 1:
                                time.sleep(0.5)
                        task.step_audio = "transferred"
                        
                        # VALIDATION: Check files exist after transfer
                        self.log_status(port, STATUS_CHECKING, "Verifying audio files...", progress=98)
                        final_files = self.get_device_file_list(dev_prog) or []
                        missing_after = [f for f in required_files if f not in final_files]
                        if missing_after:
                            task.step_audio = "failed"
                            raise RuntimeError(f"Audio verification failed. Missing: {missing_after}")

                    else:
                        self.log_status(port, STATUS_TRANSFERRING, "All files present", progress=99)
                        if task.step_audio == "pending":
                             task.step_audio = "skipped"

                # Success (pre-device creation)!
                task.end_time = time.time()
                duration = task.end_time - task.start_time
                
                # If lot number is set, wait for serial number input before marking complete
                if self.lot_number and self.lot_number_set and self.register_backend:
                    task.step_device = "awaiting_serial"
                    task.needs_user_action = True
                    task.user_action_message = "Enter 4-digit serial number"
                    self.log_status(port, STATUS_AWAITING_SERIAL, f"Ready for serial (MAC: {task.mac_address})", progress=100)
                    # Don't play success sound yet - wait until device is fully created
                else:
                    # No device creation needed, mark as complete
                    self.log_status(port, STATUS_COMPLETED, f"Done in {duration:.1f}s", progress=100)
                    self._play_sound(success=True)
                    self._log_to_csv(task)
                    
                    with self.lock:
                        self.stats["total_programmed"] += 1
                        self.completion_times.append(duration)
                        if port in self.pending_resumes:
                            del self.pending_resumes[port]
                
            finally:
                dev_prog.disconnect()

        except Exception as e:
            task.end_time = time.time()
            task.errors.append(str(e))
            self.log_status(port, STATUS_FAILED, str(e), progress=0)
            
            # Actions on failure
            self._play_sound(success=False)
            self._log_to_csv(task)
            
            with self.lock:
                self.stats["total_failed"] += 1
                if port in self.pending_resumes:
                    del self.pending_resumes[port]
        
        finally:
            # Always release the port lock
            try:
                port_lock.release()
            except:
                pass

    def wait_for_auth(self):
        """Block until authentication is successful or skipped."""
        if self.auth_status == "authenticated":
            return
            
        print(f"{Colors.WARNING}Waiting for authentication...{Colors.ENDC}")
        
        while self.running:
            # Check if auth status changed (via API)
            if self.auth_status == "authenticated":
                return
            
            # Check if we should skip backend
            if not self.register_backend:
                return
                
            time.sleep(0.5)

    def scan_loop(self):
        print(f"\n{Colors.HEADER}{Colors.BOLD}AutoTQ Production Station{Colors.ENDC}")
        print(f"{Colors.OKBLUE}Dashboard: http://localhost:9090{Colors.ENDC}\n")
        
        # BLOCK HERE UNTIL AUTHENTICATED
        self.wait_for_auth()
        
        last_port_count = -1 # Track changes to reduce log spam
        scan_count = 0
        
        while self.running:
            try:
                # Use include_all=True to be more permissive with device detection
                # Use quiet=True to suppress repeated log messages
                current_ports_info = self.fw_programmer.list_available_ports(include_all=True, quiet=True)
                current_ports = {p[0] for p in current_ports_info}
                
                # Only log when port count changes (reduce noise)
                scan_count += 1
                if len(current_ports) != last_port_count:
                    if current_ports:
                        print(f"{Colors.OKGREEN}[Scan #{scan_count}] Found {len(current_ports)} device(s): {', '.join(current_ports)}{Colors.ENDC}")
                    else:
                        print(f"{Colors.WARNING}[Scan #{scan_count}] No devices detected. Waiting...{Colors.ENDC}")
                    last_port_count = len(current_ports)
                
                with self.lock:
                    # 1. Handle removals
                    ports_to_remove = []
                    for port, task in self.active_devices.items():
                        if port not in current_ports:
                            # Only move to history if it was completed or failed, otherwise it's an "unplugged during op" error
                            # BUT we want to keep it visible if it just finished.
                            if task.status in [STATUS_COMPLETED, STATUS_FAILED]:
                                self.completed_history.append(task)
                                ports_to_remove.append(port)
                            elif task.status != STATUS_REMOVED:
                                task.status = STATUS_REMOVED
                                task.errors.append("Device unplugged")
                                # We can keep it in active_devices as "REMOVED" until plugged back in?
                                # Or move to history?
                                # If we move to history, the UI will show it in "Recent".
                                self.completed_history.append(task)
                                ports_to_remove.append(port)
                    
                    for port in ports_to_remove:
                        if port in self.active_devices:
                            del self.active_devices[port]
                    
                    # 2. Handle new devices OR resumes
                    for port in current_ports:
                        if port in self.pending_resumes:
                            # RESUMING A PAUSED DEVICE
                            # Check if thread is still running (shouldn't be, but just in case)
                            if self.is_port_busy(port):
                                continue
                                
                            print(f"{Colors.OKCYAN}[{port}] Device replugged - Resuming transfer...{Colors.ENDC}")
                            task = self.pending_resumes[port]
                            task.status = STATUS_CONNECTING
                            task.needs_user_action = False # Cleared automatically on replug
                            task.resumed_from_battery_error = True
                            
                            # Move back to active
                            del self.pending_resumes[port]
                            self.active_devices[port] = task
                            
                            # Restart processing thread with existing task
                            self.start_device_thread(port, task)
                            
                        elif port not in self.active_devices:
                            # TRULY NEW DEVICE
                            
                            # Check if this port has an active thread already
                            if self.is_port_busy(port):
                                continue
                            
                            # FIX: Double check if we already have an active task for this port (race condition)
                            if port in self.active_devices:
                                continue
                                
                            self.device_counter += 1
                            usb_loc = self._get_usb_location(port)
                            
                            print(f"{Colors.OKBLUE}[{port}] New device detected! (#{self.device_counter}, {usb_loc}){Colors.ENDC}")
                            task = DeviceTask(port, device_number=self.device_counter, usb_location=usb_loc)
                            self.active_devices[port] = task
                            self.start_device_thread(port, task)
                            
                    # 3. Update status of pending resumes (waiting for replug)
                    for port, task in self.pending_resumes.items():
                        if port not in current_ports:
                            task.status = STATUS_WAITING_RETRY
                            task.message = "Waiting for device replug..."
                            
            except Exception as e:
                print(f"Scan error: {e}")
                
            time.sleep(1.0)

#
# --- WEB DASHBOARD ---

app = Flask(__name__, template_folder="templates")
manager: Optional[AutoProductionManager] = None

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/api/state')
def api_state():
    if manager:
        return jsonify(manager.get_state())
    return jsonify({"devices": [], "recent_completed": [], "stats": {"total_programmed": 0, "total_failed": 0}})

@app.route('/api/retry', methods=['POST'])
def api_retry():
    if manager:
        data = request.get_json()
        port = data.get('port')
        if port:
            success = manager.request_retry(port)
            return jsonify({"success": success})
    return jsonify({"success": False})

@app.route('/api/action', methods=['POST'])
def api_action():
    if manager:
        data = request.get_json()
        port = data.get('port')
        action = data.get('action')
        if port and action:
            success = manager.request_manual_action(port, action)
            return jsonify({"success": success})
    return jsonify({"success": False})

@app.route('/api/logs/<filename>')
def api_get_log(filename):
    """Get contents of a specific log file."""
    # Sanitize filename to prevent path traversal
    if not filename.startswith('session_log_') or not filename.endswith('.csv'):
        return jsonify({"error": "Invalid log file"}), 400
    
    try:
        log_path = Path(filename)
        if not log_path.exists():
            return jsonify({"error": "Log not found"}), 404
        
        rows = []
        with open(log_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        
        return jsonify({
            "filename": filename,
            "rows": rows,
            "count": len(rows)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    """Authenticate with username/password and get API key."""
    if not manager:
        return jsonify({"success": False, "error": "Manager not initialized"}), 500
    
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"}), 400
    
    result = manager.authenticate(username, password)
    return jsonify(result)

@app.route('/api/skip_auth', methods=['POST'])
def api_skip_auth():
    """Skip authentication and run in offline mode."""
    if manager:
        manager.register_backend = False
        manager.auth_status = "offline"
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/lot_number', methods=['POST'])
def api_set_lot_number():
    """Set the lot number for device creation."""
    if not manager:
        return jsonify({"success": False, "error": "Manager not initialized"}), 500
    
    data = request.get_json()
    lot_number = data.get('lot_number', '').strip()
    
    success, message = manager.set_lot_number(lot_number)
    return jsonify({"success": success, "message": message, "lot_number": lot_number if success else None})

@app.route('/api/serial_number', methods=['POST'])
def api_submit_serial():
    """Submit serial number for a device awaiting it."""
    if not manager:
        return jsonify({"success": False, "error": "Manager not initialized"}), 500
    
    data = request.get_json()
    port = data.get('port', '').strip()
    serial_number = data.get('serial_number', '').strip()
    
    if not port:
        return jsonify({"success": False, "error": "Port required"}), 400
    
    success, message = manager.submit_serial_number(port, serial_number)
    return jsonify({"success": success, "message": message})

def run_flask(port: int):
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

def main():
    global manager
    
    parser = argparse.ArgumentParser(description="AutoTQ Automated Production Tool")
    parser.add_argument("--no-flash", action="store_true", help="Skip firmware flashing")
    parser.add_argument("--slow", action="store_true", help="Disable production mode")
    parser.add_argument("--no-backend", action="store_true", help="Disable backend registration")
    parser.add_argument("--audio-dir", default="audio", help="Audio directory")
    parser.add_argument("--firmware-dir", default="firmware", help="Firmware directory")
    parser.add_argument("--port", type=int, default=9090, help="Web server port")
    
    args = parser.parse_args()
    
    manager = AutoProductionManager(
        audio_dir=args.audio_dir,
        firmware_dir=args.firmware_dir,
        flash_firmware=not args.no_flash,
        production_mode=not args.slow,
        register_backend=not args.no_backend
    )
    
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, args=(args.port,), daemon=True)
    flask_thread.start()
    
    # Auto-open dashboard in browser
    def open_browser():
        time.sleep(2.0) # Wait for Flask to fully start
        url = f'http://localhost:{args.port}'
        print(f"{Colors.OKGREEN}🌐 Opening dashboard: {url}{Colors.ENDC}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"{Colors.WARNING}⚠️ Could not open browser automatically: {e}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}   Please open manually: {url}{Colors.ENDC}")
    
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    try:
        manager.scan_loop()
    except KeyboardInterrupt:
        print("\nStopping...")
        manager.running = False
        sys.exit(0)

if __name__ == "__main__":
    main()
