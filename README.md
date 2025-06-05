# AutoTQ Programming Tools

Complete toolkit for programming AutoTQ ESP32-S3 devices with firmware and audio files.

## ✅ Tested Environment
- **Platform**: Windows 11 (primary testing)
- **Python**: 3.8+
- **Hardware**: ESP32-S3 AutoTQ devices
- **Authentication**: Username/password registered in AutoTQ database
- **Performance**: Complete programming cycle ~144 seconds

## 🚀 Quick Start (Main Workflow)

### Step 1: Initial Setup & Updates
Run this **once initially**, then **whenever you need updates** for new firmware or audio files:

```bash
python autotq_setup.py
```

**What this does:**
- Connects to AutoTQ server with your credentials
- Downloads the latest firmware to `./firmware/`
- Downloads all required audio files to `./audio/`
- Creates a manifest file with version information
- Saves credentials securely for future use

**When to run:**
- First time using the tools
- When new firmware versions are released
- When audio files are updated
- If you get "files not found" errors

### Step 2: Program Your Devices
Run this **every time you want to program a device**:

```bash
python autotq_programmer.py
```

**What this does automatically:**
- ✅ **Auto-detects esptool** (tested on Windows 11)
- ✅ **Auto-detects ESP32-S3 devices** (works with multiple USB devices connected)
- ✅ **Flashes latest firmware** using optimized settings
- ✅ **Transfers all audio files** with production-optimized timing
- ✅ **Complete hands-off operation** after initial credential entry

**Performance (tested):**
- **Total time**: ~144 seconds per device
- **Firmware flashing**: ~30-60 seconds
- **Audio transfer**: ~60-90 seconds (could be optimized further)
- **Device detection**: Near-instant

## 📋 System Requirements

### Verified Working Environment
- **Operating System**: Windows 11 ✅ (primary testing platform)
- **Python**: 3.8 or higher
- **Internet**: Required for initial setup and updates
- **USB**: Available port for device connection
- **Credentials**: Valid username/password in AutoTQ database

### Required Python Packages
The tools will automatically install these when needed:
```bash
pip install pyserial esptool requests tqdm psutil cryptography
```

### Hardware
- AutoTQ ESP32-S3 devices
- USB cable for device connection
- At least 500MB free disk space

## 🔧 Installation & First Use

### Windows (Tested)
1. **Download/clone the AutoTQ programming tools**
2. **Run the setup script** (handles everything automatically):
   ```cmd
   setup_and_program.bat
   ```
   Or manually:
   ```cmd
   python autotq_setup.py
   python autotq_programmer.py
   ```

### Linux/macOS (Community Support)
1. **Make script executable and run**:
   ```bash
   chmod +x setup_and_program.sh
   ./setup_and_program.sh
   ```
   Or manually:
   ```bash
   python3 autotq_setup.py
   python3 autotq_programmer.py
   ```

## 🏭 Production Features (Default Mode)

The tools are optimized for **production use** by default:

### Firmware Programming
- ✅ **Smart sectored erase** (faster than full chip erase)
- ✅ **Compression enabled** for faster transfer
- ✅ **Verification skipped** for speed (firmware flash success rate is very high)
- ✅ **High-speed baud rates** (921600 bps)

### Audio File Transfer  
- ✅ **Optimized chunk sizes** (256B writes, 2KB file chunks)
- ✅ **Minimal delays** (1ms between writes)
- ✅ **Production timing** (tested stable settings)
- ⚠️ **Room for improvement** (audio transfer could be faster)

### Device Detection
- ✅ **Auto-detects esptool** (finds Python module or installed version)
- ✅ **Smart device filtering** (prioritizes ESP32-S3 devices)
- ✅ **Multi-device handling** (tested with multiple USB devices connected)
- ✅ **Platform-specific optimizations**

## 📖 Detailed Usage

### Main Commands (Tested & Recommended)

#### Setup & Updates
```bash
# Download everything (run when you need updates)
python autotq_setup.py

# Download only firmware updates
python autotq_setup.py --firmware-only

# Download only audio file updates  
python autotq_setup.py --audio-only

# Force re-download (if files are corrupted)
python autotq_setup.py --force
```

#### Device Programming
```bash
# Auto-detect and program device (RECOMMENDED)
python autotq_programmer.py

# Development mode (slower, with verification)
python autotq_programmer.py --dev

# Program multiple devices automatically
python autotq_programmer.py --batch

# Check requirements and device detection
python autotq_programmer.py --check-only
```

### Batch Scripts (Tested - Windows)
For the easiest experience:
```cmd
# Windows: Complete setup and programming
setup_and_program.bat

# Linux/Mac: Complete setup and programming  
./setup_and_program.sh
```

