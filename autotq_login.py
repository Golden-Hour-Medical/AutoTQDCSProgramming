#!/usr/bin/env python3
"""
AutoTQ Login and API Key Generator
Login with username/password and generate a new API key
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


class AutoTQLogin:
    def __init__(self, base_url: str = None, verify_ssl: bool = True):
        """
        Initialize the AutoTQ login client
        
        Args:
            base_url: Base URL of the AutoTQ server (default: https://api.theautotq.com)
            verify_ssl: Whether to verify SSL certificates (True for production)
        """
        self.base_url = base_url or "https://api.theautotq.com"
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.access_token: Optional[str] = None
    
    def login(self, username: str = None, password: str = None) -> bool:
        """
        Login with username and password to get an access token
        
        Args:
            username: Username (will prompt if not provided)
            password: Password (will prompt if not provided)
            
        Returns:
            bool: True if login successful, False otherwise
        """
        if not username:
            username = input("Username: ")
        
        if not password:
            try:
                password = getpass.getpass("Password: ")
            except Exception:
                password = input("Password: ")
        
        if not username or not password:
            print("❌ Username and password are required")
            return False
        
        try:
            # Login endpoint expects form data
            response = self.session.post(
                f"{self.base_url}/auth/token",
                data={
                    "username": username,
                    "password": password
                },
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                if self.access_token:
                    # Set Bearer token in session headers
                    self.session.headers['Authorization'] = f"Bearer {self.access_token}"
                    print("✅ Login successful!")
                    return True
                else:
                    print("❌ No access token in response")
                    return False
            elif response.status_code == 401:
                print("❌ Invalid username or password")
                return False
            elif response.status_code == 403:
                error_detail = response.json().get('detail', 'Account locked')
                print(f"❌ {error_detail}")
                return False
            else:
                error_detail = response.json().get('detail', f'Status: {response.status_code}')
                print(f"❌ Login failed: {error_detail}")
                return False
                
        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to {self.base_url}")
            print("   Please check if the server is running and the URL is correct")
            return False
        except Exception as e:
            print(f"❌ Error during login: {e}")
            return False
    
    def create_api_key(self, name: str = None) -> Optional[str]:
        """
        Create a new API key for the current user
        
        Args:
            name: Optional name for the API key
            
        Returns:
            str: The generated API key, or None if failed
        """
        if not self.access_token:
            print("❌ Must be logged in to create an API key")
            return None
        
        try:
            payload = {}
            if name:
                payload["name"] = name
            
            response = self.session.post(
                f"{self.base_url}/users/me/api-keys",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201:
                key_data = response.json()
                api_key = key_data.get("api_key")
                key_id = key_data.get("id")
                key_name = key_data.get("name", "Unnamed")
                
                if api_key:
                    print(f"✅ API key created successfully!")
                    print(f"   Key ID: {key_id}")
                    print(f"   Name: {key_name}")
                    print(f"   API Key: {api_key}")
                    print("\n⚠️  IMPORTANT: Save this API key now. It will not be shown again!")
                    return api_key
                else:
                    print("❌ No API key in response")
                    return None
            elif response.status_code == 401:
                print("❌ Unauthorized. Please login again.")
                return None
            else:
                error_detail = response.json().get('detail', f'Status: {response.status_code}')
                print(f"❌ Failed to create API key: {error_detail}")
                return None
                
        except Exception as e:
            print(f"❌ Error creating API key: {e}")
            return None
    
    def save_api_key(self, api_key: str) -> bool:
        """
        Save API key to autotq_token.json
        
        Args:
            api_key: The API key to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        token_file = "autotq_token.json"
        try:
            payload = {
                "api_key": api_key,
                "saved_at": datetime.utcnow().isoformat() + "Z"
            }
            
            with open(token_file, 'w') as f:
                json.dump(payload, f, indent=2)
            
            print(f"💾 API key saved to {token_file}")
            return True
            
        except Exception as e:
            print(f"❌ Could not save API key to {token_file}: {e}")
            print("   Please save it manually!")
            return False
    
    def get_user_profile(self) -> Optional[Dict[str, Any]]:
        """
        Get current user profile information
        
        Returns:
            dict: User profile data or None if failed
        """
        if not self.access_token:
            return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/users/me",
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return None
                
        except Exception:
            return None


def main():
    """Main function for interactive use"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="AutoTQ Login and API Key Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_login.py
  python autotq_login.py --url https://api.theautotq.com
  python autotq_login.py --url https://localhost:8000 --no-ssl-verify
  python autotq_login.py --username myuser --key-name "Production Key"
        """
    )
    parser.add_argument("--url", default="https://api.theautotq.com",
                       help="Server URL (default: https://api.theautotq.com)")
    parser.add_argument("--no-ssl-verify", action="store_true",
                       help="Disable SSL certificate verification (for local dev)")
    parser.add_argument("--username", help="Username (will prompt if not provided)")
    parser.add_argument("--key-name", help="Name for the API key (optional)")
    
    args = parser.parse_args()
    
    print("🔐 AutoTQ Login and API Key Generator")
    print("=" * 50)
    
    # Initialize client
    client = AutoTQLogin(
        base_url=args.url,
        verify_ssl=not args.no_ssl_verify
    )
    
    # Login
    print("\n📝 Step 1: Login")
    print("-" * 50)
    success = client.login(username=args.username)
    
    if not success:
        print("\n❌ Login failed. Cannot generate API key.")
        exit(1)
    
    # Get user info
    user_info = client.get_user_profile()
    if user_info:
        print(f"👤 Logged in as: {user_info.get('username', 'Unknown')}")
        print(f"🏷️  Role: {user_info.get('role', 'Unknown')}")
    
    # Create API key
    print("\n🔑 Step 2: Generate API Key")
    print("-" * 50)
    api_key = client.create_api_key(name=args.key_name)
    
    if not api_key:
        print("\n❌ Failed to generate API key.")
        exit(1)
    
    # Save API key
    print("\n💾 Step 3: Save API Key")
    print("-" * 50)
    client.save_api_key(api_key)
    
    print("\n🎉 Success! Your API key has been saved.")
    print("\nYou can now use it with other AutoTQ tools:")
    print("  python autotq_client.py")
    print("  python autotq_check_auth.py")


if __name__ == "__main__":
    main()

