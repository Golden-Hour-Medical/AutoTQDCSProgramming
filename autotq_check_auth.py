#!/usr/bin/env python3
"""
AutoTQ Authentication Checker
Check if current authentication (API key) is valid
"""
import os
import json
import requests
from typing import Optional, Dict, Any
import urllib3

# Disable SSL warnings for self-signed certificates in local development
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AutoTQAuthChecker:
    def __init__(self, base_url: str = None, verify_ssl: bool = True):
        """
        Initialize the AutoTQ auth checker
        
        Args:
            base_url: Base URL of the AutoTQ server (default: https://api.theautotq.com)
            verify_ssl: Whether to verify SSL certificates (True for production)
        """
        self.base_url = base_url or "https://api.theautotq.com"
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.api_key: Optional[str] = None
    
    def _load_api_key(self) -> Optional[str]:
        """Load API key from autotq_token.json in common locations"""
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
                            return api_key
            except Exception:
                continue
        
        return None
    
    def check_authentication(self, api_key: str = None) -> Dict[str, Any]:
        """
        Check if authentication is valid
        
        Args:
            api_key: API key to check (will load from file if not provided)
            
        Returns:
            dict: Status information with 'valid', 'user_info', 'error', etc.
        """
        # Load API key if not provided
        if not api_key:
            api_key = self._load_api_key()
        
        if not api_key:
            return {
                "valid": False,
                "error": "No API key found",
                "message": "No API key found in common locations. Please run 'python autotq_login.py' to generate one."
            }
        
        self.api_key = api_key
        self.session.headers['X-API-Key'] = api_key
        
        try:
            # Try versioned API first, fall back to legacy
            response = self.session.get(
                f"{self.base_url}/api/v1/users/me",
                timeout=30
            )
            
            if response.status_code == 404:
                response = self.session.get(
                    f"{self.base_url}/users/me",
                    timeout=30
                )
            
            if response.status_code == 200:
                user_info = response.json()
                return {
                    "valid": True,
                    "user_info": user_info,
                    "api_key": api_key[:20] + "..." if len(api_key) > 20 else api_key,
                    "message": "Authentication successful"
                }
            elif response.status_code == 401:
                return {
                    "valid": False,
                    "error": "Unauthorized",
                    "message": "API key is invalid or expired. Please run 'python autotq_login.py' to generate a new one."
                }
            else:
                error_detail = response.json().get('detail', f'Status: {response.status_code}')
                return {
                    "valid": False,
                    "error": f"HTTP {response.status_code}",
                    "message": f"Authentication check failed: {error_detail}"
                }
                
        except requests.exceptions.ConnectionError:
            return {
                "valid": False,
                "error": "Connection Error",
                "message": f"Cannot connect to {self.base_url}. Please check if the server is running."
            }
        except requests.exceptions.SSLError:
            return {
                "valid": False,
                "error": "SSL Error",
                "message": "SSL certificate verification failed. Try using --no-ssl-verify for local development."
            }
        except Exception as e:
            return {
                "valid": False,
                "error": str(type(e).__name__),
                "message": f"Error checking authentication: {e}"
            }
    
    def check_server_connection(self) -> bool:
        """
        Check if server is accessible
        
        Returns:
            bool: True if server is accessible, False otherwise
        """
        try:
            response = self.session.get(
                f"{self.base_url}/docs",
                timeout=10
            )
            return response.status_code == 200
        except Exception:
            try:
                response = self.session.get(
                    f"{self.base_url}/",
                    timeout=10
                )
                return response.status_code in [200, 307, 308]
            except Exception:
                return False


def main():
    """Main function for interactive use"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="AutoTQ Authentication Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_check_auth.py
  python autotq_check_auth.py --url https://api.theautotq.com
  python autotq_check_auth.py --url https://localhost:8000 --no-ssl-verify
  python autotq_check_auth.py --api-key YOUR_API_KEY
        """
    )
    parser.add_argument("--url", default="https://api.theautotq.com",
                       help="Server URL (default: https://api.theautotq.com)")
    parser.add_argument("--no-ssl-verify", action="store_true",
                       help="Disable SSL certificate verification (for local dev)")
    parser.add_argument("--api-key", help="API key to check (will load from file if not provided)")
    parser.add_argument("--check-server", action="store_true",
                       help="Only check if server is accessible")
    
    args = parser.parse_args()
    
    print("🔍 AutoTQ Authentication Checker")
    print("=" * 50)
    
    # Initialize checker
    checker = AutoTQAuthChecker(
        base_url=args.url,
        verify_ssl=not args.no_ssl_verify
    )
    
    # Check server connection first
    if args.check_server:
        print(f"\n🔄 Checking server connection to {args.url}...")
        if checker.check_server_connection():
            print("✅ Server is accessible")
            exit(0)
        else:
            print("❌ Server is not accessible")
            exit(1)
    
    # Check authentication
    print(f"\n🔍 Checking authentication...")
    print(f"   Server: {args.url}")
    
    result = checker.check_authentication(api_key=args.api_key)
    
    if result["valid"]:
        print("\n✅ Authentication Status: VALID")
        print("-" * 50)
        
        user_info = result.get("user_info", {})
        print(f"👤 Username: {user_info.get('username', 'Unknown')}")
        print(f"📧 Email: {user_info.get('email', 'Unknown')}")
        print(f"🏷️  Role: {user_info.get('role', 'Unknown')}")
        print(f"🆔 User ID: {user_info.get('id', 'Unknown')}")
        
        if result.get("api_key"):
            print(f"🔑 API Key: {result['api_key']}")
        
        print(f"\n✅ {result['message']}")
        exit(0)
    else:
        print("\n❌ Authentication Status: INVALID")
        print("-" * 50)
        print(f"❌ Error: {result.get('error', 'Unknown error')}")
        print(f"💡 {result.get('message', 'Please check your API key')}")
        exit(1)


if __name__ == "__main__":
    main()

