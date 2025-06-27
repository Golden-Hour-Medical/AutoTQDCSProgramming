#!/usr/bin/env python3
"""
AutoTQ Programmer - All-in-One ESP32-S3 Programming Tool
Automatically detects AutoTQ devices, flashes firmware, and transfers audio files.
Run this after using autotq_setup.py to download the latest files.
"""

import os
import sys
import time
import argparse
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

# Import our existing programmers
try:
    from autotq_firmware_programmer import AutoTQFirmwareProgrammer
    from autotq_device_programmer import AutoTQDeviceProgrammer
except ImportError as e:
    print(f"❌ Error importing required modules: {e}")
    print("Make sure autotq_firmware_programmer.py and autotq_device_programmer.py are in the same directory")
    sys.exit(1)


class AutoTQProgrammer:
    """All-in-One AutoTQ Device Programmer"""
    
    def __init__(self, firmware_dir: str = None, audio_dir: str = None):
        """
        Initialize the combined AutoTQ programmer
        
        Args:
            firmware_dir: Directory containing firmware files (default: ./firmware)
            audio_dir: Directory containing audio files (default: ./audio)
        """
        self.firmware_dir = Path(firmware_dir) if firmware_dir else Path("firmware")
        self.audio_dir = Path(audio_dir) if audio_dir else Path("audio")
        
        # Initialize sub-programmers
        self.firmware_programmer = AutoTQFirmwareProgrammer(str(self.firmware_dir))
        self.device_programmer = AutoTQDeviceProgrammer(audio_dir=str(self.audio_dir))
        
        current_platform = platform.system()
        print(f"🚀 AutoTQ All-in-One Programmer initialized ({current_platform})")
        print(f"📦 Firmware directory: {self.firmware_dir.absolute()}")
        print(f"🎵 Audio directory: {self.audio_dir.absolute()}")
        
        # Check requirements
        self.check_requirements()
    
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
            "FLASH": "⚡ ",
            "AUDIO": "🎵 "
        }
        emoji = emoji_map.get(level, "")
        print(f"[{timestamp}] {emoji} {message}")
    
    def check_requirements(self) -> bool:
        """Check if all required files and tools are available"""
        self.log("Checking requirements...", "PROGRESS")
        
        # Check if esptool is available
        if not self.firmware_programmer.esptool_path:
            self.log("esptool not found - firmware flashing will not be available", "ERROR")
            self.log("Install with: pip install esptool", "INFO")
            return False
        
        # Check if firmware is available
        if not self.firmware_programmer.latest_firmware:
            self.log("No firmware found - run autotq_setup.py first", "ERROR")
            return False
        
        # Check if audio files are available
        available_audio, missing_audio = self.device_programmer.check_local_files()
        if not available_audio:
            self.log("No audio files found - run autotq_setup.py first", "ERROR")
            return False
        elif missing_audio:
            self.log(f"Missing audio files: {', '.join(missing_audio)}", "WARNING")
            self.log("Run autotq_setup.py to download all required files", "INFO")
        
        self.log("All requirements met", "SUCCESS")
        return True
    
    def auto_detect_device(self) -> Optional[str]:
        """Auto-detect a single AutoTQ/ESP32-S3 device"""
        self.log("Scanning for AutoTQ devices...", "PROGRESS")
        
        # Get available ports
        ports = self.firmware_programmer.list_available_ports()
        
        if not ports:
            self.log("No devices detected", "ERROR")
            current_platform = platform.system().lower()
            if current_platform == "linux":
                self.log("💡 Linux: Ensure device is connected and user has serial permissions", "INFO")
                self.log("💡 Add user to dialout group: sudo usermod -a -G dialout $USER", "INFO")
            elif current_platform == "windows":
                self.log("💡 Windows: Check Device Manager for COM ports", "INFO")
            return None
        
        # Filter for ESP32-S3 devices (marked with 🎯)
        esp32_ports = [port for port, desc in ports if '🎯' in desc]
        
        if len(esp32_ports) == 1:
            selected_port = esp32_ports[0]
            port_desc = next(desc for port, desc in ports if port == selected_port)
            self.log(f"Auto-detected ESP32-S3 device: {port_desc}", "SUCCESS")
            return selected_port
        elif len(esp32_ports) > 1:
            self.log(f"Multiple ESP32-S3 devices detected ({len(esp32_ports)})", "WARNING")
            self.log("Please disconnect extra devices or use manual selection", "INFO")
            return None
        else:
            # No ESP32-S3 devices, but other serial devices found
            self.log(f"Found {len(ports)} serial device(s) but none appear to be ESP32-S3", "WARNING")
            for port, desc in ports:
                self.log(f"  • {desc}", "INFO")
            return None
    
    def configure_production_audio_settings(self):
        """Configure optimized audio transfer settings for production mode"""
        # Use our proven fast settings from the optimized implementation
        self.device_programmer.set_transfer_speed("fast")
        
        self.log("🏭 Production audio settings: Optimized JavaScript-style transfer enabled", "SUCCESS")
    
    def program_device_complete(self, port: str = None, production_mode: bool = True) -> bool:
        """
        Complete device programming: firmware + audio files
        
        Args:
            port: Serial port (auto-detect if None)
            production_mode: Use fast production settings (default: True)
            
        Returns:
            True if both firmware and audio programming succeeded
        """
        start_time = time.time()
        
        # Auto-detect device if port not specified
        if not port:
            port = self.auto_detect_device()
            if not port:
                self.log("Device auto-detection failed", "ERROR")
                return False
        
        self.log("=" * 60, "INFO")
        self.log(f"🚀 STARTING COMPLETE DEVICE PROGRAMMING", "INFO")
        self.log(f"📟 Device: {port}", "INFO")
        if production_mode:
            self.log("🏭 Production mode: ENABLED (maximum speed)", "INFO")
        else:
            self.log("🐌 Development mode: Slower but with verification", "INFO")
        self.log("=" * 60, "INFO")
        
        # Step 1: Flash Firmware
        self.log("\n⚡ STEP 1: FIRMWARE PROGRAMMING", "FLASH")
        self.log("-" * 40, "INFO")
        
        # Test connection first
        if not self.firmware_programmer.test_esptool_connection(port):
            self.log(f"Cannot connect to ESP32-S3 on {port}", "ERROR")
            return False
        
        # Flash firmware with production optimizations
        firmware_success = self.firmware_programmer.program_device(
            port=port,
            erase_first=True,
            verify=not production_mode,  # Skip verification in production mode
            smart_erase=True,  # Always use smart erase for speed
            production_mode=production_mode
        )
        
        if not firmware_success:
            self.log("Firmware programming failed", "ERROR")
            return False
        
        # Wait for device to reboot and stabilize
        reboot_delay = 2 if production_mode else 5
        self.log(f"Waiting for device to reboot ({reboot_delay}s)...", "PROGRESS")
        time.sleep(reboot_delay)
        
        # Step 2: Transfer Audio Files
        self.log("\n🎵 STEP 2: AUDIO FILE TRANSFER", "AUDIO")
        self.log("-" * 40, "INFO")
        
        # Configure production audio settings if enabled
        if production_mode:
            self.configure_production_audio_settings()
        
        # Connect to device for audio transfer
        if not self.device_programmer.connect():
            # Try to set the port manually if auto-detection fails
            self.device_programmer.port_name = port
            if not self.device_programmer.connect():
                self.log("Cannot connect to device for audio transfer", "ERROR")
                self.log("Device may need more time to boot or may have firmware issues", "WARNING")
                return False
        
        # Transfer all required audio files
        successful, failed = self.device_programmer.transfer_required_files(skip_existing=False)
        
        # Disconnect from device
        self.device_programmer.disconnect()
        
        # Check audio transfer results
        audio_success = failed == 0
        if not audio_success:
            self.log(f"Audio transfer incomplete: {failed} files failed", "ERROR")
            return False
        
        # Success summary
        end_time = time.time()
        duration = end_time - start_time
        
        self.log("\n" + "=" * 60, "SUCCESS")
        self.log("🎉 DEVICE PROGRAMMING COMPLETED SUCCESSFULLY!", "SUCCESS")
        self.log(f"⏱️  Total time: {duration:.1f} seconds", "SUCCESS")
        self.log(f"📟 Device: {port}", "SUCCESS")
        fw_info = self.firmware_programmer.latest_firmware
        self.log(f"📦 Firmware: {fw_info['version']} programmed", "SUCCESS")
        self.log(f"🎵 Audio files: {successful} files transferred", "SUCCESS")
        if production_mode:
            self.log("🏭 Production mode optimizations used", "SUCCESS")
        self.log("=" * 60, "SUCCESS")
        
        return True
    
    def batch_program_devices(self, production_mode: bool = True) -> bool:
        """
        Program all detected ESP32-S3 devices in batch
        
        Args:
            production_mode: Use production optimizations for speed (default: True)
            
        Returns:
            True if all devices programmed successfully
        """
        self.log("🚀 BATCH MODE: Scanning for multiple devices...", "PROGRESS")
        
        # Get all ESP32-S3 devices
        ports = self.firmware_programmer.list_available_ports()
        esp32_ports = [port for port, desc in ports if '🎯' in desc]
        
        if not esp32_ports:
            self.log("No ESP32-S3 devices found for batch programming", "ERROR")
            return False
        
        self.log(f"Found {len(esp32_ports)} ESP32-S3 device(s) for batch programming", "SUCCESS")
        
        # Program each device
        results = {}
        for i, port in enumerate(esp32_ports, 1):
            self.log(f"\n🔄 BATCH: Programming device {i}/{len(esp32_ports)}: {port}", "PROGRESS")
            
            success = self.program_device_complete(port=port, production_mode=production_mode)
            results[port] = success
            
            if success:
                self.log(f"✅ Device {i} ({port}): Programming completed", "SUCCESS")
            else:
                self.log(f"❌ Device {i} ({port}): Programming failed", "ERROR")
                
                # Ask user if they want to continue
                if i < len(esp32_ports):
                    try:
                        continue_choice = input(f"❓ Device {port} failed. Continue with remaining devices? (y/n): ")
                        if continue_choice.lower() not in ['y', 'yes']:
                            self.log("Batch programming cancelled by user", "WARNING")
                            break
                    except KeyboardInterrupt:
                        self.log("Batch programming interrupted", "WARNING")
                        break
            
            # Small delay between devices
            if i < len(esp32_ports):
                time.sleep(1)  # Reduced delay in production
        
        # Summary
        successful = sum(1 for success in results.values() if success)
        total = len(results)
        
        self.log("\n" + "=" * 60, "INFO")
        self.log("📊 BATCH PROGRAMMING SUMMARY", "INFO")
        self.log(f"✅ Successful: {successful}/{total} devices", "SUCCESS" if successful == total else "WARNING")
        self.log(f"❌ Failed: {total - successful}/{total} devices", "ERROR" if successful < total else "INFO")
        self.log(f"📈 Success rate: {successful/total*100:.1f}%" if total > 0 else "0%", "INFO")
        self.log("=" * 60, "INFO")
        
        return successful == total
    
    def interactive_device_selection(self) -> Optional[str]:
        """Interactive device selection when multiple devices are found"""
        ports = self.firmware_programmer.list_available_ports()
        
        if not ports:
            self.log("No devices found", "ERROR")
            return None
        
        print("\n📟 Available devices:")
        esp32_ports = []
        other_ports = []
        
        for port, desc in ports:
            if '🎯' in desc:
                esp32_ports.append((port, desc))
            else:
                other_ports.append((port, desc))
        
        device_index = 1
        
        if esp32_ports:
            print("  ESP32-S3 devices (recommended):")
            for port, desc in esp32_ports:
                print(f"    {device_index}. {desc}")
                device_index += 1
        
        if other_ports:
            print("  Other USB serial devices:")
            for port, desc in other_ports:
                print(f"    {device_index}. {desc}")
                device_index += 1
        
        try:
            choice = input(f"\nEnter device number (1-{len(ports)}), or 'auto' for batch mode: ").strip()
            
            if choice.lower() == 'auto':
                return 'batch'
            
            index = int(choice) - 1
            if 0 <= index < len(ports):
                return ports[index][0]
            else:
                self.log("Invalid selection", "ERROR")
                return None
                
        except (ValueError, KeyboardInterrupt):
            self.log("Selection cancelled", "WARNING")
            return None
    
    def run_auto_program(self, production_mode: bool = True) -> bool:
        """
        Main auto-programming function
        
        Args:
            production_mode: Enable production optimizations (default: True)
            
        Returns:
            True if programming succeeded
        """
        self.log("🔍 AUTO-PROGRAMMING: Starting device detection...", "PROGRESS")
        
        # Try auto-detection first
        port = self.auto_detect_device()
        
        if port:
            # Single device detected - program it
            return self.program_device_complete(port=port, production_mode=production_mode)
        else:
            # Multiple devices or no devices - let user choose
            selected = self.interactive_device_selection()
            
            if not selected:
                return False
            elif selected == 'batch':
                return self.batch_program_devices(production_mode=production_mode)
            else:
                return self.program_device_complete(port=selected, production_mode=production_mode)


