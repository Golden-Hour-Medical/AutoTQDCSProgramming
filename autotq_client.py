#!/usr/bin/env python3
"""
AutoTQ Device Management Client
Python client for authentication and device management with the actual FastAPI server
"""
import os
import json
import requests
import getpass
from typing import Optional, Dict, Any
from datetime import datetime
import urllib3

# Disable SSL warnings for self-signed certificates in local development
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class AutoTQClient:
    def __init__(self, base_url: str = None, verify_ssl: bool = False):
        """
        Initialize the AutoTQ client
        
        Args:
            base_url: Base URL of the AutoTQ server (default: https://localhost:8000)
            verify_ssl: Whether to verify SSL certificates (False for local dev)
        """
        self.base_url = base_url or "https://localhost:8000"
        self.verify_ssl = verify_ssl
        self.api_key: Optional[str] = None
        # Back-compat attribute so legacy callers don't crash
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = verify_ssl
        
        # Load existing API key if available (backward-compatible read)
        self._load_api_key()
    
    def _load_api_key(self) -> None:
        """Load API key from autotq_token.json in common locations."""
        candidates = []
        # Project directory
        candidates.append("autotq_token.json")
        # Home directory
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            candidates.append(os.path.join(home, ".autotq_token.json"))
            candidates.append(os.path.join(home, ".autotq", "autotq_token.json"))
        # APPDATA on Windows
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "AutoTQ", "autotq_token.json"))

        for path in candidates:
            try:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        data = json.load(f)
                        api_key = data.get('api_key')
                        if api_key:
                            self.api_key = api_key
                            self.session.headers.update({'X-API-Key': self.api_key})
                            print(f"📝 Loaded existing API key from {path}")
                            return
                        # Check for legacy bearer token
                        if data.get('access_token') and not data.get('api_key'):
                            print("ℹ️  Legacy bearer token found but API now uses X-API-Key. Please run 'python autotq_login.py' to generate an API key.")
            except Exception:
                # Ignore errors and continue to next candidate
                continue

    def _save_api_key(self, api_key: str) -> None:
        """Persist API key to autotq_token.json in best-available writable location."""
        payload = {"api_key": api_key, "saved_at": datetime.utcnow().isoformat() + "Z"}
        tried = []
        # Preference order: project dir, ~/.autotq, %APPDATA%/AutoTQ
        targets = []
        targets.append("autotq_token.json")
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            homedir = os.path.join(home, ".autotq")
            targets.append(os.path.join(home, ".autotq_token.json"))
            targets.append(os.path.join(homedir, "autotq_token.json"))
        appdata = os.environ.get("APPDATA")
        if appdata:
            appdir = os.path.join(appdata, "AutoTQ")
            targets.append(os.path.join(appdir, "autotq_token.json"))

        saved_any = False
        for json_path in targets:
            try:
                # ensure directory exists
                jd = os.path.dirname(json_path)
                if jd and not os.path.exists(jd):
                    os.makedirs(jd, exist_ok=True)
                with open(json_path, 'w') as f:
                    json.dump(payload, f, indent=2)
                print(f"💾 Saved API key to {json_path}")
                saved_any = True
                break
            except Exception as e:
                tried.append((json_path, str(e)))
                continue
        if not saved_any:
            for path, err in tried:
                print(f"⚠️  Warning: Could not write {path}: {err}")
    
    def set_api_key(self, api_key: Optional[str] = None, prompt_if_missing: bool = True) -> bool:
        """Set the API key, verify it by requesting the current user, and store in session headers.

        Args:
            api_key: The plaintext API key. If None and prompt_if_missing, prompt securely.
            prompt_if_missing: Whether to prompt the user for input if the key is missing.

        Returns:
            bool: True if the API key works, False otherwise.
        """
        if not api_key and prompt_if_missing:
            try:
                api_key = getpass.getpass("API key: ")
            except Exception:
                api_key = input("API key: ")

        if not api_key:
            print("❌ No API key provided")
            return False

        # Set header and verify
        self.session.headers['X-API-Key'] = api_key
        try:
            me = self.get_user_profile()
            if me:
                self.api_key = api_key
                print("✅ API key accepted")
                print(f"👤 Logged in as: {me.get('username', 'Unknown')}")
                # Persist the working API key for future runs
                self._save_api_key(api_key)
                return True
            else:
                # Remove header on failure
                self.session.headers.pop('X-API-Key', None)
                print("❌ Invalid API key")
                return False
        except Exception as e:
            self.session.headers.pop('X-API-Key', None)
            print(f"❌ Error validating API key: {e}")
            return False
    
    # Backward-compatible alias for existing callers
    def login(self, *_args, **_kwargs) -> bool:
        print("\n🔐 AutoTQ API Key Authentication")
        print("=" * 50)
        return self.set_api_key(prompt_if_missing=True)
    
    def get_user_profile(self) -> Optional[Dict[str, Any]]:
        """
        Get current user profile information from /users/me endpoint
        
        Returns:
            dict: User profile data or None if failed
        """
        try:
            # Prefer versioned API path; fall back to legacy path
            response = self.session.get(f"{self.base_url}/api/v1/users/me", timeout=30)
            if response.status_code == 404:
                response = self.session.get(f"{self.base_url}/users/me", timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                print("❌ Unauthorized. API key invalid or expired. Please enter it again.")
                self.api_key = None
                if 'X-API-Key' in self.session.headers:
                    del self.session.headers['X-API-Key']
                return None
            else:
                print(f"❌ Failed to get user profile (Status: {response.status_code})")
                return None
                
        except Exception as e:
            print(f"❌ Error getting user profile: {e}")
            return None
    
    def logout(self) -> bool:
        """
        Logout from the AutoTQ server
        
        Returns:
            bool: True if logout successful, False otherwise
        """
        # For API key auth, "logout" simply clears the local header
        if 'X-API-Key' in self.session.headers:
            del self.session.headers['X-API-Key']
        self.api_key = None
        print("✅ API key cleared from local session")
        return True
    
    def check_connection(self) -> bool:
        """
        Check if the server is accessible
        
        Returns:
            bool: True if server is accessible, False otherwise
        """
        try:
            print(f"🔄 Checking connection to {self.base_url}...")
            
            # Try accessing the docs endpoint (usually available)
            response = self.session.get(
                f"{self.base_url}/docs",
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ Server is accessible")
                return True
            else:
                # Try the root endpoint as fallback
                response = self.session.get(
                    f"{self.base_url}/",
                    timeout=10
                )
                if response.status_code in [200, 307, 308]:  # Include redirects
                    print("✅ Server is accessible")
                    return True
                else:
                    print(f"⚠️  Server responded with status: {response.status_code}")
                    return False
                
        except requests.exceptions.SSLError:
            print("❌ SSL Certificate error")
            return False
        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to {self.base_url}")
            return False
        except Exception as e:
            print(f"❌ Connection check failed: {e}")
            return False
    
    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated by verifying token with server
        
        Returns:
            bool: True if authenticated, False otherwise
        """
        # API key flow: consider authenticated if API key header present and /users/me succeeds
        if self.api_key or ('X-API-Key' in self.session.headers and self.session.headers.get('X-API-Key')):
            user_info = self.get_user_profile()
            return user_info is not None
        return False
    
    def change_password(self, current_password: str = None, new_password: str = None) -> bool:
        """
        Change user password
        
        Args:
            current_password: Current password (will prompt if not provided)
            new_password: New password (will prompt if not provided)
            
        Returns:
            bool: True if password changed successfully, False otherwise
        """
        # Not applicable for API key auth; keep endpoint call for compatibility if server supports it
        if not self.is_authenticated():
            print("❌ Must be authenticated to change password")
            return False
        
        if not current_password:
            current_password = getpass.getpass("Current password: ")
        
        if not new_password:
            new_password = getpass.getpass("New password: ")
            confirm_password = getpass.getpass("Confirm new password: ")
            if new_password != confirm_password:
                print("❌ Passwords do not match")
                return False
        
        try:
            response = self.session.post(
                f"{self.base_url}/users/change-password",
                json={
                    "current_password": current_password,
                    "new_password": new_password
                },
                timeout=30
            )
            
            if response.status_code == 200:
                print("✅ Password changed successfully")
                return True
            elif response.status_code == 401:
                print("❌ Current password is incorrect")
                return False
            else:
                error_detail = response.json().get('detail', 'Unknown error')
                print(f"❌ Password change failed: {error_detail}")
                return False
                
        except Exception as e:
            print(f"❌ Error changing password: {e}")
            return False
    
    def get_my_devices(self) -> Optional[list]:
        """
        Get devices owned by the current user
        
        Returns:
            list: List of user's devices or None if failed
        """
        if not self.is_authenticated():
            print("❌ Must be authenticated to view devices")
            return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/devices/my-devices",
                timeout=30
            )
            
            if response.status_code == 200:
                devices = response.json()
                print(f"📱 Found {len(devices)} device(s) associated with your account")
                
                for i, device in enumerate(devices, 1):
                    print(f"\n  Device {i}:")
                    print(f"    🏷️  GS1 Barcode: {device.get('gs1_barcode')}")
                    print(f"    📦 Model: {device.get('model_name')}")
                    print(f"    🔗 MAC Address: {device.get('mac_address', 'Not set')}")
                    print(f"    ✅ Registered: {'Yes' if device.get('is_registered') else 'No'}")
                    
                    location = device.get('current_location_description')
                    if location:
                        print(f"    📍 Location: {location}")
                    
                    if device.get('city') and device.get('state'):
                        print(f"    🌍 City/State: {device['city']}, {device['state']}")
                
                return devices
            else:
                print(f"❌ Failed to get devices (Status: {response.status_code})")
                return None
                
        except Exception as e:
            print(f"❌ Error getting devices: {e}")
            return None


def main():
    """Main function for interactive use"""
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoTQ Device Management Client")
    parser.add_argument("--url", default="https://localhost:8000", 
                       help="Server URL (default: https://localhost:8000)")
    parser.add_argument("--no-ssl-verify", action="store_true",
                       help="Disable SSL certificate verification (for local dev)")
    parser.add_argument("--api-key", help="API key for authentication (X-API-Key)")
    parser.add_argument("--check", action="store_true", 
                       help="Only check server connection")
    parser.add_argument("--logout", action="store_true",
                       help="Logout from the server")
    parser.add_argument("--change-password", action="store_true",
                       help="Change user password")
    parser.add_argument("--devices", action="store_true",
                       help="List user's devices")
    
    args = parser.parse_args()
    
    # Initialize client
    client = AutoTQClient(
        base_url=args.url,
        verify_ssl=not args.no_ssl_verify
    )
    
    print("🚀 AutoTQ Device Management Client")
    print("=" * 50)
    
    # Handle different commands
    if args.check:
        success = client.check_connection()
        exit(0 if success else 1)
    
    elif args.logout:
        success = client.logout()
        exit(0 if success else 1)
    
    elif args.change_password:
        if not client.is_authenticated():
            print("❌ Must authenticate first to change password")
            success = client.set_api_key(args.api_key, prompt_if_missing=True)
            if not success:
                exit(1)
        success = client.change_password()
        exit(0 if success else 1)
    
    elif args.devices:
        if not client.is_authenticated():
            print("❌ Must authenticate first to view devices")
            success = client.set_api_key(args.api_key, prompt_if_missing=True)
            if not success:
                exit(1)
        devices = client.get_my_devices()
        exit(0 if devices is not None else 1)
    
    else:
        # Check if already authenticated
        if client.is_authenticated():
            print("✅ Already authenticated!")
            user_info = client.get_user_profile()
            if user_info:
                print(f"👤 Logged in as: {user_info.get('username', 'Unknown')}")
                print(f"🏷️  Role: {user_info.get('role', 'Unknown')}")
                print("\nAvailable commands:")
                print("  --logout          Clear local API key header")
                print("  --change-password Change your password (if supported)")
                print("  --devices         List your devices")
                print("  --check           Check server connection")
        else:
            # Attempt API key auth
            success = client.set_api_key(args.api_key, prompt_if_missing=True)
            if success:
                print("\n🎉 Authentication complete! You can now use the AutoTQ system.")
                print("\nTry these commands:")
                print("  python autotq_client.py --devices")
                print("  python autotq_client.py --change-password")
                print("  python autotq_client.py --logout")
            else:
                print("\n❌ Authentication failed. Please check your API key and try again.")
                exit(1)


if __name__ == "__main__":
    main() 