#!/usr/bin/env python3
"""
AutoTQ Unified Production Tool

Flow:
- Ensure API auth (API key or session token) and locally cached firmware/audio are up to date (skip-existing).
- Require Nordic PPK2 present; wait until available, configure 4.2V source.
- Prompt to unplug/replug AutoTQ for clean enumeration.
- Auto-detect device → flash firmware → transfer audio files (fast settings).
- Pause: press Enter to continue to DB + testing.
- Read device MAC/FW/HW → create/update PCB (stage=factory) → run measure_sequence 3x.
- Create tests (device-idle, pump, valve) with stage_label=factory.

Minimal user interaction; concise logs.
"""

import argparse
import sys
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

try:
    import serial  # type: ignore
except Exception:
    serial = None

from autotq_setup import AutoTQSetup
from autotq_programmer import AutoTQProgrammer
from autotq_client import AutoTQClient
from autotq_device_programmer import AutoTQDeviceProgrammer
import autotq_quick_check as qc
from autotq_quick_check import (
    _list_esp_ports,
    _wait_for_usb_reenumeration,
    read_mac_via_status,
    read_mac,
    read_device_info_via_serial,
    read_fw_version_via_serial,
    ensure_pcb_stage,
    post_measure_tests,
    show_pcb_summary,
    run_ppk_sleep_measure,
    post_power_test,
    send_sleep_command,
)

# Optional PPK imports (best-effort)
try:
    from ppk2_api.ppk2_api import PPK2_API  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:
    PPK2_API = None  # type: ignore
    list_ports = None  # type: ignore


def log(msg: str):
    print(msg, flush=True)


# Quiet context to reduce noisy library output
from contextlib import redirect_stdout, redirect_stderr
import io

class suppress_output:
    def __enter__(self):
        self._stdout = io.StringIO()
        self._stderr = io.StringIO()
        self._exit1 = redirect_stdout(self._stdout)
        self._exit2 = redirect_stderr(self._stderr)
        self._exit1.__enter__()
        self._exit2.__enter__()
        return self
    def __exit__(self, exc_type, exc, tb):
        try:
            self._exit2.__exit__(exc_type, exc, tb)
            self._exit1.__exit__(exc_type, exc, tb)
        finally:
            self._stdout.close()
            self._stderr.close()


def find_ppk_comport() -> Optional[str]:
    try:
        if list_ports is None:
            return None
        ports = list(list_ports.comports())
        for p in ports:
            try:
                if getattr(p, 'vid', None) == 0x1915 and getattr(p, 'pid', None) == 0xC00A:
                    return p.device
            except Exception:
                continue
        for p in ports:
            desc = (getattr(p, 'description', '') or '').lower()
            if 'nrf connect usb cdc acm' in desc or 'ppk' in desc:
                return p.device
    except Exception:
        return None
    return None


GLOBAL_PPK = None


def wait_for_ppk() -> Optional[PPK2_API]:
    if PPK2_API is None:
        log("PPK2 library not installed. Install: pip install ppk2_api")
        return None
    global GLOBAL_PPK
    if GLOBAL_PPK is not None:
        return GLOBAL_PPK
    log("Waiting for PPK2... plug it in if not detected.")
    for _ in range(60):
        port = find_ppk_comport()
        if port:
            try:
                ppk = PPK2_API(port)
                GLOBAL_PPK = ppk
                return GLOBAL_PPK
            except Exception:
                pass
        time.sleep(1)
    return None