def main():
    """Command line interface"""
    parser = argparse.ArgumentParser(
        description="AutoTQ All-in-One Programmer - Flash firmware and transfer audio files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python autotq_programmer.py                    # Auto-detect and program device (PRODUCTION MODE - default)
  python autotq_programmer.py --dev              # Development mode (slower, with verification)
  python autotq_programmer.py --firmware-dir ./fw --audio-dir ./audio  # Custom directories
  python autotq_programmer.py --check-only       # Just check requirements
  python autotq_programmer.py --batch            # Program all detected devices

Workflow:
  1. Run: python autotq_setup.py                 # Download latest files (once)
  2. Run: python autotq_programmer.py            # Program your devices (FAST by default!)
  
Production mode features (DEFAULT):
  - Faster firmware flashing with compression
  - Skip firmware verification for speed  
  - Optimized audio transfer (256B writes, 1ms delay, 2KB chunks)
  - Minimal user interaction
  
Development mode features (--dev):
  - Firmware verification enabled
  - Slower but safer settings
  - More detailed logging
        """
    )
    
    parser.add_argument("--firmware-dir", default="firmware",
                       help="Directory containing firmware files (default: firmware)")
    parser.add_argument("--audio-dir", default="audio",
                       help="Directory containing audio files (default: audio)")
    parser.add_argument("--dev", action="store_true",
                       help="Enable development mode (slower, with verification)")
    parser.add_argument("--batch", action="store_true",
                       help="Program all detected ESP32-S3 devices")
    parser.add_argument("--check-only", action="store_true",
                       help="Only check requirements and available devices")
    
    # Keep --production for backward compatibility but make it default
    parser.add_argument("--production", action="store_true",
                       help="Enable production mode (DEFAULT - kept for compatibility)")
    
    args = parser.parse_args()
    
    # Production mode is default unless --dev is specified
    production_mode = not args.dev
    
    # Initialize programmer
    programmer = AutoTQProgrammer(
        firmware_dir=args.firmware_dir,
        audio_dir=args.audio_dir
    )
    
    try:
        if args.check_only:
            # Just check and list devices
            print("\n📋 REQUIREMENTS CHECK:")
            if programmer.check_requirements():
                print("✅ All requirements met")
            else:
                print("❌ Requirements not met - run autotq_setup.py first")
                sys.exit(1)
            
            print("\n📟 DEVICE SCAN:")
            port = programmer.auto_detect_device()
            if port:
                print(f"✅ Ready to program device on {port}")
            else:
                programmer.interactive_device_selection()
            
        elif args.batch:
            # Batch mode - program all devices
            if production_mode:
                print("🏭 BATCH PRODUCTION MODE: Programming all devices with optimized settings")
            else:
                print("🚀 BATCH DEVELOPMENT MODE: Programming all devices with verification")
            
            success = programmer.batch_program_devices(production_mode=production_mode)
            sys.exit(0 if success else 1)
            
        else:
            # Normal auto-programming mode
            if production_mode:
                print("🏭 PRODUCTION MODE: Fast programming with optimizations (DEFAULT)")
            else:
                print("🐌 DEVELOPMENT MODE: Slower programming with verification")
            
            success = programmer.run_auto_program(production_mode=production_mode)
            sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print("\n👋 Programming interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 