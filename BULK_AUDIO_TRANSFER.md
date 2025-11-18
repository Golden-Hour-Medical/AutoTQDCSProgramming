# AutoTQ Bulk Audio Transfer Tool

## Quick Reference Guide

### What It Does
Transfers audio files to **multiple AutoTQ devices simultaneously** using parallel threads. Instead of transferring to devices one at a time, this tool detects all connected devices and transfers to all of them at once.

### Time Savings
- **Sequential**: 10 devices × 60 seconds = **10 minutes**
- **Parallel**: 10 devices ÷ 1 transfer time = **~60 seconds** ⚡

## Quick Start

### Basic Usage (Interactive)
```bash
# Windows
run_bulk_audio.bat

# Python
python autotq_bulk_audio_transfer.py
```

**What happens:**
1. Tool detects all connected AutoTQ devices
2. Shows you which devices were found
3. Asks for confirmation
4. Transfers audio to all devices in parallel
5. Shows summary of results

### Production Mode (Automated)
```bash
# Windows - no prompts, start immediately
run_bulk_audio.bat --no-prompt

# Python - no prompts, start immediately
python autotq_bulk_audio_transfer.py --no-prompt
```

### Continuous Production Mode
```bash
# Keep running and process new batches automatically
run_bulk_audio.bat --continuous --no-prompt
```

**Perfect for:**
- Production lines
- Quality control stations
- High-volume manufacturing

## Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--no-prompt` | Skip confirmation, start immediately | `run_bulk_audio.bat --no-prompt` |
| `--speed` | Transfer speed: slow, normal, fast, ultrafast | `--speed ultrafast` |
| `--audio-dir` | Custom audio directory | `--audio-dir C:\MyAudio` |
| `--continuous` | Keep detecting and transferring to new devices | `--continuous` |

## Common Scenarios

### Scenario 1: Program 10 Devices at Once
1. Plug in all 10 devices to USB hub(s)
2. Run: `run_bulk_audio.bat`
3. Wait ~60-90 seconds
4. Done! All 10 devices have audio files

### Scenario 2: Production Line
1. Set up multiple USB ports/hubs at workstation
2. Run: `run_bulk_audio.bat --continuous --no-prompt`
3. Worker plugs in batch of devices
4. Tool auto-detects and transfers
5. Worker removes completed batch, plugs in next batch
6. Repeat continuously

### Scenario 3: Quality Control Re-Transfer
1. Connect devices that need audio updated
2. Run: `run_bulk_audio.bat --no-prompt --speed ultrafast`
3. Tool transfers to all devices simultaneously
4. Remove and process next batch

## Understanding the Output

### Detection Phase
```
[10:30:15] Detecting connected AutoTQ devices...
[10:30:16] ✅ Found 3 device(s):
   1. COM3 - ESP32-S3 🎯
   2. COM5 - ESP32-S3 🎯
   3. COM7 - ESP32-S3 🎯
```

### Transfer Phase (Parallel)
```
[10:30:20] [COM3] Starting audio transfer...
[10:30:20] [COM5] Starting audio transfer...
[10:30:20] [COM7] Starting audio transfer...
[10:30:45] [COM3] ✅ Transfer complete - 6 files transferred
[10:30:47] [COM5] ✅ Transfer complete - 6 files transferred
[10:30:48] [COM7] ✅ Transfer complete - 6 files transferred
```

### Summary
```
======================================================================
TRANSFER SUMMARY
======================================================================

✅ Device 1: COM3
   Duration: 25.3s
   Files: 6 succeeded, 0 failed
   Device: MAC=AA:BB:CC:DD:EE:01, FW=v1.3.1

✅ Device 2: COM5
   Duration: 27.1s
   Files: 6 succeeded, 0 failed
   Device: MAC=AA:BB:CC:DD:EE:02, FW=v1.3.1

✅ Device 3: COM7
   Duration: 28.5s
   Files: 6 succeeded, 0 failed
   Device: MAC=AA:BB:CC:DD:EE:03, FW=v1.3.1

======================================================================
OVERALL RESULTS
======================================================================
Total devices: 3
Successful: 3
Total time: 28.5s
Average time per device: 26.9s
======================================================================
```

## Troubleshooting

### No Devices Detected
**Problem:** Tool reports "No AutoTQ devices detected"

**Solutions:**
1. Check USB connections
2. Make sure devices are powered on
3. Verify devices enumerate properly in Device Manager (Windows)
4. Try unplugging and re-plugging devices
5. Check that drivers are installed (run `setup_all.bat`)

### Some Transfers Failed
**Problem:** Some devices succeeded, others failed

**Solutions:**
1. Check the error message for failed devices
2. Try re-running for just the failed devices
3. Verify those devices work individually
4. Check USB cable quality
5. Try a slower transfer speed: `--speed normal`

### Permission Errors on Windows
**Problem:** `PermissionError(13, 'The device does not recognize the command.')`

**What it means:** Windows COM port conflict when opening multiple serial ports simultaneously