def configure_ppk_source(ppk: PPK2_API, mv: int = 4200) -> bool:
    try:
        try:
            ppk.get_modifiers()
        except Exception:
            pass
        # Best-effort: set highest sampling rate if API supports it
        try:
            if hasattr(ppk, 'set_sampling_period'):  # some APIs expose this
                ppk.set_sampling_period(1)  # 1 us if supported
        except Exception:
            pass
        ppk.use_source_meter()
        ppk.set_source_voltage(int(mv))
        try:
            ppk.set_source_current_limit(0)
        except Exception:
            try:
                ppk.set_current_limit(0)  # type: ignore
            except Exception:
                pass
        try:
            ppk.start_measuring()
        except Exception:
            pass
        try:
            ppk.toggle_DUT_power("ON")
        except Exception:
            try:
                ppk.toggle_DUT_power(True)  # type: ignore
            except Exception:
                pass
        log("PPK: Source set to 4.2 V and DUT power enabled")
        return True
    except Exception as e:
        log(f"PPK: Failed to configure source ({e})")
        return False


def ensure_files(setup_url: str, verify_ssl: bool) -> Tuple[bool, AutoTQClient]:
    # Use setup tool with skip-existing behavior but keep console quiet
    setup = AutoTQSetup(base_url=setup_url, verify_ssl=verify_ssl, output_dir=".")
    with suppress_output():
        if not setup.check_system_requirements():
            return False, setup.client
        if not setup.authenticate():
            return False, setup.client
        ok_fw = True
        fw_info = setup.get_latest_firmware_version()
        if fw_info:
            ok_fw = setup.download_firmware(fw_info, force=False)
        ok_audio = setup.download_all_audio_files(force=False)
    # Minimal status line
    log("✔ Files verified (firmware/audio)")
    return (ok_fw and ok_audio), setup.client


def ensure_ppk_on(mv: int = 4200) -> None:
    global GLOBAL_PPK
    if GLOBAL_PPK is None:
        return
    try:
        GLOBAL_PPK.use_source_meter()
        GLOBAL_PPK.set_source_voltage(int(mv))
        try:
            GLOBAL_PPK.start_measuring()
        except Exception:
            pass
        try:
            GLOBAL_PPK.toggle_DUT_power("ON")
        except Exception:
            try:
                GLOBAL_PPK.toggle_DUT_power(True)  # type: ignore
            except Exception:
                pass
    except Exception:
        pass


def prompt_enter_or_skip(message: str, auto_proceed: bool = False) -> bool:
    if auto_proceed:
        log(f"{message} → auto-proceeding")
        return True
    try:
        resp = input(f"{message} (Enter to continue, 's' to skip): ").strip().lower()
        return resp != 's'
    except Exception:
        return True


