#!/usr/bin/env python3
"""
Arduino Binary Transfer Debug Tool
Helps diagnose issues with the Arduino binary transfer protocol.
"""

import serial
import json
import time
import threading
from pathlib import Path

class ArduinoDebugger:
    def __init__(self, port):
        self.port = port
        self.serial_connection = None
        self.running = False
        self.reader_thread = None
        
    def connect(self):
        try:
            self.serial_connection = serial.Serial(
                self.port, 
                baudrate=115200,
                timeout=5
            )
            time.sleep(2)
            
            self.running = True
            self.reader_thread = threading.Thread(target=self._reader, daemon=True)
            self.reader_thread.start()
            
            print(f"✅ Connected to {self.port}")
            return True
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            return False
            
    def _reader(self):
        buffer = ""
        while self.running and self.serial_connection and self.serial_connection.is_open:
            try:
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[{timestamp}] ARDUINO: {line}")
                            
                time.sleep(0.01)
            except Exception as e:
                if self.running:
                    print(f"Read error: {e}")
                break
                
    def send_command(self, command):
        if not self.serial_connection or not self.serial_connection.is_open:
            print("❌ No connection!")
            return False
            
        try:
            command_json = json.dumps(command) + '\n'
            self.serial_connection.write(command_json.encode('utf-8'))
            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] SENT: {json.dumps(command)}")
            return True
        except Exception as e:
            print(f"❌ Send failed: {e}")
            return False
            
    def test_small_transfer(self):
        """Test transfer with very small file to isolate the issue."""
        print("\n🧪 Testing small binary transfer...")
        
        # Create 100 bytes of test data
        test_data = b"A" * 100
        filename = "test_small.bin"
        
        # Send download command
        command = {
            "command": "download_file",
            "filename": filename,
            "size": len(test_data),
            "chunk_size": 64,  # Very small chunk
            "crc32": 0x12345678  # Dummy CRC
        }
        
        if not self.send_command(command):
            return False
            
        print("⏳ Waiting 3 seconds for Arduino response...")
        time.sleep(3)
        
        print(f"📤 Sending {len(test_data)} bytes of test data...")
        try:
            bytes_written = self.serial_connection.write(test_data)
            print(f"✅ Wrote {bytes_written} bytes to serial")
        except Exception as e:
            print(f"❌ Failed to write data: {e}")
            return False
            
        print("⏳ Waiting 5 seconds for completion...")
        time.sleep(5)
        
        return True
        
    def disconnect(self):
        self.running = False
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            print("🔌 Disconnected")

def main():
    print("🔧 Arduino Binary Transfer Debug Tool")
    print("=" * 50)
    
    # List available ports
    import serial.tools.list_ports
    ports = [port.device for port in serial.tools.list_ports.comports()]
    
    if not ports:
        print("❌ No serial ports found!")
        return
        
    print("Available ports:")
    for i, port in enumerate(ports):
        print(f"  {i+1}. {port}")
        
    try:
        choice = int(input("\nSelect port: ")) - 1
        if 0 <= choice < len(ports):
            selected_port = ports[choice]
        else:
            print("❌ Invalid selection!")
            return
    except ValueError:
        print("❌ Invalid input!")
        return
        
    debugger = ArduinoDebugger(selected_port)
    
    try:
        if debugger.connect():
            print("\n🎯 Options:")
            print("1. Test small binary transfer")
            print("2. Send ping command")
            print("3. Just monitor Arduino output")
            
            choice = input("\nSelect test (1-3): ").strip()
            
            if choice == '1':
                debugger.test_small_transfer()
            elif choice == '2':
                debugger.send_command({"command": "ping", "timestamp": int(time.time())})
                time.sleep(2)
            elif choice == '3':
                print("📡 Monitoring Arduino output (Ctrl+C to stop)...")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
            else:
                print("❌ Invalid choice!")
                
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    finally:
        debugger.disconnect()

if __name__ == "__main__":
    main() 