## 🧪 Advanced Features (Experimental)

*Note: These individual tools exist but are not as thoroughly tested as the main workflow above.*

### Individual Firmware Programming
```bash
python autotq_firmware_programmer.py --auto-program
```

### Individual Audio Transfer
```bash
python autotq_device_programmer.py --transfer-all
```

### Interactive Modes
```bash
# Firmware programmer with menu
python autotq_firmware_programmer.py

# Audio programmer with menu
python autotq_device_programmer.py
```

## 📊 Performance Data

Based on real-world testing:

| Operation | Time | Notes |
|-----------|------|-------|
| **Complete device programming** | ~144 seconds | Firmware + audio files |
| **Firmware flashing** | 30-60 seconds | Depends on firmware size |
| **Audio file transfer** | 60-90 seconds | 5 files, could be optimized |
| **Device detection** | <5 seconds | Usually instant |
| **Setup download** | 1-5 minutes | Depends on internet speed |

## 🔍 Troubleshooting

### Common Issues (Tested Solutions)

#### "esptool not found"
✅ **Solution**: The tool auto-installs esptool
```bash
pip install esptool
```

#### "No devices detected"  
✅ **Solution**: Check USB connection and device mode
- Ensure device is connected via USB
- Try different USB cable/port
- Check Windows Device Manager for COM ports

#### "Permission denied" (Linux)
✅ **Solution**: Add user to dialout group
```bash
sudo usermod -a -G dialout $USER
# Logout and login again
```

#### "Files not found"
✅ **Solution**: Run setup first
```bash
python autotq_setup.py
```

#### "Authentication failed"
✅ **Solution**: Verify credentials
- Ensure username/password are registered in AutoTQ database
- Check internet connection
- Verify server URL

#### Slow performance
✅ **Solutions**:
- Production mode is already enabled by default
- Audio transfer optimization is ongoing
- Close other USB applications

## 📁 File Structure

After running `autotq_setup.py`:

```
D:\AutoTQDCSProgramming\
├── firmware/
│   └── v1.3.1/                    # Latest version
│       ├── firmware_v1.3.1.bin   # Binary file
│       └── manifest_v1.3.1.json  # ESP Web Tools manifest
├── audio/
│   ├── tightenStrap.wav           # Required audio files
│   ├── bleedingContinues.wav
│   ├── pullStrapTighter.wav
│   ├── inflating.wav
│   └── timeRemaining.wav
├── autotq_manifest.json           # Download metadata
├── autotq_setup.log               # Setup log
├── autotq_programmer.py           # ⭐ Main programming tool
├── autotq_setup.py                # ⭐ Setup/update tool
├── setup_and_program.bat          # ⭐ Windows batch script
└── setup_and_program.sh           # Linux/Mac script
```

## 🎯 Recommended Workflow

### For Production Use
1. **Initial setup** (once):
   ```bash
   python autotq_setup.py
   ```

2. **Program devices** (as needed):
   ```bash
   python autotq_programmer.py
   ```

3. **Update when needed**:
   ```bash
   python autotq_setup.py  # Get latest files
   python autotq_programmer.py  # Program with updates
   ```

### For Development/Testing
1. **Use development mode** for verification:
   ```bash
   python autotq_programmer.py --dev
   ```

2. **Check individual components**:
   ```bash
   python autotq_programmer.py --check-only
   ```

## ⚠️ Known Limitations

- **Audio transfer speed**: Currently ~60-90 seconds for 5 files, could be optimized
- **Individual tools**: Less tested than main workflow
- **Platform support**: Primarily tested on Windows 11
- **Firmware verification**: Disabled by default for speed (can be enabled with `--dev`)

## 🆘 Support

### Before Reporting Issues
1. **Check log files**: `autotq_setup.log`
2. **Verify requirements**: `python autotq_programmer.py --check-only`
3. **Update files**: `python autotq_setup.py`
4. **Check connections**: Device and internet connectivity

### Error Codes
- **Exit 0**: Success ✅
- **Exit 1**: General error (check logs)
- **Exit 2**: Requirements not met
- **Exit 3**: Authentication failed  
- **Exit 4**: Device connection failed

### Getting Help
1. Check the troubleshooting section above
2. Review log files for specific error messages
3. Ensure you're using the main workflow (setup → program)
4. Verify your environment matches the tested configuration

---

**✅ This toolkit has been tested and verified on Windows 11 with real AutoTQ ESP32-S3 devices. The main workflow (autotq_setup.py → autotq_programmer.py) is production-ready and optimized for fast, reliable device programming.**