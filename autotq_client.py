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
        self.token = None
        self.token_type = "bearer"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        
        # Load existing token if available
        self._load_token()
    
    def _load_token(self) -> None:
        """Load authentication token from file if it exists"""
        token_file = "autotq_token.json"
        if os.path.exists(token_file):
            try:
                with open(token_file, 'r') as f:
                    data = json.load(f)
                    self.token = data.get('access_token')
                    self.token_type = data.get('token_type', 'bearer')
                    if self.token:
                        self.session.headers.update({
                            'Authorization': f'{self.token_type.title()} {self.token}'
                        })
                        print("📝 Loaded existing authentication token")
            except Exception as e:
                print(f"⚠️  Warning: Could not load token file: {e}")
    
    def _save_token(self, token_data: Dict[str, Any]) -> None:
        """Save authentication token to file"""
        token_file = "autotq_token.json"
        try:
            save_data = {
                'access_token': token_data.get('access_token'),
                'token_type': token_data.get('token_type', 'bearer'),
                'training_completed': token_data.get('training_completed', False),
                'requires_training': token_data.get('requires_training', True),
                'saved_at': datetime.now().isoformat()
            }
            
            with open(token_file, 'w') as f:
                json.dump(save_data, f, indent=2)
            print("💾 Authentication token saved")
        except Exception as e:
            print(f"⚠️  Warning: Could not save token: {e}")
    
    def login(self, username: str = None, password: str = None) -> bool:
        """
        Authenticate user with the AutoTQ server using OAuth2 form data
        
        Args:
            username: Username (will prompt if not provided)
            password: Password (will prompt securely if not provided)
            
        Returns:
            bool: True if login successful, False otherwise
        """
        print("\n🔐 AutoTQ Device Management System Login")
        print("=" * 50)
        
        # Get credentials if not provided
        if not username:
            username = input("Username: ")
        
        if not password:
            password = getpass.getpass("Password: ")
        
        try:
            print("🔄 Attempting to authenticate...")
            
            # Use form data as expected by OAuth2PasswordRequestForm
            form_data = {
                'username': username,
                'password': password,
                'grant_type': 'password'  # OAuth2 standard
            }
            
            # Make login request to the correct endpoint
            response = self.session.post(
                f"{self.base_url}/auth/token",
                data=form_data,  # Use form data, not JSON
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.token = token_data.get('access_token')
                self.token_type = token_data.get('token_type', 'bearer')
                
                if self.token:
                    # Update session headers
                    self.session.headers.update({
                        'Authorization': f'{self.token_type.title()} {self.token}'
                    })
                    
                    # Save token data
                    self._save_token(token_data)
                    
                    print("✅ Login successful!")
                    
                    # Display training status if available
                    training_completed = token_data.get('training_completed', False)
                    requires_training = token_data.get('requires_training', False)
                    
                    if training_completed:
                        print("🎓 Training: ✅ Completed")
                    elif requires_training:
                        print("📚 Training: ⚠️  Required (incomplete)")
                    else:
                        print("🎓 Training: Not required for your role")
                    
                    # Get and display user info
                    user_info = self.get_user_profile()
                    if user_info:
                        print(f"👤 Welcome, {user_info.get('username', 'User')}!")
                        print(f"📧 Email: {user_info.get('email', 'N/A')}")
                        print(f"🏷️  Role: {user_info.get('role', 'N/A')}")
                        print(f"🕐 Login time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        
                        if user_info.get('full_name'):
                            print(f"📋 Full name: {user_info['full_name']}")
                        
                        # Account status
                        if user_info.get('is_active'):
                            print("✅ Account status: Active")
                        else:
                            print("⚠️  Account status: Inactive")
                        
                        created_at = user_info.get('created_at')
                        if created_at:
                            print(f"📅 Account created: {created_at}")
                    
                    return True
                else:
                    print("❌ Login failed: No access token received")
                    return False
            
            elif response.status_code == 401:
                print("❌ Login failed: Invalid credentials")
                return False
            
            elif response.status_code == 403:
                print("❌ Login failed: Account may be locked or access forbidden")
                return False
            
            else:
                print(f"❌ Login failed: Server error (Status: {response.status_code})")
                try:
                    error_detail = response.json().get('detail', 'Unknown error')
                    print(f"Error details: {error_detail}")
                except:
                    print(f"Error details: {response.text}")
                return False
                
        except requests.exceptions.SSLError:
            print("❌ SSL Certificate error. Try using --no-ssl-verify flag for local development")
            return False
        except requests.exceptions.ConnectionError:
            print(f"❌ Connection error: Could not connect to {self.base_url}")
            print("Make sure the AutoTQ server is running and accessible")
            return False
        except requests.exceptions.Timeout:
            print("❌ Login timeout: Server did not respond in time")
            return False
        except Exception as e:
            print(f"❌ Unexpected error during login: {e}")
            return False
    
    def get_user_profile(self) -> Optional[Dict[str, Any]]:
        """
        Get current user profile information from /users/me endpoint
        
        Returns:
            dict: User profile data or None if failed
        """
        if not self.token:
            print("❌ Not authenticated. Please login first.")
            return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/users/me",
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                print("❌ Authentication expired. Please login again.")
                self.token = None
                # Clear session headers
                if 'Authorization' in self.session.headers:
                    del self.session.headers['Authorization']
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
        if not self.token:
            print("ℹ️  Not currently logged in")
            return True
        
        try:
            print("🔄 Logging out...")
            
            response = self.session.post(
                f"{self.base_url}/auth/logout",
                timeout=30
            )
            
            # Clear token regardless of response
            self.token = None
            self.token_type = "bearer"
            if 'Authorization' in self.session.headers:
                del self.session.headers['Authorization']
            
            # Remove token file
            token_file = "autotq_token.json"
            if os.path.exists(token_file):
                os.remove(token_file)
            
            if response.status_code in [200, 401]:  # 401 means already logged out
                print("✅ Logout successful!")
                return True
            else:
                print(f"⚠️  Logout response: {response.status_code}")
                print("✅ Local session cleared")
                return True
                
        except Exception as e:
            print(f"⚠️  Error during logout: {e}")
            print("✅ Local session cleared")
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
        if not self.token:
            return False
        
        # Verify token is still valid by checking user profile
        user_info = self.get_user_profile()
        return user_info is not None
    
    def change_password(self, current_password: str = None, new_password: str = None) -> bool:
        """
        Change user password
        
        Args:
            current_password: Current password (will prompt if not provided)
            new_password: New password (will prompt if not provided)
            
        Returns:
            bool: True if password changed successfully, False otherwise
        """
        if not self.is_authenticated():
            print("❌ Must be logged in to change password")
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
            print("❌ Must be logged in to view devices")
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
    parser.add_argument("--username", help="Username for login")
    parser.add_argument("--password", help="Password for login")
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
            print("❌ Must login first to change password")
            success = client.login(args.username, args.password)
            if not success:
                exit(1)
        
        success = client.change_password()
        exit(0 if success else 1)
    
    elif args.devices:
        if not client.is_authenticated():
            print("❌ Must login first to view devices")
            success = client.login(args.username, args.password)
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
                print("  --logout          Logout from the server")
                print("  --change-password Change your password")
                print("  --devices         List your devices")
                print("  --check           Check server connection")
        else:
            # Attempt login
            success = client.login(args.username, args.password)
            if success:
                print("\n🎉 Authentication complete! You can now use the AutoTQ system.")
                print("\nTry these commands:")
                print("  python autotq_client.py --devices")
                print("  python autotq_client.py --change-password")
                print("  python autotq_client.py --logout")
            else:
                print("\n❌ Authentication failed. Please check your credentials and try again.")
                exit(1)


if __name__ == "__main__":
    main() 