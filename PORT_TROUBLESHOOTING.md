# 🔧 COM Port Troubleshooting Guide

## Problem: "ClearCommError failed" or "Port Busy" Errors

This error happens when Windows COM ports have stale handles or are held by another process.

---

## ⚡ **Quick Fix (Try This First)**

1. **Close the program** (Ctrl+C or close window)
2. **Unplug the AutoTQ USB cable** from your computer
3. **Wait 3 full seconds**
4. **Plug it back in**
5. **Open a fresh Command Prompt** and run again

---

## 🔍 **Diagnose the Problem**

Run this diagnostic tool to check what's wrong with the port:

```cmd
check_port.bat COM229
```

Replace `COM229` with your actual port number. This will tell you:
- ✅ If the port exists
- ✅ If it's accessible  
- ❌ What's preventing access
- 💡 Specific solutions for your situation

---

## 🎯 **Solutions by Error Type**

### Error Type 1: "ClearCommError failed (PermissionError 13)"

**Cause:** Port has stale handles from a previous session

**Solutions (in order):**

1. **Unplug/Replug Method** (Most reliable)
   ```cmd
   # 1. Unplug USB
   # 2. Wait 3 seconds
   # 3. Plug back in
   # 4. Run: run_unified.bat
   ```

2. **Fresh Start Method**
   ```cmd
   # For each device, open a NEW Command Prompt:
   cd D:\AutoTQDCSProgramming
   run_unified.bat
   # After device is done, CLOSE the window
   # Open NEW window for next device
   ```

3. **Check for Other Programs**
   - Close Arduino IDE if open
   - Close any serial monitor programs (PuTTY, TeraTerm, etc.)
   - Close Device Manager if viewing COM ports
   - Check Task Manager for python.exe processes and end them

4. **Reboot Computer** (If nothing else works)

---

### Error Type 2: "Port doesn't exist" or "FileNotFoundError"

**Cause:** Device disconnected or drivers not working

**Solutions:**

1. Check Device Manager (Win + X → Device Manager)
   - Look under "Ports (COM & LPT)"
   - Should see "USB Serial Device (COMxx)" or similar
   - If you see yellow warning icon: Update/reinstall driver

2. Try different USB port

3. Check USB cable (try a different one if available)

---

### Error Type 3: Port works initially, fails on 2nd device

**Cause:** Port not properly released between devices

**The fixes I added should handle this, but if it still happens:**

1. **Use Fresh Start Method** (see above - new CMD window per device)

2. **Manual Port Release:**
   ```cmd
   # Between devices:
   # 1. Close the program
   # 2. Wait 5 seconds
   # 3. Unplug device
   # 4. Wait 3 seconds  
   # 5. Plug in new device
   # 6. Restart program
   ```

---

## 🚀 **Best Practices for Continuous Operation**

### Method 1: Single Command Prompt (Updated Code)
```cmd
cd D:\AutoTQDCSProgramming
run_unified.bat
# Process device 1
# When prompted, swap devices and press Enter
# Process device 2
# etc.
```

**My fixes should make this work now**, but if you still have issues:

### Method 2: Fresh Start Per Device (Most Reliable)
```cmd
# Device 1:
cd D:\AutoTQDCSProgramming
run_unified.bat
# Complete, then CLOSE window

# Device 2:
# Open NEW Command Prompt
cd D:\AutoTQDCSProgramming  
run_unified.bat
# Complete, then CLOSE window
```

---

## 🔧 **Advanced: Check What's Using the Port**

### Windows PowerShell Method:
```powershell
# Check for processes holding serial ports
Get-Process | Where-Object {$_.Modules.ModuleName -like "*serial*"} | Select ProcessName, Id

# If you find a stuck Python process:
Stop-Process -Id <ProcessId> -Force
```

### Check Python Processes:
```cmd
tasklist | findstr python.exe
# If you see multiple python.exe, one might be holding the port
# End them in Task Manager
```

---

## 📝 **What the New Code Does**

I've added these automatic fixes:

1. **Aggressive Port Cleanup** - Tries 5 times with increasing delays to clear stale handles
2. **Port Release Detection** - Waits for esptool to fully release port after flashing
3. **Port Availability Check** - Verifies port is accessible before audio transfer
4. **Automatic Refresh** - Forces Windows to update its COM port cache
5. **Interactive Recovery** - If cleanup fails, guides you through manual fix

---

## ❓ **Still Not Working?**

1. **Try the diagnostic tool:**
   ```cmd
   check_port.bat
   ```

2. **Check these common issues:**
   - [ ] Is Arduino IDE closed?
   - [ ] Are there stale python.exe processes? (Check Task Manager)
   - [ ] Is Device Manager showing the COM port without errors?
   - [ ] Did you try a different USB port?
   - [ ] Did you try unplugging/replugging the device?

3. **Last resort:**
   - Reboot your computer
   - This clears all port handles and resets the COM subsystem

---

## 💡 **Pro Tips**

- **Use a powered USB hub** - Reduces USB issues
- **Same USB port** - Use the same port for all devices (more consistent COM port numbers)
- **Close unneeded programs** - Especially serial monitors and Arduino IDE
- **Don't disconnect during programming** - Can leave port in bad state

---

## 📞 **Getting Help**

If you're still stuck, provide this info:

1. Output from `check_port.bat COMxxx`
2. Error message from run_unified.bat
3. What step of the process fails (first device? second device?)
4. Have you rebooted since the problem started?