**Solutions (Already Built-In):**
1. ✅ Tool automatically staggers connections (1.5s intervals)
2. ✅ Built-in retry logic (3 attempts per device)
3. ✅ Each device gets its own dedicated thread

**If still occurring:**
1. Close any other programs using COM ports (Arduino IDE, PuTTY, etc.)
2. Reduce number of simultaneous devices
3. Try unplugging/replugging devices
4. Restart computer to clear COM port locks

### Transfer Too Slow
**Problem:** Transfer seems slower than expected

**Solutions:**
1. Use faster transfer speed: `--speed ultrafast`
2. Check USB hub quality (some hubs have slow bandwidth)
3. Close other USB-intensive applications
4. Ensure devices have good USB connections

### Audio Files Not Found
**Problem:** "Audio directory not found" error

**Solution:**
1. Run setup first: `setup_all.bat` or `python autotq_setup.py`
2. Or specify custom directory: `--audio-dir path/to/audio`

## Technical Details

### How Parallel Transfer Works
1. Main thread detects all connected ESP32/AutoTQ devices
2. Spawns one worker thread per device
3. Connections are **staggered** (1.5s intervals) to avoid Windows COM port conflicts
4. Each thread independently:
   - Waits for its staggered connection delay
   - Connects to its assigned device (with retry logic)
   - Transfers all required audio files
   - Reports progress and results
5. Main thread waits for all workers to complete
6. Displays consolidated summary

**Important:** On Windows, attempting to open multiple serial ports simultaneously can cause permission errors. The tool automatically staggers connection attempts to avoid this issue. The first device connects immediately, the second after 1.5s, the third after 3s, etc. This adds a small initial delay but ensures reliable connections.

### Thread Safety
- Each device has its own serial port connection
- No shared state between device threads
- Thread-safe result collection
- Safe for concurrent operations

### Performance Considerations
- **CPU**: Minimal - mostly waiting on I/O
- **Memory**: ~50MB + (5MB per device)
- **USB Bandwidth**: Main bottleneck
  - USB 2.0 hub: ~10-15 devices simultaneously
  - USB 3.0 hub: ~20+ devices simultaneously
- **Serial I/O**: Each device transfers at 115200 baud independently

### Audio Files Transferred
The tool transfers these required files:
1. `tightenStrap.wav`
2. `bleedingContinues.wav`
3. `pullStrapTighter.wav`
4. `inflating.wav`
5. `timeRemaining.wav`
6. `reattachStrap.wav`

## Integration with Production Workflow

### Option 1: Two-Stage Process
**Stage 1 - Firmware (Sequential):**
- Use `autotq_unified_production.py` to flash firmware one at a time
- Firmware flashing is fast (~30s) and works best sequentially

**Stage 2 - Audio (Parallel):**
- Collect all firmware-flashed devices
- Use `run_bulk_audio.bat --no-prompt` to transfer audio to all devices at once
- Audio transfer is slow (~60s) so parallel saves significant time

### Option 2: Skip Audio in Unified Tool
```bash
# Program firmware only, skip audio
run_unified.bat -y --skip-audio

# Then batch transfer audio to all devices
run_bulk_audio.bat --no-prompt
```

### Option 3: Quality Control Station
- Dedicated workstation with USB hub
- Run in continuous mode
- Workers continuously feed devices through

## Best Practices

### USB Hub Selection
- ✅ **Use powered USB hubs** (don't rely on computer power)
- ✅ **USB 3.0 hubs** provide better bandwidth
- ✅ **Industrial-grade hubs** for reliability
- ❌ Avoid daisy-chaining multiple hubs

### Device Handling
1. Plug in all devices before starting transfer
2. Don't unplug devices during transfer
3. Wait for summary before removing devices
4. Label devices if tracking individual units

### Speed Settings
- **Production**: Use `fast` (default) - good balance
- **Quality Critical**: Use `normal` or `slow` - more reliable
- **Time Critical**: Use `ultrafast` - fastest but verify success rate

### Monitoring
- Watch for any failed transfers in summary
- Keep track of success rate over time
- Re-transfer to any failed devices
- Verify random samples with device testing

## FAQs

**Q: How many devices can I connect at once?**
A: Typically 10-20 devices work well. Limited by USB hub capabilities and bandwidth.

**Q: Can I use this with other AutoTQ tools?**
A: Yes! Use `autotq_unified_production.py --skip-audio` then this tool for audio.

**Q: What if one device fails?**
A: Other devices continue. Failed device shows in summary. Re-run for failed devices.

**Q: Does it work on Mac/Linux?**
A: Yes! Python script works cross-platform. Use `python3 autotq_bulk_audio_transfer.py`

**Q: Can I cancel during transfer?**
A: Yes, press Ctrl+C. Devices that completed will have audio, others won't.

**Q: How do I update audio files?**
A: Run `setup_all.bat` or `python autotq_setup.py` to download latest audio files.

## Support

For issues or questions:
1. Check this guide first
2. Review main README.md
3. Contact AutoTQ support team
4. Report bugs to development team

---

**Last Updated:** November 2025
**Version:** 1.0

