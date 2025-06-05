# AutoTQ Manufacturer Portal API Reference

## Overview
This document describes the communication protocols, API endpoints, and procedures used in the AutoTQ Manufacturer Portal for device management, firmware flashing, and audio file transfers.

## Device Communication Protocol

### Serial Connection
- **Interface**: Web Serial API (USB)
- **Baud Rate**: 115200
- **Device Type**: ESP32-based AutoTQ devices
- **Text Encoding**: UTF-8
- **Line Termination**: `\n` (newline)

### Connection Procedure
1. **Request Port**: Use `navigator.serial.requestPort()` to select device
2. **Open Port**: Configure with 115200 baud rate
3. **Stabilization**: Wait 2000ms for device to stabilize after connection
4. **Device Info**: Send commands to retrieve MAC address and status
5. **Retry Logic**: Up to 3 attempts with 1000ms delays between retries

### Serial Buffer Management
- **Incoming Buffer**: UTF-8 text decoder with stream processing
- **Line Processing**: Split by `\n` and process complete lines
- **Buffer Limits**: Process max 50 lines per call to prevent infinite loops
- **Message Filtering**: Filter verbose debug messages (AudioTask, I2S config, etc.)

### Connection Termination
1. Cancel reader stream
2. Release reader lock
3. Release writer lock  
4. Close serial port
5. Set connection flags to false
6. Log disconnection audit event

## Device Commands

### Command Format
All commands are sent as JSON objects terminated with `\n`:
```json
{"command": "command_name", "parameter": "value"}\n
```

### Available Commands

#### 1. Get MAC Address
```json
{"command": "wifi_get_mac"}
```
**Response:**
```json
{"command": "wifi_get_mac", "mac": "AA:BB:CC:DD:EE:FF"}
```

#### 2. Get Device Status
```json
{"command": "get_status"}
```
**Response:** Device-specific status information

#### 3. List Files on Device
```json
{"command": "list_files"}
```
**Response:**
```json
{"command": "list_files", "response": "file_list", "files": ["file1.wav", "file2.wav"]}
```

#### 4. List Missing Audio Files
```json
{"command": "list_missing_audio"}
```
**Response:** List of missing required audio files

#### 5. File Transfer Initialization
```json
{
  "command": "download_file",
  "filename": "example.wav",
  "size": 12345,
  "chunk_size": 1024,
  "crc": 3735928559
}
```

## Audio File Transfer Protocol

### Required Audio Files
- `tightenStrap.wav`
- `bleedingContinues.wav`
- `pullStrapTighter.wav`
- `inflating.wav`
- `timeRemaining.wav`

### Transfer Process
1. **Initialize Transfer**: Send `download_file` command with file metadata
2. **CRC32 Calculation**: Calculate CRC32 checksum for integrity verification
3. **Chunked Transfer**: Send file in 1024-byte chunks
4. **Write Timing**: 64-byte writes with 2ms delays between writes
5. **Progress Tracking**: Update progress bar during transfer
6. **Completion**: Wait for device confirmation
7. **Cleanup**: 500ms pause between files

### Transfer Modes
- **All Required Files**: Download all 5 required audio files
- **Missing Files Only**: Download only files not present on device
- **Single File**: Transfer individual audio file

## Backend API Endpoints

### Authentication
**Base URL**: Determined by `window.location.origin`
**Authentication**: Bearer token in `Authorization` header
**Token Storage**: `localStorage.getItem('mfg_token')`

#### Login Endpoint
- **Redirect**: `/static/manufacturer_login.html` (if no token)

#### Logout
- **Method**: POST
- **Endpoint**: `/auth/logout`
- **Headers**: `Authorization: Bearer {token}`

### User Management
#### Get User Profile
- **Method**: GET
- **Endpoint**: `/users/me`
- **Headers**: `Authorization: Bearer {token}`
- **Response**: User profile data

### Audio File Management
#### List Audio Files
- **Method**: GET
- **Endpoint**: `/audio/files`
- **Headers**: `Authorization: Bearer {token}`
- **Response**: Array of available audio filenames

#### Download Audio File
- **Method**: GET
- **Endpoint**: `/audio/file/{filename}`
- **Headers**: `Authorization: Bearer {token}`
- **Response**: Binary audio file data (ArrayBuffer)

### Firmware Management
#### Get Firmware Versions
- **Method**: GET
- **Endpoint**: `/firmware/versions?limit=1&skip=0`
- **Headers**: `Authorization: Bearer {token}`
- **Response**: Array of firmware version objects

