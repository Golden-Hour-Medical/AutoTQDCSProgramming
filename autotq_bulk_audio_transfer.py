#!/usr/bin/env python3
"""
AutoTQ Bulk Audio Transfer Tool

Detects multiple AutoTQ devices connected via USB and transfers audio files
to all devices simultaneously using parallel threads.
"""

import sys
import time
import argparse
import threading
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

try:
    from autotq_device_programmer import AutoTQDeviceProgrammer
    from autotq_firmware_programmer import AutoTQFirmwareProgrammer
except ImportError as e:
    print(f"❌ Error: Required modules not found: {e}")
    sys.exit(1)


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class DeviceTransferResult:
    """Store result of audio transfer for a device"""
    def __init__(self, port: str):
        self.port = port
        self.success = False
        self.successful_files = 0
        self.failed_files = 0
        self.duration_seconds = 0.0
        self.error_message = None
        self.device_info = {}


def log(message: str, color: str = ""):
    """Print message with optional color and timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    if color:
        print(f"{color}[{timestamp}] {message}{Colors.ENDC}", flush=True)
    else:
        print(f"[{timestamp}] {message}", flush=True)


def list_esp_ports() -> List[Tuple[str, str]]:
    """
    List all connected ESP32/AutoTQ devices.
    Returns list of (port, description) tuples.
    """
    try:
        prog = AutoTQFirmwareProgrammer()
        ports = prog.list_available_ports()
        # Filter for ESP/AutoTQ devices (marked with 🎯)
        esp_ports = [(p, desc) for p, desc in ports if '🎯' in desc]
        return esp_ports
    except Exception as e:
        log(f"Error listing ports: {e}", Colors.FAIL)
        return []


def transfer_to_device(port: str, audio_dir: str, transfer_speed: str = "fast") -> DeviceTransferResult:
    """
    Transfer audio files to a single device.
    This function runs in a separate thread for each device.
    """
    result = DeviceTransferResult(port)
    start_time = time.perf_counter()
    
    try:
        log(f"[{port}] Starting audio transfer...", Colors.OKCYAN)
        
        # Create programmer instance for this device
        programmer = AutoTQDeviceProgrammer(port=port, audio_dir=audio_dir)
        
        # Set transfer speed
        try:
            programmer.set_transfer_speed(transfer_speed)
        except Exception:
            pass  # Use default if set_transfer_speed fails
        
        # Connect to device
        if not programmer.connect():
            result.error_message = "Failed to connect to device"
            log(f"[{port}] ❌ Failed to connect", Colors.FAIL)
            return result
        
        # Get device info if available
        try:
            result.device_info = programmer.device_info or {}
        except Exception:
            pass
        
        # Transfer files
        try:
            successful, failed = programmer.transfer_required_files(skip_existing=False)
            result.successful_files = successful
            result.failed_files = failed
            result.success = (failed == 0)
            
            if result.success:
                log(f"[{port}] ✅ Transfer complete - {successful} files transferred", Colors.OKGREEN)
            else:
                log(f"[{port}] ⚠️  Transfer partial - {successful} succeeded, {failed} failed", Colors.WARNING)
                result.error_message = f"{failed} files failed"
        except Exception as e:
            result.error_message = f"Transfer error: {e}"
            log(f"[{port}] ❌ Transfer error: {e}", Colors.FAIL)
        finally:
            # Disconnect
            try:
                programmer.disconnect()
            except Exception:
                pass
    
    except Exception as e:
        result.error_message = f"Unexpected error: {e}"
        log(f"[{port}] ❌ Unexpected error: {e}", Colors.FAIL)
    
    finally:
        result.duration_seconds = time.perf_counter() - start_time
    
    return result


def transfer_to_all_devices(ports: List[str], audio_dir: str, transfer_speed: str = "fast") -> List[DeviceTransferResult]:
    """
    Transfer audio files to multiple devices in parallel using threads.
    """
    if not ports:
        log("No devices to transfer to", Colors.WARNING)
        return []
    
    log(f"Starting parallel transfer to {len(ports)} device(s)...", Colors.HEADER)
    
    # Store results from each thread
    results = {}
    threads = []
    
    def worker(port: str):
        """Worker function for thread"""
        result = transfer_to_device(port, audio_dir, transfer_speed)
        results[port] = result
    
    # Start a thread for each device
    for port in ports:
        thread = threading.Thread(target=worker, args=(port,), daemon=True)
        thread.start()
        threads.append(thread)
        time.sleep(0.2)  # Small delay between thread starts
    
    # Wait for all threads to complete
    log(f"Waiting for all {len(threads)} transfers to complete...", Colors.OKBLUE)
    for thread in threads:
        thread.join()
    
    # Return results in the same order as input ports
    return [results[port] for port in ports if port in results]


def print_summary(results: List[DeviceTransferResult], total_duration: float):
    """Print summary of all transfers"""
    print("\n" + "="*70)
    print(f"{Colors.BOLD}TRANSFER SUMMARY{Colors.ENDC}")
    print("="*70)
    
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    
    for i, result in enumerate(results, 1):
        status_icon = "✅" if result.success else "❌"
        color = Colors.OKGREEN if result.success else Colors.FAIL
        
        print(f"\n{color}{status_icon} Device {i}: {result.port}{Colors.ENDC}")
        print(f"   Duration: {result.duration_seconds:.1f}s")
        print(f"   Files: {result.successful_files} succeeded, {result.failed_files} failed")
        
        if result.error_message:
            print(f"   Error: {result.error_message}")
        
        # Show device info if available
        if result.device_info:
            mac = result.device_info.get('mac', 'N/A')
            fw = result.device_info.get('firmware_version', 'N/A')
            print(f"   Device: MAC={mac}, FW={fw}")
    
    print("\n" + "="*70)
    print(f"{Colors.BOLD}OVERALL RESULTS{Colors.ENDC}")
    print("="*70)
    print(f"Total devices: {len(results)}")
    print(f"{Colors.OKGREEN}Successful: {successful}{Colors.ENDC}")
    if failed > 0:
        print(f"{Colors.FAIL}Failed: {failed}{Colors.ENDC}")
    print(f"Total time: {total_duration:.1f}s")
    
    # Calculate average time per device
    avg_time = sum(r.duration_seconds for r in results) / len(results) if results else 0
    print(f"Average time per device: {avg_time:.1f}s")
    print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="AutoTQ Bulk Audio Transfer - Transfer audio files to multiple devices simultaneously",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Auto-detect devices and transfer
  %(prog)s --audio-dir ./audio      # Use custom audio directory
  %(prog)s --speed ultrafast        # Use fastest transfer speed
  %(prog)s --no-prompt              # Don't wait for user confirmation
        """
    )
    
    parser.add_argument(
        '--audio-dir',
        default='audio',
        help='Directory containing audio files (default: ./audio)'
    )
    
    parser.add_argument(
        '--speed',
        choices=['slow', 'normal', 'fast', 'ultrafast'],
        default='fast',
        help='Transfer speed (default: fast)'
    )
    
    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='Skip confirmation prompt and start immediately'
    )
    
    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Continuous mode - keep running and detect new devices'
    )
    
    args = parser.parse_args()
    
    # Verify audio directory exists
    audio_path = Path(args.audio_dir)
    if not audio_path.exists():
        log(f"❌ Audio directory not found: {audio_path.absolute()}", Colors.FAIL)
        return 1
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}AutoTQ Bulk Audio Transfer Tool{Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*70}{Colors.ENDC}\n")
    print(f"Audio directory: {audio_path.absolute()}")
    print(f"Transfer speed: {args.speed}\n")
    
    cycle_count = 0
    
    while True:
        cycle_count += 1
        if args.continuous and cycle_count > 1:
            print(f"\n{Colors.HEADER}--- Cycle {cycle_count} ---{Colors.ENDC}\n")
        
        # Detect devices
        log("Detecting connected AutoTQ devices...", Colors.OKBLUE)
        detected_ports = list_esp_ports()
        
        if not detected_ports:
            log("❌ No AutoTQ devices detected!", Colors.FAIL)
            log("Please plug in one or more AutoTQ devices via USB", Colors.WARNING)
            
            if args.continuous:
                log("Waiting 5 seconds before next scan...", Colors.OKBLUE)
                time.sleep(5)
                continue
            else:
                try:
                    input("\nPress Enter to retry or Ctrl+C to exit... ")
                    continue
                except KeyboardInterrupt:
                    print("\n")
                    return 1
        
        # Display detected devices
        log(f"✅ Found {len(detected_ports)} device(s):", Colors.OKGREEN)
        for i, (port, desc) in enumerate(detected_ports, 1):
            print(f"   {i}. {port} - {desc}")
        
        # Prompt for confirmation unless --no-prompt
        if not args.no_prompt and not args.continuous:
            try:
                response = input(f"\n{Colors.BOLD}Transfer audio to all {len(detected_ports)} device(s)? (Enter/y to proceed, n to cancel): {Colors.ENDC}").strip().lower()
                if response and response not in ['y', 'yes', '']:
                    log("Transfer cancelled by user", Colors.WARNING)
                    return 0
            except KeyboardInterrupt:
                print("\n")
                log("Transfer cancelled by user", Colors.WARNING)
                return 0
        
        print()  # Blank line before transfer starts
        
        # Start parallel transfer
        start_time = time.perf_counter()
        ports_only = [port for port, _ in detected_ports]
        
        results = transfer_to_all_devices(
            ports_only,
            str(audio_path),
            args.speed
        )
        
        total_duration = time.perf_counter() - start_time
        
        # Print summary
        print_summary(results, total_duration)
        
        # Check if we should continue
        if args.continuous:
            log("Remove completed devices and plug in new ones...", Colors.OKBLUE)
            log("Waiting 10 seconds before next scan...", Colors.OKBLUE)
            time.sleep(10)
        else:
            # Ask if user wants to do another batch
            try:
                response = input(f"{Colors.BOLD}Transfer to another batch? (Enter/y to continue, n to exit): {Colors.ENDC}").strip().lower()
                if response and response not in ['y', 'yes', '']:
                    break
            except KeyboardInterrupt:
                print("\n")
                break
    
    log("Bulk audio transfer complete!", Colors.OKGREEN)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Transfer interrupted by user{Colors.ENDC}")
        sys.exit(130)

