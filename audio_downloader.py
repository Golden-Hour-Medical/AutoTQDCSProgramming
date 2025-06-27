#!/usr/bin/env python3
"""
Audio Downloader System - JavaScript-Style Implementation
Transfers audio files from local storage to embedded devices via serial communication.
Modeled after the working JavaScript implementation.
"""

import os
import json
import time
import zlib
import serial
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any

# ANSI color codes for clear output formatting
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class AudioDownloader:
    """
    Audio file downloader system for embedded devices.
    JavaScript-style implementation with proper flow control.
    """
    
    # Required audio files for the system
    REQUIRED_AUDIO_FILES = [
        'tightenStrap.wav',
        'bleedingContinues.wav', 
        'pullStrapTighter.wav',
        'inflating.wav',
        'timeRemaining.wav',
        'reattachStrap.wav'
    ]
    
    # Serial communication parameters
    SERIAL_PARAMS = {
        'baudrate': 115200,
        'bytesize': serial.EIGHTBITS,
        'parity': serial.PARITY_NONE,
        'stopbits': serial.STOPBITS_ONE,
        'xonxoff': False,
        'rtscts': False,
        'dsrdtr': False,
        'timeout': 5
    }
    
    # Transfer parameters - Conservative JavaScript-style reliability
    CHUNK_SIZE = 2048  # Proven reliable chunk size 
    SEND_SIZE = 512    # Conservative piece size like JavaScript
    PIECE_DELAY = 0.002  # 2ms delay matching JavaScript timing
    
    def __init__(self, audio_folder: str = "audio"):
        """Initialize the audio downloader."""
        self.audio_folder = Path(audio_folder)
        self.serial_connection: Optional[serial.Serial] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.running = False
        self.device_responses = []
        self.response_lock = threading.Lock()
        
        # JavaScript-style logging
        self.log_message("🎵 Audio Downloader System Initialized")
        self.log_message(f"📂 Audio folder: {self.audio_folder.absolute()}")
        
    def log_message(self, message: str, level: str = "INFO"):
        """Log messages with timestamp like JavaScript."""
        timestamp = time.strftime("%H:%M:%S")
        if level == "ERROR":
            color = Colors.FAIL
            prefix = "❌"
        elif level == "WARN":
            color = Colors.WARNING  
            prefix = "⚠️"
        elif level == "SUCCESS":
            color = Colors.OKGREEN
            prefix = "✅"
        else:
            color = Colors.OKCYAN
            prefix = "📱"
            
        print(f"{color}[{timestamp}] {prefix} {message}{Colors.ENDC}")
        
    def calculate_crc32(self, data: bytes) -> int:
        """Calculate CRC32 checksum for data integrity verification."""
        return zlib.crc32(data) & 0xffffffff
        
    def discover_audio_files(self) -> Dict[str, Path]:
        """Discover available audio files like JavaScript fetchAvailableAudioFiles."""
        available_files = {}
        
        self.log_message("🔍 Fetching list of available audio files from local storage...")
        
        if not self.audio_folder.exists():
            self.log_message(f"Audio folder {self.audio_folder} does not exist!", "ERROR")
            return available_files
            
        for file_path in self.audio_folder.glob("*.wav"):
            available_files[file_path.name] = file_path
            file_size = file_path.stat().st_size
            self.log_message(f"📋 Found: {file_path.name} ({file_size:,} bytes)")
            
        self.log_message(f"✅ Successfully found {len(available_files)} audio files")
        return available_files
        
    def list_serial_ports(self) -> List[str]:
        """List available serial ports."""
        import serial.tools.list_ports
        
        ports = []
        self.log_message("🔌 Available serial ports:")
        
        for port in serial.tools.list_ports.comports():
            ports.append(port.device)
            self.log_message(f"  📱 {port.device} - {port.description}")
            
        return ports
        
    def connect_serial(self, port: str = None) -> bool:
        """Establish serial connection with the device like JavaScript."""
        if port is None:
            available_ports = self.list_serial_ports()
            if not available_ports:
                self.log_message("No serial ports found!", "ERROR")
                return False
                
            print(f"\n{Colors.WARNING}Please select a serial port:{Colors.ENDC}")
            for i, p in enumerate(available_ports):
                print(f"  {i+1}. {p}")
                
            try:
                choice = int(input("Enter port number: ")) - 1
                port = available_ports[choice]
            except (ValueError, IndexError):
                self.log_message("Invalid selection!", "ERROR")
                return False
                
        try:
            self.log_message(f"🔗 Connecting to {port}...")
            self.serial_connection = serial.Serial(port, **self.SERIAL_PARAMS)
            time.sleep(2)  # Allow connection to stabilize
            
            # Start reader thread like JavaScript
            self.running = True
            self.reader_thread = threading.Thread(target=self._serial_reader, daemon=True)
            self.reader_thread.start()
            
            self.log_message(f"✅ Connected to {port}")
            return True
            
        except serial.SerialException as e:
            self.log_message(f"Failed to connect to {port}: {e}", "ERROR")
            return False
            
    def _serial_reader(self):
        """Background thread to read serial data like JavaScript readLoop."""
        buffer = ""
        
        while self.running and self.serial_connection and self.serial_connection.is_open:
            try:
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            self._process_device_message(line)
                                
                time.sleep(0.01)
                
            except Exception as e:
                if self.running:
                    self.log_message(f"Serial read error: {e}", "ERROR")
                break
                
    def _process_device_message(self, line: str):
        """Process device messages like JavaScript processDeviceMessage."""
        try:
            response = json.loads(line)
            self.log_message(f"📱 Device: {json.dumps(response)}")
            
            with self.response_lock:
                self.device_responses.append({
                    'data': response,
                    'timestamp': time.time(),
                    'type': 'json'
                })
                
        except json.JSONDecodeError:
            # Non-JSON message - device debug/diagnostic messages
            if len(line) > 0 and not line.startswith('[Audio') and not line.startswith('[Timing]'):
                self.log_message(f"📱 Device: {line}")
                
                with self.response_lock:
                    self.device_responses.append({
                        'data': line,
                        'timestamp': time.time(),
                        'type': 'text'
                    })
                
    def send_command(self, command: Dict[str, Any]) -> bool:
        """Send JSON command to device like JavaScript sendCommand."""
        if not self.serial_connection or not self.serial_connection.is_open:
            self.log_message("No serial connection!", "ERROR")
            return False
            
        try:
            command_json = json.dumps(command) + '\n'
            self.serial_connection.write(command_json.encode('utf-8'))
            self.log_message(f"📤 Sent: {json.dumps(command)}")
            return True
        except Exception as e:
            self.log_message(f"Failed to send command: {e}", "ERROR")
            return False
            
    def wait_for_response(self, response_type: str, timeout: float = 15.0) -> Optional[Dict]:
        """Wait for specific device response like JavaScript."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.response_lock:
                # Check recent responses
                for response in self.device_responses[-10:]:
                    if response['type'] == 'json':
                        data = response['data']
                        
                        if response_type == 'binary_transfer_ready':
                            if (data.get('command') == 'download_file' and 
                                data.get('response') == 'binary_transfer_ready'):
                                return data
                                
                        elif response_type == 'chunk_received':
                            if data.get('response') == 'chunk_received':
                                return data
                                
                        elif response_type == 'binary_transfer_complete':
                            if data.get('response') == 'binary_transfer_complete':
                                return data
                                
                        elif response_type == 'binary_transfer_aborted':
                            if data.get('response') == 'binary_transfer_aborted':
                                return data
                                
            time.sleep(0.1)
            
        return None
        
    def send_file(self, file_data: bytes, filename: str) -> bool:
        """Send file to device like JavaScript sendFile."""
        file_size = len(file_data)
        file_crc = self.calculate_crc32(file_data)
        
        self.log_message(f"📤 Starting binary transfer of {filename}")
        self.log_message(f"📊 File size: {file_size} bytes ({file_size / 1024:.1f} KB)")
        self.log_message(f"🔐 CRC32: 0x{file_crc:08X}")
        
        # Step 1: Send initial download command like JavaScript
        start_command = {
            "command": "download_file",
            "filename": filename,
            "size": file_size,
            "chunk_size": self.CHUNK_SIZE,
            "crc32": file_crc
        }
        
        if not self.send_command(start_command):
            return False
            
        self.log_message("✅ Successfully sent download_file command to device")
        
        # Step 2: Wait for device ready signal like JavaScript
        self.log_message("⏳ Waiting for device ready signal...")
        ready_response = self.wait_for_response('binary_transfer_ready', timeout=10.0)
        
        if not ready_response:
            self.log_message("❌ Device did not signal ready for binary transfer!", "ERROR")
            return False
            
        self.log_message("✅ Device ready for binary transfer, sending data...")
        time.sleep(0.1)  # Small delay like JavaScript
        
        # Step 3: Send file in chunks like JavaScript
        sent_bytes = 0
        chunk_count = 0
        
        while sent_bytes < file_size:
            current_chunk_size = min(self.CHUNK_SIZE, file_size - sent_bytes)
            chunk_data = file_data[sent_bytes:sent_bytes + current_chunk_size]
            chunk_count += 1
            
            self.log_message(f"📦 Sending chunk {chunk_count}: {current_chunk_size} bytes")
            
            # Send chunk in small pieces like JavaScript to avoid buffer overflow
            for i in range(0, len(chunk_data), self.SEND_SIZE):
                piece = chunk_data[i:i + self.SEND_SIZE]
                try:
                    bytes_written = self.serial_connection.write(piece)
                    if self.PIECE_DELAY > 0:
                        time.sleep(self.PIECE_DELAY)
                except Exception as e:
                    self.log_message(f"Failed to send data piece: {e}", "ERROR")
                    return False
                    
            sent_bytes += current_chunk_size
            percent = round((sent_bytes / file_size) * 100)
            
            self.log_message(f"📊 Progress: {percent}% ({sent_bytes}/{file_size} bytes)")
            
            # Check for abort signals
            abort_response = self.wait_for_response('binary_transfer_aborted', timeout=0.1)
            if abort_response:
                reason = abort_response.get('reason', 'Unknown')
                self.log_message(f"❌ Transfer aborted by device: {reason}", "ERROR")
                return False
                
        self.log_message("✅ Binary transfer completed, waiting for device processing...")
        
        # Step 4: Wait for completion like JavaScript
        processing_time = max(2.0, min(8.0, file_size / 1024 * 0.1))  # 2-8 seconds based on file size
        self.log_message(f"⏳ Allowing {processing_time:.1f}s for device to process file...")
        
        # Check for both completion and abort responses
        start_time = time.time()
        while time.time() - start_time < processing_time + 5:
            completion_response = self.wait_for_response('binary_transfer_complete', timeout=0.5)
            if completion_response:
                break
                
            abort_response = self.wait_for_response('binary_transfer_aborted', timeout=0.5)
            if abort_response:
                reason = abort_response.get('reason', 'Unknown')
                self.log_message(f"❌ Transfer aborted by device: {reason}", "ERROR")
                return False
        
        if completion_response:
            crc_check = completion_response.get('crc_check', None)
            
            # Arduino may not send explicit CRC status but still indicate success
            if crc_check == 'passed':
                self.log_message("✅ CRC verification passed!")
                self.log_message(f"✅ Successfully transferred {filename}", "SUCCESS")
                return True
            elif crc_check == 'failed':
                self.log_message(f"❌ CRC verification failed: {crc_check}", "ERROR")
                return False
            else:
                # Arduino sent completion but no explicit CRC status - assume success
                self.log_message("✅ Transfer completed (CRC verification not reported by device)")
                self.log_message(f"✅ Successfully transferred {filename}", "SUCCESS")
                return True
        else:
            self.log_message("⚠️ No completion response received within timeout", "WARN")
            return False
            
    def download_all_files(self, available_files: Dict[str, Path]) -> Dict[str, bool]:
        """Download all available files like JavaScript downloadAllAudioFiles."""
        results = {}
        success_count = 0
        failure_count = 0
        
        self.log_message("📥 Starting download of all required audio files...")
        self.log_message("🔍 Will transfer files from local storage to device...")
        
        for i, filename in enumerate(self.REQUIRED_AUDIO_FILES):
            if filename in available_files:
                try:
                    self.log_message(f"📥 Processing {filename} ({i + 1}/{len(self.REQUIRED_AUDIO_FILES)})...")
                    
                    # Read file data
                    with open(available_files[filename], 'rb') as f:
                        file_data = f.read()
                        
                    if not file_data:
                        self.log_message(f"❌ No data available for {filename}", "ERROR")
                        results[filename] = False
                        failure_count += 1
                        continue
                        
                    # Send file to device
                    success = self.send_file(file_data, filename)
                    results[filename] = success
                    
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1
                        
                    # Add delay between files like JavaScript
                    if i < len(self.REQUIRED_AUDIO_FILES) - 1:
                        self.log_message("⏸️ Waiting 2 seconds before next file...")
                        time.sleep(2)
                        
                except Exception as e:
                    self.log_message(f"❌ Exception during transfer of {filename}: {e}", "ERROR")
                    results[filename] = False
                    failure_count += 1
            else:
                self.log_message(f"❌ {filename} not available locally!", "ERROR")
                results[filename] = False
                failure_count += 1
                
        # Final status like JavaScript
        final_message = f"Audio transfer complete: {success_count} succeeded, {failure_count} failed"
        self.log_message(final_message, "SUCCESS" if failure_count == 0 else "WARN")
        
        return results
        
    def request_file_list(self) -> bool:
        """Request list of files from device like JavaScript."""
        self.log_message("🔄 Requesting file list from device...")
        return self.send_command({"command": "list_files"})
        
    def request_missing_audio(self) -> bool:
        """Request list of missing audio files from device like JavaScript."""
        self.log_message("🔍 Checking for missing audio files...")
        return self.send_command({"command": "list_missing_audio"})
        
    def disconnect(self):
        """Clean up and disconnect from device."""
        self.running = False
        
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)
            
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.log_message("🔌 Serial connection closed")

def main():
    """Main program entry point with JavaScript-style interface."""
    print(f"{Colors.BOLD}{Colors.HEADER}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                    Audio Downloader System                   ║")
    print("║              JavaScript-Style Python Implementation          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")
    
    downloader = AudioDownloader()
    
    try:
        # Discover available audio files
        available_files = downloader.discover_audio_files()
        if not available_files:
            print(f"{Colors.FAIL}No audio files found! Please check the audio folder.{Colors.ENDC}")
            return
            
        # Connect to device
        if not downloader.connect_serial():
            print(f"{Colors.FAIL}Failed to establish serial connection!{Colors.ENDC}")
            return
            
        # Interactive menu like JavaScript interface
        while True:
            print(f"\n{Colors.WARNING}🎯 Available Operations:{Colors.ENDC}")
            print("1. 📥 Download all available files")
            print("2. 📁 Download specific file")
            print("3. 📋 Request device file list")
            print("4. 🔍 Request missing audio files")
            print("5. 🏓 Test device communication")
            print("6. 🚪 Exit")
            
            try:
                choice = input(f"\n{Colors.OKCYAN}Select operation (1-6): {Colors.ENDC}").strip()
                
                if choice == '1':
                    downloader.download_all_files(available_files)
                    
                elif choice == '2':
                    print(f"\n{Colors.WARNING}📂 Available files:{Colors.ENDC}")
                    file_list = list(available_files.keys())
                    for i, filename in enumerate(file_list):
                        print(f"  {i+1}. {filename}")
                        
                    try:
                        file_choice = int(input("Select file number: ")) - 1
                        if 0 <= file_choice < len(file_list):
                            filename = file_list[file_choice]
                            with open(available_files[filename], 'rb') as f:
                                file_data = f.read()
                            downloader.send_file(file_data, filename)
                        else:
                            print(f"{Colors.FAIL}Invalid file selection!{Colors.ENDC}")
                    except ValueError:
                        print(f"{Colors.FAIL}Invalid input!{Colors.ENDC}")
                        
                elif choice == '3':
                    downloader.request_file_list()
                    time.sleep(2)  # Allow time for response
                    
                elif choice == '4':
                    downloader.request_missing_audio()
                    time.sleep(2)  # Allow time for response
                    
                elif choice == '5':
                    test_command = {"command": "ping", "timestamp": int(time.time())}
                    downloader.send_command(test_command)
                    time.sleep(1)
                    
                elif choice == '6':
                    break
                    
                else:
                    print(f"{Colors.FAIL}Invalid choice!{Colors.ENDC}")
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.WARNING}Operation interrupted by user.{Colors.ENDC}")
                break
            except Exception as e:
                print(f"{Colors.FAIL}Error: {e}{Colors.ENDC}")
                
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Program interrupted by user.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}Unexpected error: {e}{Colors.ENDC}")
    finally:
        downloader.disconnect()
        print(f"{Colors.HEADER}Program terminated.{Colors.ENDC}")

if __name__ == "__main__":
    main() 