def _wait_for_usb_disconnection(prev_port: str, timeout_s: float = 60.0) -> bool:
    """Wait until the given port is no longer present among ESP ports."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            ports_now = set(_list_esp_ports())
            if prev_port not in ports_now:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def program_firmware_only() -> bool:
    from autotq_firmware_programmer import AutoTQFirmwareProgrammer
    ensure_ppk_on()
    log("")
    log("Programming firmware...")
    t0 = time.perf_counter()
    
    # Prefer using the port we just detected to avoid any interactive prompts
    try:
        port = find_first_device_port()
    except Exception:
        port = None
    
    if not port:
        log("❌ No device port detected")
        return False
    
    log(f"Using detected port: {port}")
    
    # CRITICAL FIX: Clean up any stale port handles before programming
    # This fixes "ClearCommError" and "PermissionError" issues on Windows
    if not _cleanup_stale_port(port):
        log("⚠️ Port cleanup failed!")
        log("❓ Do you want to:")
        log("   [1] Retry after unplugging/replugging device (RECOMMENDED)")
        log("   [2] Attempt programming anyway")
        log("   [3] Skip this device")
        try:
            choice = input("Enter choice (1-3): ").strip()
            if choice == "1":
                log("📌 Please unplug the USB device now...")
                time.sleep(2)
                log("📌 Wait 3 seconds...")
                time.sleep(3)
                log("📌 Now plug the device back in...")
                time.sleep(3)
                log("🔄 Retrying cleanup...")
                if not _cleanup_stale_port(port):
                    log("❌ Cleanup still failed. Skipping device.")
                    return False
            elif choice == "3":
                log("⏭️ Skipping device")
                return False
            # choice == "2" or anything else falls through to attempt anyway
        except Exception:
            log("⚠️ Using default: attempting anyway...")
    
    fw = AutoTQFirmwareProgrammer(port=port)
    ok = fw.program_device(port=port, erase_first=True, verify=False, smart_erase=True, production_mode=True)
    log(f"✔ Firmware programmed ({time.perf_counter() - t0:.1f}s)" if ok else "✖ Firmware programming failed")
    
    # CRITICAL FIX: Wait for port to be fully released by esptool subprocess
    # This prevents "port busy" errors when programming multiple devices
    if ok and port:
        log("⏳ Waiting for serial port to be released...")
        _wait_for_port_release(port, timeout_s=5.0)
        time.sleep(1.0)  # Additional buffer for Windows COM port cleanup
    
    return ok


def transfer_audio_only() -> bool:
    from autotq_device_programmer import AutoTQDeviceProgrammer
    ensure_ppk_on()
    log("")
    log("Transferring audio files...")
    t0 = time.perf_counter()
    ok = False
    port = None
    # Prefer using the port we just detected to avoid any interactive prompts
    try:
        port = find_first_device_port()
    except Exception:
        port = None
    if port:
        log(f"Using detected port: {port}")
    
    dp = None
    try:
        dp = AutoTQDeviceProgrammer(port=port, stabilize_ms=0)  # Reduce initial stabilize delay
        # Use moderately fast, reliable settings for production
        try:
            dp.set_transfer_speed("fast")
        except Exception:
            pass
        
        # Wait briefly for port to be accessible
        if port and not _wait_for_port_available(port, timeout_s=3.0):
            log("⚠️ Port may not be ready, attempting connection anyway...")
        
        if dp.connect():
            successful, failed = dp.transfer_required_files(skip_existing=False)
            ok = failed == 0
        else:
            log("✖ Failed to connect to device for audio transfer")
            ok = False
    finally:
        if dp:
            try:
                dp.disconnect()
            except Exception:
                pass
        # CRITICAL FIX: Ensure serial port is fully released
        if port:
            time.sleep(0.5)  # Brief pause for port cleanup
    
    log(f"✔ Audio transferred ({time.perf_counter() - t0:.1f}s)" if ok else "✖ Audio transfer failed")
    return ok


def read_mac_and_versions(port: str) -> Tuple[str, Optional[str], Optional[str]]:
    mac = read_mac_via_status(port) or read_mac(port) or "?"
    dinfo = read_device_info_via_serial(port)
    fw = dinfo.get("firmware_version") or read_fw_version_via_serial(port)
    hw = dinfo.get("hardware_version")
    return mac, fw, hw


def find_first_device_port() -> Optional[str]:
    """Find first available ESP device port with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        ports = _list_esp_ports()
        if ports:
            return ports[0]
        if attempt < max_retries - 1:
            log(f"⚠️ No device detected (attempt {attempt + 1}/{max_retries}), refreshing...")
            _force_port_refresh()
            time.sleep(0.5)
    return None


def _wait_for_port_release(port: str, timeout_s: float = 5.0) -> bool:
    """Wait for a serial port to be released by checking if we can open it."""
    import serial as ser
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            # Try to briefly open the port to verify it's released
            test = ser.Serial(port, 115200, timeout=0.5)
            test.close()
            time.sleep(0.1)  # Brief pause after successful check
            return True
        except (ser.SerialException, OSError):
            # Port still busy or not accessible
            time.sleep(0.2)
    return False


def _wait_for_port_available(port: str, timeout_s: float = 3.0) -> bool:
    """Wait for a serial port to become available."""
    import serial as ser
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            test = ser.Serial(port, 115200, timeout=0.5)
            test.close()
            return True
        except (ser.SerialException, OSError):
            time.sleep(0.25)
    return False


