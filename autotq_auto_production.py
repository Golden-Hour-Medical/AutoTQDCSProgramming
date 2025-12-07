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
    from flask import Flask, render_template_string, jsonify, request
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
        
        # Detailed Step Status
        self.step_firmware = "pending" # pending, skipped, flashed, failed
        self.step_backend = "pending"  # pending, registered, failed
        self.step_audio = "pending"    # pending, skipped, transferred, failed

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
                "audio": self.step_audio
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
        self.lock = threading.Lock()
        self.running = True
        self.stats = {"total_programmed": 0, "total_failed": 0}
        
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
                writer.writerow(['Timestamp', 'Port', 'MAC Address', 'PCB ID', 'Firmware', 'Status', 'Step:Firmware', 'Step:Backend', 'Step:Audio', 'Duration (s)', 'Error'])
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
                    task.firmware_version or 'Unknown',
                    task.status,
                    task.step_firmware,
                    task.step_backend,
                    task.step_audio,
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
                    winsound.Beep(300, 800) # Low pitch, long
            except Exception:
                pass

    def _get_usb_location(self, port: str) -> str:
        """Try to extract USB hub/port location from port info."""
        try:
            for p in serial.tools.list_ports.comports():
                if p.device == port:
                    # Try to get location from various attributes
                    loc = getattr(p, 'location', None)
                    if loc:
                        return f"USB:{loc}"
                    
                    # Try hwid which often contains bus-port info
                    hwid = getattr(p, 'hwid', '') or ''
                    # Look for patterns like "USB VID:PID=xxxx:xxxx LOCATION=1-2.3"
                    match = re.search(r'LOCATION=([^\s]+)', hwid)
                    if match:
                        return f"USB:{match.group(1)}"
                    
                    # Try to extract from description
                    desc = getattr(p, 'description', '') or ''
                    if 'USB' in desc:
                        return desc[:30] # Truncate if too long
                    
                    return "USB"
        except Exception:
            pass
        return "Unknown"

    def _init_backend(self):
        """Initialize backend connection and check authentication."""
        try:
            self.client = AutoTQClient()
            
            # Check if authentication is valid
            if self.client.is_authenticated():
                user = self.client.get_user_profile()
                self.auth_status = "authenticated"
                self.auth_user = user.get('username') if user else None
                print(f"{Colors.OKGREEN}✅ Backend authenticated as {self.auth_user}{Colors.ENDC}")
                
                # Initialize setup tool for firmware downloads
                self.setup_tool = AutoTQSetup(output_dir=str(Path.cwd()))
                
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
            self.client = AutoTQClient()
            if self.client.is_authenticated():
                user = self.client.get_user_profile()
                self.auth_status = "authenticated"
                self.auth_user = user.get('username') if user else username
                self.auth_error = None
                self.register_backend = True
                
                # Initialize setup tool
                self.setup_tool = AutoTQSetup(output_dir=str(Path.cwd()))
                
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
                    if not any(t.name == f"thread-{port}" and t.is_alive() for t in threading.enumerate()):
                        # Thread is dead, we can restart
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
                        t.start()
                        return True
                    else:
                        print(f"{Colors.WARNING}[{port}] Cannot start manual action: Device busy{Colors.ENDC}")
                        return False
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
            if do_firmware and not task.firmware_flashed and not task.resumed_from_battery_error:
                self.log_status(port, STATUS_CONNECTING, "Checking existing firmware...", progress=2)
                
                # Quick connect to check version
                pre_check_prog = AutoTQDeviceProgrammer(port=port, audio_dir=str(self.audio_dir), stabilize_ms=2000)
                if pre_check_prog.connect():
                    # Use new consolidated info getter
                    info = self.get_device_info(pre_check_prog)
                    current_fw = info.get("fw_version")
                    pre_check_prog.disconnect()
                    
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
            
            # FORCE OVERRIDE: If manual action was firmware, don't skip even if versions match
            if task.force_action == 'flash_firmware':
                skip_flash = False
                task.firmware_flashed = False # Also reset this since pre-check might have set it
                task.step_firmware = "pending"

            # --- PHASE 1: FIRMWARE ---
            # Only flash if enabled AND NOT skipped AND NOT already flashed
            if do_firmware and not task.firmware_flashed and not skip_flash:
                self.log_status(port, STATUS_FLASHING, "Erasing flash...", progress=5)
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
                time.sleep(1.0)
                self.wait_for_port(port, timeout=15.0)
            elif task.resumed_from_battery_error:
                self.log_status(port, STATUS_CONNECTING, "Resuming after battery fix...", progress=55)

            # --- PHASE 2: CONNECTING ---
            self.log_status(port, STATUS_CONNECTING, "Connecting to device...", progress=60)
            dev_prog = AutoTQDeviceProgrammer(port=port, audio_dir=str(self.audio_dir), stabilize_ms=2000)
            
            connected = False
            for i in range(5):
                try:
                    if dev_prog.connect():
                        connected = True
                        break
                except Exception:
                    pass
                if i < 4:
                    self.log_status(port, STATUS_CONNECTING, f"Retry {i+1}...", progress=60 + i*2)
                    time.sleep(1.5 + (i * 0.5))
            
            if not connected:
                raise RuntimeError("Could not connect to serial port after 5 attempts")
                
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
                            try:
                                verify_pcb = self.client.session.get(f"{self.client.base_url}/pcbs/{pcb_id}", timeout=5)
                                if verify_pcb.status_code == 200:
                                    task.pcb_id = pcb_id
                                    task.step_backend = "registered_new" if is_new else "registered_existing"
                                else:
                                    self.log_status(port, STATUS_FAILED, f"Backend verify failed: {verify_pcb.status_code}")
                                    task.step_backend = "failed"
                            except Exception:
                                self.log_status(port, STATUS_FAILED, "Backend verify timeout")
                                task.step_backend = "failed"
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

                # Success!
                task.end_time = time.time()
                duration = task.end_time - task.start_time
                self.log_status(port, STATUS_COMPLETED, f"Done in {duration:.1f}s", progress=100)
                
                # Actions on completion
                self._play_sound(success=True)
                self._log_to_csv(task)
                
                with self.lock:
                    self.stats["total_programmed"] += 1
                    self.completion_times.append(duration)
                    # Remove from pending if it was there (cleanup)
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
                            print(f"{Colors.OKCYAN}[{port}] Device replugged - Resuming transfer...{Colors.ENDC}")
                            task = self.pending_resumes[port]
                            task.status = STATUS_CONNECTING
                            task.needs_user_action = False # Cleared automatically on replug
                            task.resumed_from_battery_error = True
                            
                            # Move back to active
                            del self.pending_resumes[port]
                            self.active_devices[port] = task
                            
                            # Restart processing thread with existing task
                            t = threading.Thread(target=self.process_device, args=(port, task), daemon=True, name=f"thread-{port}")
                            t.start()
                            
                        elif port not in self.active_devices:
                            # TRULY NEW DEVICE
                            
                            # Check if this port recently completed a task?
                            # If so, ignore unless explicitly removed?
                            # Actually, rely on 'active_devices' check above.
                            # If it's not in active_devices, it's either brand new or was removed.
                            
                            # FIX: Double check if we already have an active task for this port (race condition)
                            if port in self.active_devices:
                                continue
                                
                            self.device_counter += 1
                            usb_loc = self._get_usb_location(port)
                            
                            print(f"{Colors.OKBLUE}[{port}] New device detected! (#{self.device_counter}, {usb_loc}){Colors.ENDC}")
                            task = DeviceTask(port, device_number=self.device_counter, usb_location=usb_loc)
                            self.active_devices[port] = task
                            t = threading.Thread(target=self.process_device, args=(port, task), daemon=True, name=f"thread-{port}")
                            t.start()
                            
                    # 3. Update status of pending resumes (waiting for replug)
                    for port, task in self.pending_resumes.items():
                        if port not in current_ports:
                            task.status = STATUS_WAITING_RETRY
                            task.message = "Waiting for device replug..."
                            
            except Exception as e:
                print(f"Scan error: {e}")
                
            time.sleep(1.0)

