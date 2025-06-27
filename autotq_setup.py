#!/usr/bin/env python3
"""
AutoTQ Setup & Update Tool
Downloads latest firmware and audio files from the AutoTQ server
"""
import os
import sys
import json
import argparse
import time
import shutil
import hashlib
import signal
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Third-party imports
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("⚠️  Warning: tqdm not installed. Progress bars will be disabled.")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️  Warning: psutil not installed. Process checking will be limited.")

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    print("⚠️  Warning: cryptography not installed. Credential storage will be disabled.")

# Import our existing client
from autotq_client import AutoTQClient

class AutoTQSetup:
    def __init__(self, base_url: str = None, verify_ssl: bool = True, output_dir: str = None):
        """
        Initialize the AutoTQ setup tool
        
        Args:
            base_url: Server URL (default: https://seahorse-app-ax33h.ondigitalocean.app)
            verify_ssl: Whether to verify SSL certificates (True for production)
            output_dir: Directory to download files to (default: current directory)
        """
        self.client = AutoTQClient(
            base_url=base_url or "https://seahorse-app-ax33h.ondigitalocean.app", 
            verify_ssl=verify_ssl
        )
        self.output_dir = Path(output_dir or ".")
        self.firmware_dir = self.output_dir / "firmware"
        self.audio_dir = self.output_dir / "audio"
        self.manifest_file = self.output_dir / "autotq_manifest.json"
        self.credentials_file = self.output_dir / ".autotq_credentials"
        self.lock_file = self.output_dir / "autotq_setup.lock"
        
        # Platform detection
        self.current_platform = platform.system().lower()
        
        # Create directories
        self.firmware_dir.mkdir(exist_ok=True)
        self.audio_dir.mkdir(exist_ok=True)
        
        # Logging
        self.log_file = self.output_dir / "autotq_setup.log"
        
        # Platform-specific setup
        if self.current_platform == "windows":
            # On Windows, handle different signal types
            signal.signal(signal.SIGINT, self._signal_handler)
            try:
                signal.signal(signal.SIGBREAK, self._signal_handler)
            except AttributeError:
                pass  # SIGBREAK not available on all Windows versions
        else:
            # Unix-like systems
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Clean up on signal"""
        self.log("\nReceived interrupt signal, cleaning up...", "WARNING")
        self.release_lock()
        sys.exit(1)
    
    def check_system_requirements(self) -> bool:
        """Check system requirements and dependencies"""
        self.log(f"Checking system requirements on {platform.system()}...", "PROGRESS")
        
        # Check Python version
        if sys.version_info < (3, 8):
            self.log(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}", "ERROR")
            return False
        self.log(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} ({platform.architecture()[0]})", "SUCCESS")
        
        # Platform-specific information
        if self.current_platform == "windows":
            self.log(f"✓ Windows {platform.release()} detected", "SUCCESS")
        elif self.current_platform == "linux":
            try:
                import distro
                self.log(f"✓ Linux {distro.name()} {distro.version()} detected", "SUCCESS")
            except ImportError:
                self.log(f"✓ Linux {platform.release()} detected", "SUCCESS")
        elif self.current_platform == "darwin":
            self.log(f"✓ macOS {platform.mac_ver()[0]} detected", "SUCCESS")
        
        # Check disk space (require at least 500MB)
        try:
            free_space = shutil.disk_usage(self.output_dir).free
            required_space = 500 * 1024 * 1024  # 500MB
            if free_space < required_space:
                self.log(f"Insufficient disk space. Required: {required_space//1024//1024}MB, Available: {free_space//1024//1024}MB", "ERROR")
                return False
            self.log(f"✓ Disk space: {free_space//1024//1024}MB available", "SUCCESS")
        except Exception as e:
            self.log(f"Could not check disk space: {e}", "WARNING")
        
        # Check write permissions in output directory
        try:
            test_file = self.output_dir / ".autotq_write_test"
            test_file.write_text("test")
            test_file.unlink()
            self.log(f"✓ Write permissions: {self.output_dir.absolute()}", "SUCCESS")
        except Exception as e:
            self.log(f"No write permission in output directory: {e}", "ERROR")
            return False
        
        # Check required packages
        required_packages = {
            'requests': 'HTTP client library',
            'urllib3': 'HTTP library with connection pooling'
        }
        
        missing_packages = []
        for package, description in required_packages.items():
            try:
                __import__(package)
                self.log(f"✓ {package}: {description}", "SUCCESS")
            except ImportError:
                missing_packages.append(package)
                self.log(f"✗ {package}: {description} (MISSING)", "ERROR")
        
        if missing_packages:
            install_cmd = f"pip install {' '.join(missing_packages)}"
            self.log(f"Install missing packages: {install_cmd}", "ERROR")
            if self.current_platform == "windows":
                self.log("💡 On Windows, you may need to run as Administrator", "INFO")
            return False
        
        # Check optional packages
        optional_packages = {
            'tqdm': ('Progress bars', HAS_TQDM),
            'psutil': ('Process management', HAS_PSUTIL),
            'cryptography': ('Credential encryption', HAS_CRYPTO)
        }
        
        for package, (description, available) in optional_packages.items():
            if available:
                self.log(f"✓ {package}: {description}", "SUCCESS")
            else:
                self.log(f"⚠ {package}: {description} (Optional, but recommended)", "WARNING")
                if self.current_platform == "windows":
                    self.log(f"💡 Install with: pip install {package}", "INFO")
        
        self.log("System requirements check completed", "SUCCESS")
        return True
    
    def acquire_lock(self) -> bool:
        """Prevent multiple instances from running simultaneously"""
        if self.lock_file.exists():
            try:
                with open(self.lock_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Check if process is still running
                if self.is_process_running(pid):
                    self.log(f"Another setup process is already running (PID: {pid})", "ERROR")
                    self.log("If you're sure no other process is running, delete the lock file:", "INFO")
                    self.log(f"  rm {self.lock_file}", "INFO")
                    return False
                else:
                    self.log("Found stale lock file, removing...", "WARNING")
                    self.lock_file.unlink()
            except (ValueError, FileNotFoundError):
                self.log("Found invalid lock file, removing...", "WARNING")
                self.lock_file.unlink()
        
        # Create lock file with current PID
        try:
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
            self.log(f"Acquired lock (PID: {os.getpid()})", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Could not create lock file: {e}", "ERROR")
            return False
    
    def release_lock(self):
        """Release the lock file"""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
                self.log("Released lock", "SUCCESS")
        except Exception as e:
            self.log(f"Could not remove lock file: {e}", "WARNING")
    
    def is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running"""
        if HAS_PSUTIL:
            return psutil.pid_exists(pid)
        else:
            # Fallback method - platform specific
            try:
                if self.current_platform == "windows":
                    # On Windows, os.kill with signal 0 doesn't work the same way
                    # Use tasklist command as fallback
                    import subprocess
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    return str(pid) in result.stdout
                else:
                    # Unix-like systems
                    os.kill(pid, 0)
                    return True
            except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
                return False
    
    def _get_encryption_key(self, password: str) -> bytes:
        """Generate encryption key from password"""
        if not HAS_CRYPTO:
            return None
        
        # Use a salt stored in the credentials file or generate one
        salt_file = self.output_dir / ".autotq_salt"
        if salt_file.exists():
            with open(salt_file, 'rb') as f:
                salt = f.read()
        else:
            salt = os.urandom(16)
            with open(salt_file, 'wb') as f:
                f.write(salt)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def save_credentials(self, username: str, password: str) -> bool:
        """Securely save credentials for future use"""
        if not HAS_CRYPTO:
            self.log("Cryptography not available, cannot save credentials", "WARNING")
            return False
        
        try:
            # Create a master password from system info - handle Windows user detection
            try:
                if self.current_platform == "windows":
                    # On Windows, try multiple methods to get username
                    user = os.environ.get('USERNAME') or os.environ.get('USER') or 'default'
                else:
                    user = os.getlogin()
            except OSError:
                # Fallback if os.getlogin() fails (can happen in some environments)
                user = os.environ.get('USER') or os.environ.get('USERNAME') or 'default'
            
            system_info = f"{user}-{platform.node()}-autotq"
            key = self._get_encryption_key(system_info)
            
            fernet = Fernet(key)
            
            credentials = {
                'username': username,
                'password': password,
                'saved_at': datetime.now().isoformat(),
                'platform': self.current_platform
            }
            
            encrypted_data = fernet.encrypt(json.dumps(credentials).encode())
            
            with open(self.credentials_file, 'wb') as f:
                f.write(encrypted_data)
            
            # Set restrictive permissions (Unix-like systems only)
            if self.current_platform != "windows":
                try:
                    os.chmod(self.credentials_file, 0o600)
                except Exception as e:
                    self.log(f"Could not set file permissions: {e}", "WARNING")
            else:
                # On Windows, hide the file instead
                try:
                    import subprocess
                    subprocess.run(["attrib", "+H", str(self.credentials_file)], 
                                 capture_output=True, check=False)
                except Exception:
                    pass  # Not critical if this fails
            
            self.log("Credentials saved securely", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Could not save credentials: {e}", "WARNING")
            return False
    
    def load_credentials(self) -> Optional[tuple]:
        """Load saved credentials"""
        if not HAS_CRYPTO or not self.credentials_file.exists():
            return None
        
        try:
            # Get system info same way as save_credentials
            try:
                if self.current_platform == "windows":
                    user = os.environ.get('USERNAME') or os.environ.get('USER') or 'default'
                else:
                    user = os.getlogin()
            except OSError:
                user = os.environ.get('USER') or os.environ.get('USERNAME') or 'default'
            
            system_info = f"{user}-{platform.node()}-autotq"
            key = self._get_encryption_key(system_info)
            
            fernet = Fernet(key)
            
            with open(self.credentials_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = fernet.decrypt(encrypted_data)
            credentials = json.loads(decrypted_data.decode())
            
            return credentials['username'], credentials['password']
            
        except Exception as e:
            self.log(f"Could not load saved credentials: {e}", "WARNING")
            return None
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message to both console and file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {level}: {message}"
        
        # Print to console with emoji
        emoji_map = {
            "INFO": "ℹ️ ",
            "SUCCESS": "✅ ",
            "WARNING": "⚠️ ",
            "ERROR": "❌ ",
            "PROGRESS": "🔄 "
        }
        console_message = f"{emoji_map.get(level, '')} {message}"
        print(console_message)
        
        # Write to log file
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            print(f"⚠️  Warning: Could not write to log file: {e}")
    
    def load_manifest(self) -> Dict[str, Any]:
        """Load existing manifest file if it exists"""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"Could not load existing manifest: {e}", "WARNING")
        return {}
    
    def save_manifest(self, manifest_data: Dict[str, Any]):
        """Save manifest file with download information"""
        try:
            with open(self.manifest_file, "w") as f:
                json.dump(manifest_data, f, indent=2)
            self.log("Manifest file updated", "SUCCESS")
        except Exception as e:
            self.log(f"Could not save manifest: {e}", "ERROR")
    
    def authenticate(self, username: str = None, password: str = None) -> bool:
        """Authenticate with the server"""
        self.log("Starting authentication process", "INFO")
        
        # Check if already authenticated
        if self.client.is_authenticated():
            user_info = self.client.get_user_profile()
            if user_info:
                self.log(f"Already authenticated as {user_info.get('username')}", "SUCCESS")
                return True
        
        # Try to use provided credentials first
        if username and password:
            success = self.client.login(username, password)
            if success:
                self.log("Authentication successful", "SUCCESS")
                # Save credentials for future use
                self.save_credentials(username, password)
                return True
        
        # Try to load saved credentials
        saved_creds = self.load_credentials()
        if saved_creds:
            username, password = saved_creds
            self.log("Using saved credentials", "INFO")
            success = self.client.login(username, password)
            if success:
                self.log("Authentication successful with saved credentials", "SUCCESS")
                return True
            else:
                self.log("Saved credentials are invalid, removing them", "WARNING")
                try:
                    self.credentials_file.unlink()
                except:
                    pass
        
        # If all else fails, prompt for credentials
        if not username:
            success = self.client.login()  # This will prompt
            if success:
                # Try to save the credentials that were just entered
                # Note: We can't save them here because client.login() doesn't return the password
                self.log("Authentication successful", "SUCCESS")
                return True
        
        self.log("Authentication failed", "ERROR")
        return False
    
    def get_latest_firmware_version(self) -> Optional[Dict[str, Any]]:
        """Get the latest firmware version info"""
        try:
            self.log("Fetching firmware versions list", "PROGRESS")
            response = self.client.session.get(
                f"{self.client.base_url}/firmware/versions?limit=1&skip=0",
                timeout=30
            )
            
            if response.status_code == 200:
                versions = response.json()
                if versions:
                    latest = versions[0]
                    self.log(f"Latest firmware version: {latest['version_number']}", "SUCCESS")
                    return latest
                else:
                    self.log("No firmware versions found", "WARNING")
                    return None
            else:
                self.log(f"Failed to get firmware versions (Status: {response.status_code})", "ERROR")
                return None
                
        except Exception as e:
            self.log(f"Error getting firmware versions: {e}", "ERROR")
            return None
    
    def download_with_progress(self, url: str, file_path: Path, description: str = None) -> bool:
        """Download a file with progress bar"""
        try:
            # Ensure the parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # On Windows, check for long path issues
            if self.current_platform == "windows" and len(str(file_path.absolute())) > 260:
                self.log(f"Warning: Path length ({len(str(file_path.absolute()))}) may cause issues on Windows", "WARNING")
                self.log("Consider using a shorter output directory path", "INFO")
            
            response = self.client.session.get(url, stream=True, timeout=300)
            
            if response.status_code != 200:
                self.log(f"Download failed with status {response.status_code}", "ERROR")
                if response.status_code == 404:
                    self.log("File not found on server", "ERROR")
                elif response.status_code == 403:
                    self.log("Access denied - check authentication", "ERROR")
                return False
            
            total_size = int(response.headers.get('content-length', 0))
            desc = description or file_path.name
            
            # Create a temporary file first, then rename on success (atomic operation)
            temp_file = file_path.with_suffix(file_path.suffix + '.tmp')
            
            try:
                if HAS_TQDM and total_size > 0:
                    # Use tqdm progress bar
                    with open(temp_file, 'wb') as f, tqdm(
                        desc=desc,
                        total=total_size,
                        unit='B',
                        unit_scale=True,
                        unit_divisor=1024,
                        ncols=80
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
                else:
                    # Fallback without progress bar
                    downloaded = 0
                    last_logged = 0
                    with open(temp_file, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                
                                # Log progress for large files (every 5MB)
                                if total_size > 0 and downloaded - last_logged >= 5 * 1024 * 1024:
                                    progress = (downloaded / total_size) * 100
                                    self.log(f"Download progress: {progress:.1f}% ({downloaded:,}/{total_size:,} bytes)", "PROGRESS")
                                    last_logged = downloaded
                
                # Atomic rename - move temp file to final location
                if self.current_platform == "windows":
                    # On Windows, remove target file first if it exists
                    if file_path.exists():
                        file_path.unlink()
                temp_file.rename(file_path)
                
                file_size = file_path.stat().st_size
                self.log(f"Downloaded {file_path.name} ({file_size:,} bytes)", "SUCCESS")
                return True
                
            except Exception as e:
                # Clean up temp file on error
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except:
                        pass
                raise e
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"Error downloading {file_path.name}: {error_msg}", "ERROR")
            
            # Provide platform-specific guidance
            if self.current_platform == "windows":
                if "permission denied" in error_msg.lower():
                    self.log("💡 Windows: Try running as Administrator or check if file is in use", "INFO")
                elif "path too long" in error_msg.lower() or "filename too long" in error_msg.lower():
                    self.log("💡 Windows: Path too long, try a shorter output directory", "INFO")
                elif "disk full" in error_msg.lower() or "no space" in error_msg.lower():
                    self.log("💡 Windows: Check available disk space", "INFO")
            
            return False
    
    def download_firmware(self, firmware_info: Dict[str, Any], force: bool = False) -> bool:
        """Download firmware binary file"""
        version_number = firmware_info['version_number']
        firmware_id = firmware_info['id']
        
        # Create version-specific directory
        version_dir = self.firmware_dir / f"v{version_number}"
        version_dir.mkdir(exist_ok=True)
        
        firmware_file = version_dir / f"firmware_v{version_number}.bin"
        
        # Check if already downloaded
        if firmware_file.exists() and not force:
            self.log(f"Firmware v{version_number} already exists, skipping", "INFO")
            return True
        
        # Download the firmware with progress bar
        url = f"{self.client.base_url}/firmware/versions/{firmware_id}/binary"
        success = self.download_with_progress(
            url, 
            firmware_file, 
            f"Firmware v{version_number}"
        )
        
        if success:
            # Also download the manifest file
            self.download_firmware_manifest(firmware_id, version_dir, version_number)
        
        return success
    
    def download_firmware_manifest(self, firmware_id: int, version_dir: Path, version_number: str):
        """Download the ESP Web Tools manifest for the firmware"""
        try:
            manifest_file = version_dir / f"manifest_v{version_number}.json"
            
            response = self.client.session.get(
                f"{self.client.base_url}/firmware/versions/{firmware_id}/manifest",
                timeout=30
            )
            
            if response.status_code == 200:
                with open(manifest_file, 'w') as f:
                    f.write(response.text)
                self.log(f"Firmware manifest downloaded: {manifest_file.name}", "SUCCESS")
            else:
                self.log(f"Could not download firmware manifest (Status: {response.status_code})", "WARNING")
                
        except Exception as e:
            self.log(f"Error downloading firmware manifest: {e}", "WARNING")
    
    def get_audio_files_list(self) -> Optional[List[str]]:
        """Get list of available audio files"""
        try:
            self.log("Fetching audio files list", "PROGRESS")
            response = self.client.session.get(
                f"{self.client.base_url}/audio/files",
                timeout=30
            )
            
            if response.status_code == 200:
                files = response.json()
                self.log(f"Found {len(files)} audio file(s)", "SUCCESS")
                return files
            else:
                self.log(f"Failed to get audio files list (Status: {response.status_code})", "ERROR")
                return None
                
        except Exception as e:
            self.log(f"Error getting audio files list: {e}", "ERROR")
            return None
    
    def download_audio_file(self, filename: str, force: bool = False) -> bool:
        """Download a single audio file"""
        audio_file = self.audio_dir / filename
        
        # Check if already downloaded
        if audio_file.exists() and not force:
            self.log(f"Audio file {filename} already exists, skipping", "INFO")
            return True
        
        # Download with progress bar
        url = f"{self.client.base_url}/audio/file/{filename}"
        return self.download_with_progress(url, audio_file, f"Audio: {filename}")
    
    def download_all_audio_files(self, force: bool = False) -> bool:
        """Download all available audio files"""
        audio_files = self.get_audio_files_list()
        if not audio_files:
            return False
        
        success_count = 0
        total_count = len(audio_files)
        
        self.log(f"Starting download of {total_count} audio files", "INFO")
        
        for i, filename in enumerate(audio_files, 1):
            self.log(f"Processing audio file {i}/{total_count}: {filename}", "PROGRESS")
            if self.download_audio_file(filename, force):
                success_count += 1
            
            # Small delay between downloads to be nice to the server
            time.sleep(0.5)
        
        if success_count == total_count:
            self.log(f"All {total_count} audio files downloaded successfully", "SUCCESS")
            return True
        else:
            self.log(f"Downloaded {success_count}/{total_count} audio files", "WARNING")
            return False
    
    def run_setup(self, username: str = None, password: str = None, force: bool = False, 
                  firmware_only: bool = False, audio_only: bool = False) -> bool:
        """Run the complete setup process"""
        start_time = datetime.now()
        
        # Check system requirements first
        if not self.check_system_requirements():
            self.log("System requirements not met", "ERROR")
            return False
        
        # Acquire lock to prevent concurrent runs
        if not self.acquire_lock():
            return False
        
        try:
            self.log("=" * 60, "INFO")
            self.log("AutoTQ Setup & Update Tool Started", "INFO")
            self.log(f"Platform: {platform.system()} {platform.release()}", "INFO")
            self.log(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "INFO")
            self.log(f"Server: {self.client.base_url}", "INFO")
            self.log(f"Output directory: {self.output_dir.absolute()}", "INFO")
            self.log(f"Process ID: {os.getpid()}", "INFO")
            if self.current_platform == "windows":
                self.log(f"Working directory: {os.getcwd()}", "INFO")
            self.log("=" * 60, "INFO")
            
            # Load existing manifest
            manifest = self.load_manifest()
            
            # Authenticate
            if not self.authenticate(username, password):
                self.log("Setup failed: Authentication required", "ERROR")
                return False
            
            user_info = self.client.get_user_profile()
            if user_info:
                manifest['last_updated_by'] = user_info.get('username')
                manifest['last_update_time'] = datetime.now().isoformat()
            
            overall_success = True
            
            # Download firmware
            if not audio_only:
                self.log("\n📦 FIRMWARE DOWNLOAD", "INFO")
                self.log("-" * 30, "INFO")
                
                firmware_info = self.get_latest_firmware_version()
                if firmware_info:
                    if self.download_firmware(firmware_info, force):
                        manifest['latest_firmware'] = {
                            'version': firmware_info['version_number'],
                            'id': firmware_info['id'],
                            'downloaded_at': datetime.now().isoformat()
                        }
                    else:
                        overall_success = False
                else:
                    overall_success = False
            
            # Download audio files
            if not firmware_only:
                self.log("\n🔊 AUDIO FILES DOWNLOAD", "INFO")
                self.log("-" * 30, "INFO")
                
                if self.download_all_audio_files(force):
                    manifest['audio_files_updated_at'] = datetime.now().isoformat()
                else:
                    overall_success = False
            
            # Save manifest
            self.save_manifest(manifest)
            
            # Summary
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.log("\n" + "=" * 60, "INFO")
            if overall_success:
                self.log(f"Setup completed successfully in {duration:.1f} seconds", "SUCCESS")
            else:
                self.log(f"Setup completed with some errors in {duration:.1f} seconds", "WARNING")
            
            self.log(f"Files saved to: {self.output_dir.absolute()}", "INFO")
            self.log(f"Log file: {self.log_file}", "INFO")
            
            # Platform-specific usage tips
            if self.current_platform == "windows":
                self.log("💡 Windows: Use Windows Explorer or Command Prompt to access files", "INFO")
                # Check if firmware directories exist
                firmware_dirs = list(self.firmware_dir.glob("v*"))
                if firmware_dirs and any(d.is_dir() for d in firmware_dirs):
                    self.log("💡 Firmware ready for AutoTQ Firmware Programmer", "INFO")
                # Check if audio files exist
                if list(self.audio_dir.glob("*.wav")):
                    self.log("💡 Audio files ready for AutoTQ Device Programmer", "INFO")
            elif self.current_platform == "linux":
                self.log("💡 Linux: Files are ready for programming tools", "INFO")
                self.log(f"💡 Access via: cd {self.output_dir.absolute()}", "INFO")
            elif self.current_platform == "darwin":
                self.log("💡 macOS: Files are ready for programming tools", "INFO")
                self.log(f"💡 Access via Finder or: cd {self.output_dir.absolute()}", "INFO")
            
            self.log("=" * 60, "INFO")
            
            return overall_success
            
        finally:
            # Always release the lock
            self.release_lock()


def main():
    """Command line interface"""
    parser = argparse.ArgumentParser(
        description="AutoTQ Setup & Update Tool - Download firmware and audio files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_setup.py                           # Download everything (re-downloads existing files)
  python autotq_setup.py --skip-existing           # Skip files that already exist locally
  python autotq_setup.py --firmware-only           # Only download firmware
  python autotq_setup.py --audio-only              # Only download audio files
  python autotq_setup.py --output-dir ./downloads  # Custom output directory
  python autotq_setup.py --username admin          # Pre-specify username
  python autotq_setup.py --url https://localhost:8000 --no-ssl-verify  # Use local development server

Windows examples:
  python autotq_setup.py --output-dir "C:\\AutoTQ\\Files"  # Windows path
  python autotq_setup.py --no-progress             # Better for Windows Command Prompt
  
Platform notes:
  - Windows: May require running as Administrator for some package installations
  - Linux: Ensure proper permissions for output directory
  - macOS: Should work out of the box with homebrew Python
        """
    )
    
    parser.add_argument("--url", default="https://seahorse-app-ax33h.ondigitalocean.app",
                       help="Server URL (default: https://seahorse-app-ax33h.ondigitalocean.app)")
    parser.add_argument("--no-ssl-verify", action="store_true",
                       help="Disable SSL certificate verification (for local development)")
    parser.add_argument("--username", help="Username for login")
    parser.add_argument("--password", help="Password for login")
    parser.add_argument("--output-dir", default=".",
                       help="Directory to download files to (default: current directory)")
    parser.add_argument("--skip-existing", action="store_true",
                       help="Skip downloading files that already exist (default: re-download all files)")
    parser.add_argument("--force", action="store_true", 
                       help="DEPRECATED: Re-download is now the default behavior. Use --skip-existing to skip files.")
    parser.add_argument("--firmware-only", action="store_true",
                       help="Only download firmware files")
    parser.add_argument("--audio-only", action="store_true",
                       help="Only download audio files")
    parser.add_argument("--no-progress", action="store_true",
                       help="Disable progress bars (useful for logging)")
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.firmware_only and args.audio_only:
        print("❌ Cannot specify both --firmware-only and --audio-only")
        sys.exit(1)
    
    # Disable tqdm if requested
    if args.no_progress:
        global HAS_TQDM
        HAS_TQDM = False
    
    # Handle deprecated --force flag
    if args.force:
        print("⚠️  Warning: --force flag is deprecated. Re-download is now the default behavior.")
        print("💡 Use --skip-existing if you want to skip files that already exist.")
    
    # Initialize setup tool
    setup = AutoTQSetup(
        base_url=args.url,
        verify_ssl=not args.no_ssl_verify,
        output_dir=args.output_dir
    )
    
    # Run setup
    try:
        success = setup.run_setup(
            username=args.username,
            password=args.password,
            force=not args.skip_existing,
            firmware_only=args.firmware_only,
            audio_only=args.audio_only
        )
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        setup.log("\nSetup interrupted by user", "WARNING")
        setup.release_lock()
        sys.exit(1)
    except Exception as e:
        setup.log(f"Unexpected error: {e}", "ERROR")
        setup.release_lock()
        sys.exit(1)


if __name__ == "__main__":
    main() 