def _force_port_refresh():
    """Force Windows to refresh COM port enumeration by scanning ports."""
    try:
        # Simply enumerating ports forces Windows to refresh its cache
        from serial.tools import list_ports
        list(list_ports.comports())
        time.sleep(0.2)
    except Exception:
        pass


def _cleanup_stale_port(port: str, max_attempts: int = 5) -> bool:
    """
    Aggressively clean up stale port handles that cause ClearCommError on Windows.
    
    This fixes the "PermissionError(13, 'The device does not recognize the command.')"
    error that occurs when a port has stale handles from previous sessions.
    """
    import serial as ser
    
    log(f"🔧 Attempting to clean up port {port}...")
    
    # First, try to detect if port is accessible at all
    for attempt in range(max_attempts):
        try:
            # Strategy: Open with minimal settings, no handshaking
            test = ser.Serial()
            test.port = port
            test.baudrate = 9600  # Use slower speed for cleanup
            test.timeout = 0.5
            test.write_timeout = 0.5
            test.inter_byte_timeout = None
            test.xonxoff = False
            test.rtscts = False
            test.dsrdtr = False
            
            # Disable all control lines before opening
            try:
                test.dtr = False
                test.rts = False
            except Exception:
                pass
            
            try:
                test.open()
                # Successfully opened, now cycle control lines to reset device state
                try:
                    test.setDTR(False)
                    test.setRTS(False)
                    time.sleep(0.05)
                    test.reset_input_buffer()
                    test.reset_output_buffer()
                    time.sleep(0.05)
                except Exception:
                    pass
                test.close()
                time.sleep(0.3)  # Give Windows time to release
                log(f"✅ Port {port} cleanup successful (attempt {attempt + 1})")
                return True
            except Exception as e:
                if test.is_open:
                    try:
                        test.close()
                    except Exception:
                        pass
                
                if attempt < max_attempts - 1:
                    log(f"⚠️ Port cleanup attempt {attempt + 1}/{max_attempts} failed: {type(e).__name__}")
                    # Exponential backoff
                    wait_time = 0.5 * (attempt + 1)
                    log(f"⏳ Waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)
                else:
                    log(f"❌ Port cleanup failed after {max_attempts} attempts: {e}")
        except Exception as e:
            if attempt < max_attempts - 1:
                log(f"⚠️ Port cleanup attempt {attempt + 1}/{max_attempts} failed: {type(e).__name__}")
                wait_time = 0.5 * (attempt + 1)
                time.sleep(wait_time)
            else:
                log(f"❌ Cannot access port {port}: {e}")
    
    # Last resort: check if something else has it open
    log(f"❌ Port {port} is not accessible - may be held by another process")
    log(f"💡 Try these steps:")
    log(f"   1. Unplug the USB device")
    log(f"   2. Close any other programs that might be using the port")
    log(f"   3. Wait 3 seconds")
    log(f"   4. Plug the USB device back in")
    log(f"   5. Try again")
    
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoTQ Unified Production Tool")
    parser.add_argument("--url", default="https://seahorse-app-ax33h.ondigitalocean.app", help="Server URL")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL verification")
    parser.add_argument("--api-key", help="API key (X-API-Key)")
    parser.add_argument("--auto-proceed", "-y", action="store_true", help="Auto-proceed without waiting for Enter key prompts")
    parser.add_argument("--skip-audio", action="store_true", help="Skip audio file transfer")
    parser.add_argument("--force-port-cleanup", action="store_true", help="Force aggressive port cleanup (helps with Windows port issues)")
    args = parser.parse_args()

    while True:
        cycle_start = time.perf_counter()
        steps: List[Tuple[str, bool, float]] = []

        # Step 1: verify firmware/audio
        t0 = time.perf_counter()
        ok_files, client = ensure_files(args.url, verify_ssl=not args.no_ssl_verify)
        # If user passed an explicit API key, set it on this client too
        if getattr(args, 'api_key', None):
            try:
                client.set_api_key(args.api_key, prompt_if_missing=False)
            except Exception:
                pass
        steps.append(("Files verified (firmware/audio)", ok_files, time.perf_counter() - t0))
        if not ok_files:
            _print_summary(steps)
            return 1

        # Step 2: PPK + jig prompt + enumerate
        ppk = wait_for_ppk()
        if not ppk:
            log("❌ PPK not detected. Please connect the Nordic PPK2 and press Enter to retry.")
            # Always wait for PPK even in auto-proceed mode (hardware requirement)
            try:
                input()
            except Exception:
                pass
            ppk = wait_for_ppk()
            if not ppk:
                _print_summary(steps)
                return 1
        configure_ppk_source(ppk, mv=4200)
        # Share PPK handle with quick_check helpers so overlays and sleep test work
        try:
            qc.GLOBAL_PPK = ppk
            qc.GLOBAL_PPK_VOLTAGE_MV = 4200
        except Exception:
            pass
        log("")
        log("Place PCB into jig, then unplug/re-plug the AutoTQ USB.")
        _wait_for_usb_reenumeration()
        
        # CRITICAL FIX: Force port refresh and cleanup after enumeration
        _force_port_refresh()
        time.sleep(0.5)

        # Step 3: optional firmware programming
        do_fw = prompt_enter_or_skip("Program firmware", auto_proceed=args.auto_proceed)
        fw_ok = True
        if do_fw:
            t0 = time.perf_counter()
            fw_ok = program_firmware_only()
            steps.append(("Firmware programmed", fw_ok, time.perf_counter() - t0))
            if not fw_ok:
                _print_summary(steps)
                return 1
        else:
            steps.append(("Firmware programmed (skipped)", True, 0.0))

        # Step 4: optional audio transfer
        if args.skip_audio:
            do_audio = False
            log("Transfer audio files → skipped (--skip-audio)")
        else:
            do_audio = prompt_enter_or_skip("Transfer audio files", auto_proceed=args.auto_proceed)
        audio_ok = True
        if do_audio:
            t0 = time.perf_counter()
            audio_ok = transfer_audio_only()
            steps.append(("Audio transferred", audio_ok, time.perf_counter() - t0))
            if not audio_ok:
                _print_summary(steps)
                return 1
        else:
            steps.append(("Audio transferred (skipped)", True, 0.0))

        if not args.auto_proceed:
            try:
                input("Programming stage complete. Press Enter to continue to DB creation & testing, or 's' to skip testing...")
            except Exception:
                pass
        else:
            log("Programming stage complete → auto-proceeding to DB creation & testing")

        # Step 3: detect device and read info
        t0 = time.perf_counter()
        port = find_first_device_port()
        detected = port is not None
        steps.append(("Device detected post-flash", detected, time.perf_counter() - t0))
        if not detected:
            _print_summary(steps)
            return 1
        mac, fw, hw = read_mac_and_versions(port)  # type: ignore[arg-type]
        print(f"Device: {port}  MAC={mac}  FW={fw}  HW={hw}")

        # Step 4: PCB create/update
        t0 = time.perf_counter()
        pcb_id = None
        ok_pcb = False
        if mac != "?" and fw:
            # Prefer saved API key from setup client; if absent, prompt once
            if not client.is_authenticated():
                client.set_api_key(prompt_if_missing=True)
            pcb = ensure_pcb_stage(client, mac, fw, hw, stage_label='factory', allow_create=True)
            ok_pcb = pcb is not None
            pcb_id = pcb.get('id') if pcb else None
        steps.append(("PCB create/update (factory)", ok_pcb, time.perf_counter() - t0))

        # Step 5: measurements (3x) + tests
        do_tests = prompt_enter_or_skip("Run measurements and store tests", auto_proceed=args.auto_proceed)
        if not do_tests:
            steps.append(("Measurements x3 + tests (skipped)", True, 0.0))
            _print_summary(steps, total=time.perf_counter() - cycle_start)
            if _prompt_next_cycle(auto_proceed=args.auto_proceed):
                break
            print("\n--- New Cycle ---\n")
            continue
        t0 = time.perf_counter()
        ok_meas = True
        for i in range(1, 4):
            result = _run_measure_on_port(port)  # type: ignore[arg-type]
            if result:
                _print_measure_summary(port, result)  # type: ignore[arg-type]
                if pcb_id is not None:
                    post_measure_tests(client, pcb_id, result, stage_label='factory', run_index=i)
            else:
                ok_meas = False
                print(f"[MEASURE-ERR] Unable to obtain measure_sequence result (run {i})")
        steps.append(("Measurements x3 + tests", ok_meas, time.perf_counter() - t0))

        # Sleep-mode power test sequence
        if args.auto_proceed:
            log("Run sleep-mode power test → auto-proceeding")
            do_sleep = True
        else:
            try:
                do_sleep = input("Run sleep-mode power test (Enter to continue, 's' to skip): ").strip().lower() != 's'
            except Exception:
                do_sleep = True
        if do_sleep:
            # Ask device to enter sleep (defer until USB unplug)
            send_sleep_command(port, seconds=0, defer_until_usb_unplug=True)
            print("Unplug the AutoTQ PCB from USB now. Waiting for device to disconnect...")
            _wait_for_usb_disconnection(port, timeout_s=60.0)
            print("Device disconnected. Measuring sleep current for 10s; stats will discard first 5s...")
            # Single 10s capture starting immediately; compute stats over last 5s (no live plot)
            sleep_meas = run_ppk_sleep_measure(duration_s=10.0, live_plot=False, discard_initial_s=5.0)
            if sleep_meas is not None:
                print(f"[SLEEP] PPK V={sleep_meas.get('ppk_voltage_v')}V I={sleep_meas.get('ppk_current_mA')}mA (min={sleep_meas.get('ppk_min_mA')} max={sleep_meas.get('ppk_max_mA')})")
                if pcb_id is not None:
                    post_power_test(client, pcb_id, sleep_meas, stage_label='factory', run_index=1)
            else:
                print("[SLEEP-ERR] Unable to measure sleep current (no PPK data)")
            # No need to re-plug for this cycle

        # Step 6: summary
        # No detailed test listing here per request

        _print_summary(steps, total=time.perf_counter() - cycle_start)

        if _prompt_next_cycle(auto_proceed=args.auto_proceed):
            break
        print("\n--- New Cycle ---\n")
    return 0


def _print_summary(steps: List[Tuple[str, bool, float]], total: Optional[float] = None) -> None:
    print("\nSummary:")
    for name, ok, dur in steps:
        status = "✅" if ok else "❌"
        print(f"  {status} {name} ({dur:.1f}s)")
    if total is not None:
        print(f"  ⏱ Total: {total:.1f}s")


def _prompt_next_cycle(auto_proceed: bool = False) -> bool:
    """Prompt for next device and ensure proper cleanup between cycles."""
    if auto_proceed:
        log("Remove PCB and insert the next one → auto-proceeding to next cycle")
        time.sleep(3)  # Longer pause for PCB swap and port cleanup
    else:
        try:
            nxt = input("Remove PCB and insert the next one, then press Enter (or 'q' to quit): ").strip().lower()
            if nxt == 'q':
                return True
        except Exception:
            pass
    
    # CRITICAL FIX: Force port re-enumeration and cleanup before next device
    log("🔄 Refreshing port enumeration...")
    _force_port_refresh()
    time.sleep(1.0)  # Additional buffer for Windows COM subsystem
    return False


# Import measure helpers from quick_check without re-defining
from autotq_quick_check import _run_measure_on_port, _print_measure_summary


if __name__ == "__main__":
    raise SystemExit(main())