#### Get Firmware Manifest (ESP Web Tools)
- **Method**: GET
- **Endpoint**: `/firmware/versions/{id}/manifest`
- **Headers**: `Authorization: Bearer {token}`
- **Response**: ESP Web Tools manifest for firmware flashing

### Audit Logging
#### Log Manufacturer Action
- **Method**: POST
- **Endpoint**: `/audit/manufacturer-action`
- **Headers**: 
  - `Content-Type: application/json`
  - `Authorization: Bearer {token}`
- **Body**:
```json
{
  "action_type": "ACTION_TYPE",
  "description": "Human readable description",
  "details_after": {
    "timestamp": "ISO_8601_timestamp",
    "user_agent": "browser_user_agent",
    "additional_details": "..."
  },
  "status": "SUCCESS"
}
```

## Firmware Flashing

### ESP Web Tools Integration
- **Component**: `esp-web-install-button`
- **CDN**: `https://unpkg.com/esp-web-tools@10/dist/web/install-button.js`
- **Manifest**: Retrieved from `/firmware/versions/{id}/manifest`
- **Browser Requirements**: Chrome or Edge (Web Serial API support)

### Flashing Events
- `installation-complete`: Firmware successfully flashed
- `installation-error`: Flashing failed
- `install-started`: Flashing process initiated
- `install-finished`: Flashing process completed

## Audit Event Types

### Device Connection Events
- `MANUFACTURER_DEVICE_CONNECTED`: Device successfully connected
- `MANUFACTURER_DEVICE_DISCONNECTED`: Device disconnected
- `MANUFACTURER_DEVICE_CONNECTION_FAILED`: Connection attempt failed
- `MANUFACTURER_DEVICE_CONNECTION_CANCELLED`: User cancelled connection

### File Transfer Events
- `MANUFACTURER_FILE_TRANSFER_SUCCESS`: Single file transfer completed
- `MANUFACTURER_FILE_TRANSFER_FAILED`: Single file transfer failed
- `MANUFACTURER_BATCH_TRANSFER_STARTED`: Batch transfer initiated
- `MANUFACTURER_BATCH_TRANSFER_COMPLETED`: Batch transfer finished
- `MANUFACTURER_BATCH_TRANSFER_FAILED`: Batch transfer failed
- `MANUFACTURER_SINGLE_FILE_TRANSFER_STARTED`: Single file transfer started
- `MANUFACTURER_SINGLE_FILE_TRANSFER_ERROR`: Single file transfer error

## Timing Specifications

### Connection Timing
- **Port Opening**: Immediate
- **Stabilization Wait**: 2000ms after connection
- **Command Retry Interval**: 1000ms between attempts
- **Max Retry Attempts**: 3

### Transfer Timing
- **Write Size**: 64 bytes per write operation
- **Write Delay**: 2ms between writes
- **Post-Transfer Pause**: 500ms between files
- **Progress Update**: Real-time during transfer

### Response Timeouts
- **Command Response**: 1000ms typical wait
- **File List Response**: Variable based on device
- **Transfer Confirmation**: Variable based on file size

## Error Handling

### Connection Errors
- `NotFoundError`: User cancelled port selection
- `NetworkError`: Device disconnected or communication lost
- Device reset/reboot during operation

### Transfer Errors
- File fetch failures from server
- Device communication timeouts
- CRC checksum mismatches
- Partial transfer failures

### Recovery Procedures
- Automatic retry for connection commands
- Graceful degradation for partial transfers
- Audit logging for all failure scenarios
- User notification via alerts and logs

## Security Considerations

### Authentication
- JWT Bearer tokens for all API calls
- Token stored in localStorage
- Automatic redirect on missing/invalid tokens

### Device Communication
- USB-only communication (no network exposure)
- CRC32 integrity verification for file transfers
- Audit logging for all device interactions

### Data Privacy
- MAC address tracking for audit purposes
- User agent and browser information logging
- Connection duration and timing tracking

## Browser Compatibility

### Required APIs
- **Web Serial API**: Chrome 89+, Edge 89+
- **ES6 Modules**: Modern browsers
- **ArrayBuffer/Uint8Array**: Universal support
- **TextEncoder/TextDecoder**: Universal support

### Fallback Handling
- Graceful degradation for unsupported browsers
- Clear error messages for missing API support
- ESP Web Tools compatibility warnings 