# --- WEB DASHBOARD ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoTQ Production Station</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-card: #21262d;
            --border: #30363d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --accent-blue: #58a6ff;
            --accent-green: #3fb950;
            --accent-orange: #d29922;
            --accent-red: #f85149;
            --accent-purple: #a371f7;
            --badge-gray: #30363d;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 24px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
        }
        h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .stats {
            display: flex;
            gap: 24px;
        }
        .stat {
            text-align: center;
            padding: 12px 20px;
            background: var(--bg-secondary);
            border-radius: 12px;
            border: 1px solid var(--border);
        }
        .stat-value {
            font-size: 28px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }
        .stat-label { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
        .stat.success .stat-value { color: var(--accent-green); }
        .stat.failed .stat-value { color: var(--accent-red); }
        .stat.firmware .stat-value { color: var(--accent-purple); font-size: 18px; }
        
        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 16px;
        }
        .devices-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
            gap: 16px;
            margin-bottom: 40px;
        }
        .device-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            transition: all 0.2s ease;
            position: relative;
        }
        .device-card:hover {
            border-color: var(--accent-blue);
            transform: translateY(-2px);
        }
        .device-card.needs-action {
            border-color: var(--accent-red);
            animation: pulse-border 2s infinite;
        }
        @keyframes pulse-border {
            0%, 100% { box-shadow: 0 0 0 0 rgba(248, 81, 73, 0.4); }
            50% { box-shadow: 0 0 0 8px rgba(248, 81, 73, 0); }
        }
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .device-port {
            font-family: 'JetBrains Mono', monospace;
            font-size: 18px;
            font-weight: 600;
        }
        .device-status {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .device-message {
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 16px;
            min-height: 20px;
        }
        .progress-container {
            background: var(--bg-primary);
            border-radius: 8px;
            height: 8px;
            overflow: hidden;
            margin-bottom: 16px;
        }
        .progress-bar {
            height: 100%;
            border-radius: 8px;
            transition: width 0.3s ease;
        }
        .device-meta {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            font-size: 13px;
        }
        .meta-item {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .meta-label { color: var(--text-secondary); font-size: 11px; text-transform: uppercase; }
        .meta-value { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
        
        .action-banner {
            background: linear-gradient(135deg, #f8514922, #f8514911);
            border: 1px solid var(--accent-red);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            text-align: center;
        }
        .action-banner-icon {
            font-size: 32px;
            margin-bottom: 8px;
        }
        .action-banner-title {
            font-weight: 600;
            color: var(--accent-red);
            margin-bottom: 4px;
        }
        .action-banner-desc {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 12px;
        }
        
        .control-buttons {
            display: flex;
            gap: 8px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }
        
        .btn {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            flex: 1;
        }
        .btn:hover {
            background: var(--border);
        }
        
        .btn-primary {
            background: var(--accent-blue);
            border-color: var(--accent-blue);
        }
        .btn-primary:hover {
            background: #4a9be8;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            background: var(--bg-secondary);
            border-radius: 16px;
            border: 2px dashed var(--border);
        }
        .empty-state-icon { font-size: 48px; margin-bottom: 16px; }
        .empty-state-title { font-size: 20px; font-weight: 600; margin-bottom: 8px; }
        .empty-state-desc { color: var(--text-secondary); }
        
        .pulse { animation: pulse 2s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Status Badges Row */
        .status-steps {
            display: flex;
            gap: 8px;
            margin-top: 12px;
            margin-bottom: 12px;
        }
        .step-badge {
            flex: 1;
            font-size: 11px;
            text-transform: uppercase;
            padding: 4px 8px;
            border-radius: 6px;
            text-align: center;
            font-weight: 600;
            background: var(--badge-gray);
            color: var(--text-secondary);
            border: 1px solid transparent;
        }
        .step-badge.pending { opacity: 0.5; }
        .step-badge.skipped { background: rgba(52, 152, 219, 0.1); color: #3498db; border-color: rgba(52, 152, 219, 0.2); }
        .step-badge.flashed, .step-badge.transferred, .step-badge.registered { 
            background: rgba(63, 185, 80, 0.1); color: #3fb950; border-color: rgba(63, 185, 80, 0.2); 
        }
        .step-badge.failed { background: rgba(248, 81, 73, 0.1); color: #f85149; border-color: rgba(248, 81, 73, 0.2); }
        
        /* Session Stats Bar */
        .session-bar {
            display: flex;
            gap: 24px;
            margin-bottom: 24px;
            padding: 16px 20px;
            background: var(--bg-secondary);
            border-radius: 12px;
            border: 1px solid var(--border);
            flex-wrap: wrap;
        }
        .session-stat {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .session-stat-icon { font-size: 18px; }
        .session-stat-value { 
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            color: var(--accent-blue);
        }
        .session-stat-label { font-size: 12px; color: var(--text-secondary); }
        
        /* Device Number Badge */
        .device-number {
            background: var(--accent-purple);
            color: white;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
            margin-right: 8px;
            font-family: 'JetBrains Mono', monospace;
        }
        
        .usb-location {
            font-size: 11px;
            color: var(--text-secondary);
            margin-top: 4px;
        }
        
        /* Logs Panel */
        .logs-panel {
            margin-top: 40px;
            padding: 20px;
            background: var(--bg-secondary);
            border-radius: 16px;
            border: 1px solid var(--border);
        }
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .logs-tabs {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            overflow-x: auto;
            padding-bottom: 8px;
        }
        .log-tab {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 11px;
            cursor: pointer;
            white-space: nowrap;
        }
        .log-tab.active {
            background: var(--accent-blue);
            color: white;
            border-color: var(--accent-blue);
        }
        .log-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        .log-table th, .log-table td {
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        .log-table th {
            background: var(--bg-card);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 10px;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
        }
        .log-table td {
            font-family: 'JetBrains Mono', monospace;
        }
        .log-table tr:hover td {
            background: var(--bg-card);
        }
        .log-status-success { color: var(--accent-green); }
        .log-status-failed { color: var(--accent-red); }
        
        .toggle-logs-btn {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
        }
        .toggle-logs-btn:hover {
            background: var(--border);
        }
        
        /* Login Modal */
        .login-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: var(--bg-primary);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            text-align: center;
        }
        .login-logo { font-size: 48px; margin-bottom: 16px; }
        .login-title { font-size: 24px; font-weight: 700; margin-bottom: 8px; }
        .login-subtitle { color: var(--text-secondary); margin-bottom: 32px; }
        .login-form { display: flex; flex-direction: column; gap: 16px; }
        .login-input {
            background: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 16px;
            font-size: 14px;
            color: var(--text-primary);
            outline: none;
            transition: border-color 0.2s;
        }
        .login-input:focus {
            border-color: var(--accent-blue);
        }
        .login-input::placeholder { color: var(--text-secondary); }
        .login-btn {
            background: var(--accent-blue);
            border: none;
            border-radius: 8px;
            padding: 14px;
            font-size: 14px;
            font-weight: 600;
            color: white;
            cursor: pointer;
            transition: background 0.2s;
        }
        .login-btn:hover { background: #4a9be8; }
        .login-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .login-error {
            background: rgba(248, 81, 73, 0.1);
            border: 1px solid var(--accent-red);
            border-radius: 8px;
            padding: 12px;
            color: var(--accent-red);
            font-size: 13px;
            display: none;
        }
        .login-error.show { display: block; }
        .login-offline {
            background: rgba(210, 153, 34, 0.1);
            border: 1px solid var(--accent-orange);
            color: var(--accent-orange);
        }
        .skip-btn {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            margin-top: 16px;
        }
        .skip-btn:hover { 
            background: var(--bg-secondary);
            color: var(--text-primary);
        }
        .auth-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }
        .auth-badge.authenticated { 
            background: rgba(63, 185, 80, 0.1); 
            color: var(--accent-green);
        }
        .auth-badge.offline { 
            background: rgba(210, 153, 34, 0.1); 
            color: var(--accent-orange);
        }

    </style>
</head>
<body>
    <!-- Login Overlay (shown when auth fails) -->
    <div class="login-overlay" id="login-overlay" style="display: none;">
        <div class="login-card">
            <div class="login-logo">🔐</div>
            <div class="login-title">AutoTQ Production</div>
            <div class="login-subtitle">Sign in to enable backend registration</div>
            
            <div class="login-error" id="login-error"></div>
            
            <form class="login-form" id="login-form" onsubmit="handleLogin(event)">
                <input type="text" class="login-input" id="login-username" placeholder="Username" required>
                <input type="password" class="login-input" id="login-password" placeholder="Password" required>
                <button type="submit" class="login-btn" id="login-btn">Sign In</button>
            </form>
            
            <button class="login-btn skip-btn" onclick="skipLogin()">
                Continue Without Backend
            </button>
        </div>
    </div>

    <div class="container" id="main-container">
        <header>
            <div>
                <h1>⚡ AutoTQ Production Station</h1>
                <span class="auth-badge" id="auth-badge" style="display: none;"></span>
            </div>
            <div class="stats">
                <div class="stat firmware">
                    <div class="stat-value" id="firmware-version">--</div>
                    <div class="stat-label">Firmware</div>
                </div>
                <div class="stat success">
                    <div class="stat-value" id="total-success">0</div>
                    <div class="stat-label">Programmed</div>
                </div>
                <div class="stat failed">
                    <div class="stat-value" id="total-failed">0</div>
                    <div class="stat-label">Failed</div>
                </div>
            </div>
        </header>
        
        <div class="session-bar" id="session-stats">
            <div class="session-stat">
                <span class="session-stat-icon">⏱️</span>
                <span class="session-stat-value" id="session-duration">0:00:00</span>
                <span class="session-stat-label">Session</span>
            </div>
            <div class="session-stat">
                <span class="session-stat-icon">📊</span>
                <span class="session-stat-value" id="devices-per-hour">0</span>
                <span class="session-stat-label">Devices/Hour</span>
            </div>
            <div class="session-stat">
                <span class="session-stat-icon">⚡</span>
                <span class="session-stat-value" id="avg-time">0s</span>
                <span class="session-stat-label">Avg Time</span>
            </div>
            <div class="session-stat">
                <span class="session-stat-icon">📋</span>
                <span class="session-stat-value" id="total-devices">0</span>
                <span class="session-stat-label">Total Seen</span>
            </div>
        </div>
        
        <div class="section-title">Active Devices</div>
        <div class="devices-grid" id="active-devices">
            <div class="empty-state">
                <div class="empty-state-icon pulse">🔌</div>
                <div class="empty-state-title">Waiting for devices</div>
                <div class="empty-state-desc">Plug in an AutoTQ device via USB to begin</div>
            </div>
        </div>
        
        <div class="section-title">Recent Completions</div>
        <div class="devices-grid" id="recent-devices"></div>
        
        <div class="logs-panel" id="logs-panel" style="display: none;">
            <div class="logs-header">
                <div class="section-title" style="margin: 0;">📝 Session Logs</div>
                <button class="toggle-logs-btn" onclick="toggleLogs()">Hide Logs</button>
            </div>
            <div class="logs-tabs" id="logs-tabs"></div>
            <div id="logs-content">
                <table class="log-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Port</th>
                            <th>MAC</th>
                            <th>PCB</th>
                            <th>FW</th>
                            <th>Status</th>
                            <th>Duration</th>
                        </tr>
                    </thead>
                    <tbody id="logs-tbody"></tbody>
                </table>
            </div>
        </div>
        <div style="text-align: center; margin-top: 16px;">
            <button class="toggle-logs-btn" id="show-logs-btn" onclick="toggleLogs()">📝 Show Session Logs</button>
        </div>
    </div>
    
    <script>
        let authChecked = false;
        let loginSkipped = false;
        
        async function handleLogin(event) {
            event.preventDefault();
            const username = document.getElementById('login-username').value;
            const password = document.getElementById('login-password').value;
            const btn = document.getElementById('login-btn');
            const errorDiv = document.getElementById('login-error');
            
            btn.disabled = true;
            btn.textContent = 'Signing in...';
            errorDiv.classList.remove('show');
            
            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                
                const result = await response.json();
                
                if (result.success) {
                    document.getElementById('login-overlay').style.display = 'none';
                    authChecked = true;
                    // Reload page to refresh state
                    location.reload();
                } else {
                    errorDiv.textContent = result.error || 'Login failed';
                    errorDiv.classList.add('show');
                }
            } catch (error) {
                errorDiv.textContent = 'Connection error. Check your network.';
                errorDiv.classList.add('show');
            }
            
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }
        
        function skipLogin() {
            loginSkipped = true;
            document.getElementById('login-overlay').style.display = 'none';
            // Send skip request to backend to unblock loop
            fetch('/api/skip_auth', { method: 'POST' });
        }
        
        function showLoginOverlay(authData) {
            if (loginSkipped) return;
            
            const overlay = document.getElementById('login-overlay');
            const errorDiv = document.getElementById('login-error');
            
            if (authData.status === 'offline') {
                errorDiv.textContent = '⚠️ Backend server unreachable. Working in offline mode.';
                errorDiv.classList.add('show', 'login-offline');
            } else if (authData.status === 'failed') {
                errorDiv.textContent = authData.error || 'Authentication required';
                errorDiv.classList.add('show');
            }
            
            overlay.style.display = 'flex';
        }
        
        async function sendAction(port, action) {
            try {
                await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({port: port, action: action})
                });
            } catch (error) {
                console.error('Action failed:', error);
            }
        }
        
        function getStepBadge(type, status) {
            let label = status;
            let className = status;
            
            // Map status to readable labels
            if (status === 'pending') label = 'Pending';
            else if (status === 'skipped') label = 'Skipped (Present)';
            else if (status === 'flashed') label = 'Flashed';
            else if (status === 'transferred') label = 'Transferred';
            else if (status === 'registered_new') { label = 'Registered (New)'; className = 'registered'; }
            else if (status === 'registered_existing') { label = 'Registered (Existing)'; className = 'skipped'; }
            else if (status === 'registered') label = 'Registered';
            else if (status === 'failed') label = 'Failed';

            if (type === 'firmware' && status === 'pending') label = 'Firmware';
            if (type === 'backend' && status === 'pending') label = 'Backend';
            if (type === 'audio' && status === 'pending') label = 'Audio';

            return `<div class="step-badge ${className}">${label}</div>`;
        }

        function createDeviceCard(device, isActive) {
            const statusStyle = `background: ${device.status_color}22; color: ${device.status_color}; border: 1px solid ${device.status_color}44`;
            const progressColor = device.status === 'COMPLETED' ? 'var(--accent-green)' : 
                                  device.status === 'FAILED' ? 'var(--accent-red)' : device.status_color;
            
            const needsActionClass = device.needs_user_action ? 'needs-action' : '';
            
            let actionBanner = '';
            if (device.needs_user_action) {
                actionBanner = `
                    <div class="action-banner">
                        <div class="action-banner-icon">🔋</div>
                        <div class="action-banner-title">Action Required</div>
                        <div class="action-banner-desc">${device.user_action_message}</div>
                    </div>
                `;
            }
            
            let controls = '';
            const canControl = device.is_complete || device.status === 'DETECTED' || device.status === 'FAILED';
            if (isActive && canControl) {
                controls = `
                    <div class="control-buttons">
                        <button class="btn" onclick="sendAction('${device.port}', 'flash_firmware')">Flash FW</button>
                        <button class="btn" onclick="sendAction('${device.port}', 'flash_audio')">Flash Audio</button>
                    </div>
                `;
            }
            
            // Step Badges
            const steps = device.steps || { firmware: 'pending', backend: 'pending', audio: 'pending' };
            const stepBadges = `
                <div class="status-steps">
                    ${getStepBadge('firmware', steps.firmware)}
                    ${getStepBadge('backend', steps.backend)}
                    ${getStepBadge('audio', steps.audio)}
                </div>
            `;

            return `
                <div class="device-card ${needsActionClass}">
                    <div class="device-header">
                        <span class="device-port">
                            ${device.device_number ? `<span class="device-number">#${device.device_number}</span>` : ''}
                            ${device.port}
                        </span>
                        <span class="device-status" style="${statusStyle}">
                            ${device.status_icon} ${device.status_label}
                        </span>
                    </div>
                    ${device.usb_location ? `<div class="usb-location">📍 ${device.usb_location}</div>` : ''}
                    ${actionBanner}
                    
                    ${stepBadges}

                    <div class="device-message">${device.message}</div>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: ${device.progress}%; background: ${progressColor}"></div>
                    </div>
                    <div class="device-meta">
                        <div class="meta-item">
                            <span class="meta-label">MAC Address</span>
                            <span class="meta-value">${device.mac_address || '—'}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">PCB ID</span>
                            <span class="meta-value">${device.pcb_id ? '#' + device.pcb_id : '—'}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Firmware</span>
                            <span class="meta-value">${device.firmware_version || '—'}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Battery</span>
                            <span class="meta-value">${device.battery_level !== null ? device.battery_level + '%' : '—'}</span>
                        </div>
                    </div>
                    ${controls}
                </div>
            `;
        }
        
        let currentLogFile = null;
        let logsVisible = false;
        let logFiles = [];
        
        function formatDuration(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }
        
        function toggleLogs() {
            logsVisible = !logsVisible;
            document.getElementById('logs-panel').style.display = logsVisible ? 'block' : 'none';
            document.getElementById('show-logs-btn').style.display = logsVisible ? 'none' : 'inline-block';
            if (logsVisible && currentLogFile) {
                loadLogFile(currentLogFile);
            }
        }
        
        async function loadLogFile(filename) {
            try {
                const response = await fetch(`/api/logs/${filename}`);
                const data = await response.json();
                
                if (data.error) {
                    console.error('Log error:', data.error);
                    return;
                }
                
                currentLogFile = filename;
                
                // Update tabs
                const tabsContainer = document.getElementById('logs-tabs');
                tabsContainer.innerHTML = logFiles.map(f => 
                    `<button class="log-tab ${f === filename ? 'active' : ''}" onclick="loadLogFile('${f}')">${f.replace('session_log_', '').replace('.csv', '')}</button>`
                ).join('');
                
                // Update table
                const tbody = document.getElementById('logs-tbody');
                tbody.innerHTML = data.rows.reverse().map(row => `
                    <tr>
                        <td>${row.Timestamp || ''}</td>
                        <td>${row.Port || ''}</td>
                        <td>${row['MAC Address'] || ''}</td>
                        <td>${row['PCB ID'] || ''}</td>
                        <td>${row.Firmware || ''}</td>
                        <td class="${row.Status === 'COMPLETED' ? 'log-status-success' : 'log-status-failed'}">${row.Status || ''}</td>
                        <td>${row['Duration (s)'] || ''}s</td>
                    </tr>
                `).join('');
            } catch (error) {
                console.error('Failed to load log:', error);
            }
        }
        
        async function updateDashboard() {
            try {
                const response = await fetch('/api/state');
                const data = await response.json();
                
                // Check auth status on first load
                if (!authChecked && !loginSkipped && data.auth) {
                    if (data.auth.status === 'failed' || data.auth.status === 'offline') {
                        showLoginOverlay(data.auth);
                    } else if (data.auth.status === 'authenticated') {
                        authChecked = true;
                    }
                }
                
                // Update auth badge
                const authBadge = document.getElementById('auth-badge');
                if (data.auth) {
                    if (data.auth.status === 'authenticated') {
                        authBadge.className = 'auth-badge authenticated';
                        authBadge.innerHTML = `✓ ${data.auth.user || 'Connected'}`;
                        authBadge.style.display = 'inline-flex';
                    } else if (data.auth.status === 'offline' || loginSkipped) {
                        authBadge.className = 'auth-badge offline';
                        authBadge.innerHTML = '⚠ Offline Mode';
                        authBadge.style.display = 'inline-flex';
                    }
                }
                
                document.getElementById('firmware-version').textContent = data.firmware_version || '--';
                document.getElementById('total-success').textContent = data.stats.total_programmed;
                document.getElementById('total-failed').textContent = data.stats.total_failed;
                
                // Update session stats
                if (data.session) {
                    document.getElementById('session-duration').textContent = formatDuration(data.session.duration_seconds);
                    document.getElementById('devices-per-hour').textContent = data.session.devices_per_hour || 0;
                    document.getElementById('avg-time').textContent = (data.session.avg_time_seconds || 0) + 's';
                    document.getElementById('total-devices').textContent = data.session.total_devices || 0;
                    
                    // Set current log file
                    if (!currentLogFile && data.session.current_log_file) {
                        currentLogFile = data.session.current_log_file.split('/').pop().split('\\\\').pop();
                    }
                }
                
                // Update log files list
                if (data.log_files) {
                    logFiles = data.log_files;
                }
                
                const activeContainer = document.getElementById('active-devices');
                if (data.devices.length > 0) {
                    activeContainer.innerHTML = data.devices.map(d => createDeviceCard(d, true)).join('');
                } else {
                    activeContainer.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon pulse">🔌</div>
                            <div class="empty-state-title">Waiting for devices</div>
                            <div class="empty-state-desc">Plug in an AutoTQ device via USB to begin</div>
                        </div>
                    `;
                }
                
                const recentContainer = document.getElementById('recent-devices');
                if (data.recent_completed.length > 0) {
                    recentContainer.innerHTML = data.recent_completed.reverse().map(d => createDeviceCard(d, false)).join('');
                } else {
                    recentContainer.innerHTML = '<div style="color: var(--text-secondary); padding: 20px;">No completed devices yet</div>';
                }
            } catch (error) {
                console.error('Failed to update dashboard:', error);
            }
        }
        
        setInterval(updateDashboard, 500);
        updateDashboard();
    </script>
</body>
</html>
"""

app = Flask(__name__)
manager: Optional[AutoProductionManager] = None

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

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
