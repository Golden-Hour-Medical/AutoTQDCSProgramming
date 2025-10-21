#!/usr/bin/env python3
"""
ESPEC Chamber Humidity Command Tester
Quick diagnostic to see which humidity commands your chamber supports.
"""
import sys
import gpib

def test_humidity_commands():
    print("=" * 70)
    print("  ESPEC Chamber Humidity Command Tester")
    print("=" * 70)
    print()
    
    try:
        print("Connecting to chamber...")
        inst = gpib.open_chamber()
        print("✅ Connected!")
        print()
        
        # Get chamber info
        rom = gpib.q(inst, "ROM?")
        chamber_type = gpib.q(inst, "TYPE?")
        mode = gpib.q(inst, "MODE?")
        
        print(f"Chamber Info:")
        print(f"  ROM:  {rom}")
        print(f"  TYPE: {chamber_type}")
        print(f"  MODE: {mode}")
        print()
        
        # Test 1: Check if chamber has humidity capability
        print("-" * 70)
        print("Test 1: Check humidity capability")
        print("-" * 70)
        try:
            r = gpib.q(inst, "CONSTANT SET?,HUMI")
            print(f"  CONSTANT SET?,HUMI -> '{r}'")
            if r and not r.startswith("NA:") and not r.startswith("ER:"):
                print("  ✅ Chamber has humidity control capability")
                has_humidity = True
            else:
                print("  ❌ Chamber does not have humidity control (temperature-only)")
                has_humidity = False
        except Exception as e:
            print(f"  ❌ Error: {e}")
            has_humidity = False
        print()
        
        if not has_humidity:
            print("Your chamber is temperature-only. No humidity commands needed!")
            print("You can safely use --no-humidity mode.")
            inst.close()
            return
        
        # Test 2: Try different OFF commands
        print("-" * 70)
        print("Test 2: Try turning humidity OFF (various commands)")
        print("-" * 70)
        
        commands = [
            "HUA, OFF",
            "HUMI, OFF",
            "CONSTANT SET, HUMI, OFF",
        ]
        
        working_command = None
        for cmd in commands:
            print(f"  Trying: {cmd}")
            r = gpib.tx(inst, cmd)
            print(f"    Response: '{r}'")
            if gpib.is_ok(r) or r == "":
                print(f"    ✅ This command appears to work!")
                working_command = cmd
                break
            else:
                print(f"    ❌ Command rejected or failed")
        
        print()
        
        if working_command:
            print("=" * 70)
            print(f"✅ SUCCESS! Your chamber accepts: {working_command}")
            print("=" * 70)
        else:
            print("=" * 70)
            print("⚠️  None of the standard humidity OFF commands worked.")
            print("Your chamber may use a different command syntax.")
            print("Check your chamber's GPIB command manual for the correct syntax.")
            print("=" * 70)
        
        inst.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        result = test_humidity_commands()
        print()
        input("Press ENTER to exit...")
        sys.exit(result)
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        sys.exit(1)

