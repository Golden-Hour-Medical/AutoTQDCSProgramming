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

### Step 3 (Optional): Bulk Audio Transfer for Multiple Devices
For **high-volume production** or when you need to update audio on multiple devices:

```bash
# Transfer audio to ALL connected devices simultaneously
python autotq_bulk_audio_transfer.py

# Or use the convenient batch script
run_bulk_audio.bat
```

**Why use bulk transfer?**
- ⚡ **Parallel processing** - Transfer to 10 devices in the time of 1
- 🏭 **Production optimized** - Perfect for manufacturing lines
- 🔄 **Continuous mode** - Keep detecting and transferring to new batches

See the [Detailed Usage](#bulk-audio-transfer-new---parallel-transfer) section for more options.

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
pip install pyserial esptool requests tqdm psutil cryptography ppk2_api
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

## 🧳 Portable Windows Venv (No System Python Changes)

Create a self-contained folder you can zip and ship:

1) Create venv and install deps:
```bat
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt ppk2_api
```

Optional (plotting overlays):
```bat
.\.venv\Scripts\pip install matplotlib
```

2) Create `run_unified.bat`:
```bat
@echo off
setlocal
set PYTHONUTF8=1
set SSL_CERT_FILE=
set REQUESTS_CA_BUNDLE=
.\.venv\Scripts\python.exe autotq_unified_production.py %*
```

3) Run:
```bat
run_unified.bat --api-key YOUR_KEY
```
Place a `.autotq_api_key` file (containing your key) next to the script to skip prompts.

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

#### Bulk Audio Transfer (NEW - Parallel Transfer)
Transfer audio files to multiple devices **simultaneously** for faster production:

```bash
# Auto-detect all devices and transfer audio in parallel
python autotq_bulk_audio_transfer.py

# No confirmation prompts - start immediately
python autotq_bulk_audio_transfer.py --no-prompt

# Use fastest transfer speed
python autotq_bulk_audio_transfer.py --speed ultrafast

# Continuous mode - keep detecting and transferring to new devices
python autotq_bulk_audio_transfer.py --continuous

# Combine options for fully automated production line
python autotq_bulk_audio_transfer.py --no-prompt --speed fast
```

**Windows Batch Scripts:**
```cmd
# Interactive mode - confirm before transfer
run_bulk_audio.bat

# Fully automated - no prompts
run_bulk_audio.bat --no-prompt

# Continuous production mode
run_bulk_audio.bat --continuous --no-prompt
```

**Key Benefits:**
- ✅ **Parallel transfer** - All devices transfer simultaneously
- ✅ **Huge time savings** - Transfer to N devices in the time of 1
- ✅ **Auto-detection** - Automatically finds all connected AutoTQ devices
- ✅ **Progress tracking** - Shows status for each device independently
- ✅ **Batch processing** - Transfer to multiple batches in sequence
- ⚡ **Production optimized** - Ideal for high-volume manufacturing

**Use Cases:**
- Manufacturing lines with multiple programming stations
- Batch programming sessions (program 5-10 devices at once)
- Time-critical production schedules
- Quality control stations (re-transfer audio to multiple devices)

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
├── autotq_bulk_audio_transfer.py  # ⚡ NEW: Bulk audio transfer (parallel)
├── setup_and_program.bat          # ⭐ Windows batch script
├── setup_and_program.sh           # Linux/Mac script
├── run_bulk_audio.bat             # ⚡ NEW: Bulk audio batch script (Windows)
└── run_bulk_audio.ps1             # ⚡ NEW: Bulk audio PowerShell script
```

## 🔒 Version Control & Security

### Automatic Git Exclusions

The project includes a comprehensive `.gitignore` file that automatically excludes temporary and sensitive files:

#### Generated/Downloaded Files
- `firmware/` - Downloaded firmware binaries (large files, updated frequently)
- `audio/` - Downloaded audio files (large files, updated frequently)
- `autotq_manifest.json` - Download metadata and version tracking
- `autotq_setup.log` - Setup and operation logs

#### Security & Credentials
- `autotq_token.json` - **Authentication tokens** (⚠️ **NEVER commit to git**)
- `.autotq_credentials` - Encrypted saved credentials
- `.autotq_salt` - Encryption salt for credential storage

#### Temporary Files
- `autotq_setup.lock` - Process lock files
- `*.tmp`, `*.temp` - Temporary download files
- `__pycache__/` - Python bytecode cache

#### Development Files
- `.vscode/`, `.idea/` - IDE configuration
- `*.pyc`, `*.pyo` - Compiled Python files
- `.mypy_cache/` - Type checker cache

### ⚠️ Important Security Notes

**DO NOT commit authentication tokens:**
- The `autotq_token.json` file contains your login session token
- Committing this file would expose your credentials in git history
- The `.gitignore` file automatically excludes this file

**For team development:**
1. Each developer should run `python autotq_setup.py` to authenticate individually
2. Authentication tokens are unique per user and session
3. Downloaded firmware/audio files are excluded to avoid large commits
4. Use `python autotq_setup.py` to get the latest files instead of committing them

**Clean setup for new users:**
```bash
git clone <repository>
cd <repository>
python autotq_setup.py  # Downloads files and authenticates
python autotq_programmer.py  # Ready to program devices
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