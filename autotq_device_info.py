#!/usr/bin/env python3
"""
AutoTQ Device Info Display
Simple utility to show MAC addresses and firmware versions of connected AutoTQ devices.
"""
import sys
from autotq_quick_check import (
    _list_esp_ports,
    read_mac_via_status,
    read_mac,
    read_device_info_via_serial,
    read_fw_version_via_serial,
)


def main():
    print("=" * 70)
    print("  AutoTQ Device Information")
    print("=" * 70)
    print()
    print("Scanning for connected AutoTQ devices...")
    print()
    
    ports = _list_esp_ports()
    
    if not ports:
        print("❌ No AutoTQ devices found.")
        print()
        print("Make sure devices are:")
        print("  - Plugged into USB ports")
        print("  - Powered on")
        print("  - Drivers are installed")
        print()
    else:
        print(f"✅ Found {len(ports)} device(s):\n")
        
        for idx, port in enumerate(ports, start=1):
            print(f"Device #{idx}: {port}")
            print("-" * 70)
            
            # Try to read MAC address
            mac = read_mac_via_status(port) or read_mac(port)
            if mac:
                print(f"  MAC Address:      {mac}")
            else:
                print(f"  MAC Address:      (unable to read)")
            
            # Try to read device info
            dinfo = read_device_info_via_serial(port) or {}
            fw = dinfo.get("firmware_version") or read_fw_version_via_serial(port)
            hw = dinfo.get("hardware_version")
            
            if fw:
                print(f"  Firmware Version: {fw}")
            else:
                print(f"  Firmware Version: (unable to read)")
            
            if hw:
                print(f"  Hardware Version: {hw}")
            
            print()
    
    print("=" * 70)
    print()
    input("Press ENTER to exit...")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        input("Press ENTER to exit...")
        sys.exit(1)

