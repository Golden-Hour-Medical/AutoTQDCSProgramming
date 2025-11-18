#!/usr/bin/env python3
"""
Quick Port Checker - Diagnose COM port issues
Helps identify what's holding a serial port on Windows
"""

import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("❌ pyserial not installed. Install with: pip install pyserial")
    sys.exit(1)


def check_port(port_name):
    """Check if a port is accessible and try to diagnose issues"""
    print(f"\n🔍 Checking port: {port_name}")
    print("=" * 50)
    
    # Check if port exists in system
    ports = list(serial.tools.list_ports.comports())
    port_info = None
    for p in ports:
        if p.device == port_name:
            port_info = p
            break
    
    if not port_info:
        print(f"❌ Port {port_name} not found in system")
        print(f"\n📋 Available ports:")
        for p in ports:
            print(f"   {p.device}: {p.description}")
        return False
    
    print(f"✅ Port exists in system")
    print(f"   Description: {port_info.description}")
    if port_info.manufacturer:
        print(f"   Manufacturer: {port_info.manufacturer}")
    if port_info.vid and port_info.pid:
        print(f"   VID:PID: {port_info.vid:04X}:{port_info.pid:04X}")
    
    # Try to open the port
    print(f"\n🔌 Attempting to open port...")
    for attempt in range(3):
        try:
            ser = serial.Serial()
            ser.port = port_name
            ser.baudrate = 115200
            ser.timeout = 1
            ser.write_timeout = 1
            
            # Disable control lines
            try:
                ser.dtr = False
                ser.rts = False
            except:
                pass
            
            ser.open()
            print(f"✅ Successfully opened port (attempt {attempt + 1})")
            
            # Check port status
            print(f"\n📊 Port Status:")
            print(f"   DTR: {ser.dtr}")
            print(f"   RTS: {ser.rts}")
            print(f"   CTS: {ser.cts}")
            print(f"   DSR: {ser.dsr}")
            print(f"   RI: {ser.ri}")
            print(f"   CD: {ser.cd}")
            
            # Try to read/write
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                print(f"✅ Buffers cleared successfully")
            except Exception as e:
                print(f"⚠️ Buffer clear failed: {e}")
            
            ser.close()
            print(f"✅ Port closed successfully")
            
            print(f"\n✅ Port {port_name} is ACCESSIBLE and WORKING")
            return True
            
        except serial.SerialException as e:
            error_str = str(e)
            print(f"❌ Attempt {attempt + 1} failed: {type(e).__name__}")
            print(f"   {error_str}")
            
            if "ClearCommError" in error_str or "PermissionError" in error_str:
                print(f"\n🔍 Diagnosed Issue: Port is held by another process or has stale handles")
                print(f"   This is the EXACT error you're seeing in unified production!")
                print(f"\n💡 Solutions:")
                print(f"   1. Close ALL programs that might use COM ports")
                print(f"   2. Check Device Manager for issues with the port")
                print(f"   3. Unplug the device, wait 3 seconds, plug it back in")
                print(f"   4. If persistent, reboot your computer")
            elif "Access is denied" in error_str:
                print(f"\n🔍 Diagnosed Issue: Permission denied")
                print(f"   Another program is actively using this port")
            elif "FileNotFoundError" in error_str:
                print(f"\n🔍 Diagnosed Issue: Port disappeared")
                print(f"   The device may have disconnected")
            
            if attempt < 2:
                print(f"⏳ Waiting 1 second before retry...")
                time.sleep(1)
        
        except Exception as e:
            print(f"❌ Unexpected error: {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(1)
    
    print(f"\n❌ Port {port_name} is NOT ACCESSIBLE")
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_port.py COMxx")
        print("Example: python check_port.py COM229")
        print("\nOr run without arguments to check all ESP32-like ports:")
        
        # Auto-detect ESP32 ports
        print("\n🔍 Auto-detecting ESP32 devices...")
        ports = list(serial.tools.list_ports.comports())
        esp_ports = []
        for p in ports:
            desc_lower = p.description.lower()
            if any(kw in desc_lower for kw in ['esp32', 'usb serial', 'cdc', 'ch340', 'cp210', 'ft232']):
                esp_ports.append(p.device)
                print(f"   Found: {p.device} - {p.description}")
        
        if esp_ports:
            print(f"\n✅ Found {len(esp_ports)} potential ESP32 port(s)")
            for port in esp_ports:
                check_port(port)
        else:
            print("❌ No ESP32-like devices found")
        
        return 0
    
    port = sys.argv[1]
    success = check_port(port)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

