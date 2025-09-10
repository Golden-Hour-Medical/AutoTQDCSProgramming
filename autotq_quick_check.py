#!/usr/bin/env python3
"""
AutoTQ Quick Check

Minimal, no-fuss checker:
 - Detect connected AutoTQ ESP32-S3 devices
 - Read MAC address
 - Read/estimate running firmware version (from device JSON if available)
 - Compare against latest local firmware version in ./firmware
 - Print one concise status line per device

Usage:
  python autotq_quick_check.py

Optional:
  --interval <seconds>  Polling interval (default 1.5)
  --once                Run once and exit (default behavior)

Output format:
  [OK]  COM71  MAC=AA:BB:...  FW=v1.7.14 (up-to-date)
  [OUT] COM72  MAC=...        FW=v1.7.1  (latest=v1.7.14)
  [ERR] COM73  MAC=?          reason
"""

import argparse
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from contextlib import redirect_stdout, redirect_stderr
import io

try:
    import serial  # type: ignore
except Exception:
    serial = None

from autotq_firmware_programmer import AutoTQFirmwareProgrammer
from autotq_device_programmer import AutoTQDeviceProgrammer
from autotq_client import AutoTQClient
try:
    # Nordic PPK2 control API (pip install ppk2_api)
    from ppk2_api.ppk2_api import PPK2_API  # type: ignore
except Exception:
    PPK2_API = None  # type: ignore
try:
    from serial.tools import list_ports  # type: ignore
except Exception:
    list_ports = None  # type: ignore

# Keep a persistent handle to the PPK so power stays enabled
GLOBAL_PPK = None  # type: ignore
GLOBAL_PPK_VOLTAGE_MV = 4200
VERBOSE_SERIAL = False
PPK_MEASURE_ONLY = False
try:
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MPL = True
except Exception:
    HAS_MPL = False


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


def find_latest_version(firmware_dir: Path) -> Optional[str]:
    if not firmware_dir.exists():
        return None
    versions: List[Tuple[List[int], Path]] = []
    for p in firmware_dir.iterdir():
        if p.is_dir() and p.name.startswith('v'):
            try:
                parts = [int(x) for x in p.name[1:].split('.')]
                versions.append((parts, p))
            except Exception:
                pass
    if not versions:
        return None
    versions.sort(key=lambda x: x[0], reverse=True)
    return versions[0][1].name


def _request_with_fallback(client: AutoTQClient, method: str, path: str, **kwargs):
    """General request helper with API path fallback.

    Rules:
    - PCB endpoints do NOT live under /api/v1. If path starts with /pcbs, always use legacy /pcbs.
    - For other endpoints, try /api/v1 first, then fall back to legacy on 404. For write methods, also
      fall back on 405.
    """
    base = client.base_url.rstrip('/')
    normalized = '/' + path.lstrip('/')

    # Special-case PCB endpoints: server exposes these only at legacy paths
    if normalized.startswith('/pcbs'):
        try:
            return client.session.request(method.upper(), f"{base}{normalized}", **kwargs)
        except Exception as e:
            raise e

    v1 = f"{base}/api/v1{normalized}"
    legacy = f"{base}{normalized}"
    try:
        r = client.session.request(method.upper(), v1, **kwargs)
        if method.upper() == 'GET':
            return r
        # For write methods, fall back on 404/405
        if r.status_code not in (404, 405):
            return r
    except Exception:
        pass
    try:
        r2 = client.session.request(method.upper(), legacy, **kwargs)
        return r2
    except Exception as e:
        raise e


def api_get(client: AutoTQClient, path: str, **kwargs):
    return _request_with_fallback(client, 'GET', path, **kwargs)


def api_post(client: AutoTQClient, path: str, **kwargs):
    return _request_with_fallback(client, 'POST', path, **kwargs)


def api_patch(client: AutoTQClient, path: str, **kwargs):
    return _request_with_fallback(client, 'PATCH', path, **kwargs)


def api_put(client: AutoTQClient, path: str, **kwargs):
    return _request_with_fallback(client, 'PUT', path, **kwargs)


def _list_esp_ports() -> List[str]:
    """Return list of ports currently detected as ESP/AutoTQ ('🎯' tagged)."""
    with suppress_output():
        prog = AutoTQFirmwareProgrammer()
        ports = prog.list_available_ports()
    return [p for p, desc in ports if '🎯' in desc]


def _wait_for_usb_reenumeration(max_wait_disconnect_s: float = 15.0, max_wait_reconnect_s: float = 30.0) -> None:
    """Wait for user to unplug then re-plug AutoTQ USB. Auto-advance on detection or timeout."""
    print("Please unplug the AutoTQ USB device (if connected), wait ~1s, then re-plug it. Auto-detecting re-enumeration...")
    start_ports = set(_list_esp_ports())
    # Phase 1: wait for disconnect (if any were present)
    deadline = time.time() + max_wait_disconnect_s
    disconnected = False if start_ports else True
    while time.time() < deadline and not disconnected:
        ports_now = set(_list_esp_ports())
        if not ports_now:
            disconnected = True
            break
        time.sleep(0.25)
    # Phase 2: wait for reconnect (presence of any ESP port)
    deadline2 = time.time() + max_wait_reconnect_s
    while time.time() < deadline2:
        ports_now = set(_list_esp_ports())
        if ports_now:
            # Optional short settle
            time.sleep(2.0)
            print(f"Detected device on: {', '.join(sorted(list(ports_now)))}")
            return
        time.sleep(0.25)
    print("Proceeding without re-enumeration confirmation (timeout reached).")
def _open_serial_safely(port: str, params: Dict[str, Any]):
    """Open serial port with DTR/RTS deasserted to avoid ESP32 auto-reset."""
    try:
        s = serial.Serial()
        s.port = port
        s.baudrate = params.get('baudrate', 115200)
        s.bytesize = params.get('bytesize', 8)
        s.parity = params.get('parity', 'N')
        s.stopbits = params.get('stopbits', 1)
        s.xonxoff = params.get('xonxoff', False)
        s.rtscts = params.get('rtscts', False)
        s.dsrdtr = params.get('dsrdtr', False)
        s.timeout = params.get('timeout', 5)
        try:
            s.dtr = False
            s.rts = False
        except Exception:
            pass
        s.open()
        try:
            s.setDTR(False)
            s.setRTS(False)
        except Exception:
            pass
        if VERBOSE_SERIAL:
            print(f"[SER] Opened {port} baud={s.baudrate} DTR={getattr(s, 'dtr', '?')} RTS={getattr(s, 'rts', '?')}")
        return s
    except Exception:
        return None


def _extract_mac_from_json(obj: Any) -> Optional[str]:
    import re
    if isinstance(obj, dict):
        for k in [
            'mac', 'mac_address', 'macAddress', 'ble_mac', 'bleMac',
            'wifi_mac', 'wifiMac', 'bt_mac', 'btMac']:
            v = obj.get(k)
            if isinstance(v, str):
                m = re.search(r"([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})", v)
                if m:
                    return m.group(1)
        for v in obj.values():
            r = _extract_mac_from_json(v)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _extract_mac_from_json(item)
            if r:
                return r
    return None


def read_mac_via_status(port: str, timeout_s: float = 2.5) -> Optional[str]:
    if serial is None:
        return None
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    s = _open_serial_safely(port, params)
    if s is None:
        return None
    try:
        time.sleep(0.2)
        try:
            s.reset_input_buffer()
            s.reset_output_buffer()
        except Exception:
            pass
        try:
            payload = (json.dumps({"command": "get_status"}) + "\n").encode("utf-8")
            if VERBOSE_SERIAL:
                print(f"[TX] {payload.decode('utf-8', errors='ignore').strip()}")
            s.write(payload)
        except Exception:
            pass
        deadline = time.time() + timeout_s
        buffer = ""
        while time.time() < deadline:
            if s.in_waiting > 0:
                data = s.read(s.in_waiting).decode('utf-8', errors='ignore')
                if VERBOSE_SERIAL and data:
                    for line in data.splitlines():
                        if line.strip():
                            print(f"[RX] {line.strip()}")
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        mac = _extract_mac_from_json(obj)
                        if mac:
                            return mac
                    except Exception:
                        # ignore non-JSON
                        continue
            time.sleep(0.05)
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass


def read_mac(port: str) -> Optional[str]:
    try:
        prog = AutoTQFirmwareProgrammer()
        if not prog.esptool_path:
            return None
        import subprocess, sys, os
        # Build esptool command
        if prog.esptool_path.startswith(sys.executable) and "-m esptool" in prog.esptool_path:
            cmd = [sys.executable, "-m", "esptool", "--port", port, "--baud", "115200", "read_mac"]
        elif os.path.isfile(prog.esptool_path):
            cmd = [sys.executable, prog.esptool_path, "--port", port, "--baud", "115200", "read_mac"]
        else:
            cmd = [prog.esptool_path, "--port", port, "--baud", "115200", "read_mac"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        out = (result.stdout or "") + "\n" + (result.stderr or "")
        for line in out.splitlines():
            line = line.strip()
            if line.lower().startswith("mac:"):
                return line.split(":", 1)[1].strip()
        import re
        m = re.search(r"([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})", out)
        if m:
            return m.group(1)
    except Exception:
        return None
    return None


def _extract_fw_from_json(obj: Any) -> Optional[str]:
    import re
    if isinstance(obj, dict):
        # Look for common keys first
        for k in ["version", "fw_version", "firmware_version", "firmware", "fw"]:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Recurse
        for v in obj.values():
            found = _extract_fw_from_json(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_fw_from_json(item)
            if found:
                return found
    # Pattern search anywhere
    s = None
    try:
        s = json.dumps(obj)
    except Exception:
        s = str(obj)
    if s:
        m = re.search(r"v?\d+\.\d+(?:\.\d+)?", s)
        if m:
            return m.group(0)
    return None


def read_fw_version_via_serial(port: str, timeout_s: float = 3.0) -> Optional[str]:
    if serial is None:
        return None
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    try:
        ser = _open_serial_safely(port, params)
        if ser is None:
            return None
        time.sleep(1.5)
        # Ask device status first (preferred), then version fallback
        try:
            ser.write((json.dumps({"command": "get_status"}) + "\n").encode("utf-8"))
            time.sleep(0.1)
            ser.write((json.dumps({"command": "version"}) + "\n").encode("utf-8"))
        except Exception:
            pass
        deadline = time.time() + timeout_s
        buffer = ""
        while time.time() < deadline:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    # Expect JSON; try to extract firmware version string
                    try:
                        obj = json.loads(line)
                        val = _extract_fw_from_json(obj)
                        if isinstance(val, str) and val:
                            ser.close()
                            return val
                    except Exception:
                        continue
            time.sleep(0.05)
        ser.close()
    except Exception:
        return None
    return None


def _extract_hw_from_json(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        for k in [
            "hardware_version",
            "hw_version",
            "hardware",
            "hw",
            "board_revision",
            "board_rev",
            "board",
            "revision",
            "rev",
        ]:
            v = obj.get(k)
            if isinstance(v, (str, int, float)):
                return str(v)
        for v in obj.values():
            found = _extract_hw_from_json(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_hw_from_json(item)
            if found:
                return found
    return None


def read_device_info_via_serial(port: str, timeout_s: float = 3.0) -> Dict[str, Optional[str]]:
    """Return {firmware_version, hardware_version} parsed from device JSON responses."""
    info: Dict[str, Optional[str]] = {"firmware_version": None, "hardware_version": None}
    if serial is None:
        return info
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    try:
        ser = _open_serial_safely(port, params)
        if ser is None:
            return info
        time.sleep(1.5)
        try:
            ser.write((json.dumps({"command": "get_status"}) + "\n").encode("utf-8"))
            time.sleep(0.1)
            ser.write((json.dumps({"command": "version"}) + "\n").encode("utf-8"))
        except Exception:
            pass
        deadline = time.time() + timeout_s
        buffer = ""
        while time.time() < deadline and (info["firmware_version"] is None or info["hardware_version"] is None):
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if info["firmware_version"] is None:
                            fw = _extract_fw_from_json(obj)
                            if fw:
                                info["firmware_version"] = fw
                        if info["hardware_version"] is None:
                            hw = _extract_hw_from_json(obj)
                            if hw:
                                info["hardware_version"] = hw
                    except Exception:
                        continue
            time.sleep(0.05)
        ser.close()
    except Exception:
        return info
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoTQ Quick Check")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit (default)")
    parser.add_argument("--url", default="https://localhost:8000", help="API base URL for creating PCBs")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL verification (self-signed certs)")
    parser.add_argument("--api-key", help="API key for authentication (X-API-Key header)")
    parser.add_argument("--stage", choices=["factory", "post_thermal", "thermal"], help="Stage label for this run (prompts if omitted)")
    parser.add_argument("--verbose-serial", action="store_true", help="Print all serial TX/RX for debugging")
    parser.add_argument("--ppk-measure-only", action="store_true", help="Do not enable PPK source; use PPK as ammeter only")
    parser.add_argument("--thermal-cycles", type=int, default=0, help="If >0, run thermal test plan for this many cycles (use with --stage thermal)")
    parser.add_argument("--thermal-repeats", type=int, default=9, help="Repeats per temperature stage in thermal plan (default 9)")
    args = parser.parse_args()

    global VERBOSE_SERIAL
    VERBOSE_SERIAL = bool(getattr(args, 'verbose_serial', False))
    global PPK_MEASURE_ONLY
    PPK_MEASURE_ONLY = bool(getattr(args, 'ppk_measure_only', False))

    # First step: initialize PPK as a source meter at 4.2V (no resets; no power cycle)
    if PPK_MEASURE_ONLY:
        ppk_msg = "[PPK] Measure-only mode requested; not sourcing voltage."
    else:
        initialized = _auto_setup_ppk(voltage_mv=4200, power_cycle=False)
        ppk_msg = "[PPK] Configured to 4.2 V and DUT power enabled." if initialized else "[PPK] Not found or failed to initialize; continuing without PPK."
    print(ppk_msg)

    # Auto-advance when re-enumeration detected
    _wait_for_usb_reenumeration()

    firmware_dir = Path("firmware")
    latest = find_latest_version(firmware_dir)

    with suppress_output():
        prog = AutoTQFirmwareProgrammer()
        ports = prog.list_available_ports()
    esp_ports = [p for p, desc in ports if '🎯' in desc]

    if not esp_ports:
        print("No AutoTQ devices detected.")
        return 0

    # Prepare API client (lazy-auth unless --api-key provided)
    client = AutoTQClient(base_url=args.url, verify_ssl=not args.no_ssl_verify)
    if getattr(args, 'api_key', None):
        try:
            client.set_api_key(args.api_key, prompt_if_missing=False)
        except Exception:
            pass

    # Determine stage label and whether to create PCBs
    stage_label = args.stage
    if not stage_label:
        print("Select stage for this run: 1) factory  2) post_thermal  3) thermal")
        choice = (input("Enter 1, 2 or 3 [1]: ").strip() or '1')
        if choice == '1':
            stage_label = 'factory'
        elif choice == '2':
            stage_label = 'post_thermal'
        else:
            stage_label = 'thermal'
    allow_create = (stage_label == 'factory')

    # Offer visualization before testing starts
    try:
        viz_choice = input("View existing data before testing? (v=this device, a=all, Enter=skip): ").strip().lower()
    except Exception:
        viz_choice = ''
    if viz_choice in ('v', 'a'):
        if not client.is_authenticated():
            client.login()
        if viz_choice == 'a':
            visualize_all_tests(client)
        else:
            # Pick a connected device to visualize
            esp_ports = [p for p, desc in ports if '🎯' in desc]
            target_port = None
            if len(esp_ports) == 1:
                target_port = esp_ports[0]
            elif len(esp_ports) > 1:
                print("Connected devices:")
                for i, p in enumerate(esp_ports, 1):
                    print(f"  {i}. {p}")
                try:
                    sel = int(input("Select number: ").strip())
                    if 1 <= sel <= len(esp_ports):
                        target_port = esp_ports[sel-1]
                except Exception:
                    target_port = esp_ports[0]
            if target_port:
                mac_for_v = read_mac(target_port)
                if mac_for_v:
                    pcb_id_for_v = resolve_pcb_id_by_mac(client, mac_for_v)
                    if pcb_id_for_v is not None:
                        visualize_tests(client, pcb_id_for_v)
                    else:
                        print("No PCB record found for this MAC yet. Run factory stage first to create it.")
            else:
                print("No connected devices to visualize.")

    for port in esp_ports:
        # Prefer non-esptool MAC read to avoid bootloader reset
        mac = read_mac_via_status(port) or read_mac(port) or "?"
        # Pull firmware + hardware from device JSON
        dinfo = read_device_info_via_serial(port)
        fw = dinfo.get("firmware_version") or read_fw_version_via_serial(port) or "?"
        hw = dinfo.get("hardware_version") or None
        if latest and isinstance(fw, str) and fw == latest:
            print(f"[OK]  {port:<8} MAC={mac:<17} FW={fw} (up-to-date)")
        elif latest and isinstance(fw, str) and fw != "?":
            print(f"[OUT] {port:<8} MAC={mac:<17} FW={fw} (latest={latest})")
        else:
            print(f"[INFO] {port:<8} MAC={mac:<17} FW={fw}")

        pcb_id: Optional[int] = None
        # Ensure authentication if we are going to call the API
        if mac != "?" and fw != "?":
            if not client.is_authenticated():
                client.login()
            pcb = ensure_pcb_stage(client, mac, fw, hw, stage_label=stage_label, allow_create=allow_create)
            if pcb:
                pcb_id = pcb.get('id')

        # Determine repeats based on stage
        repeats = 3
        cycle_index = None
        temp_label = None
        if stage_label == 'thermal':
            repeats = max(1, int(getattr(args, 'thermal_repeats', 9)))
        results = []
        for run_idx in range(1, repeats + 1):
            measure = _run_measure_on_port(port)
            if measure:
                # Attach thermal metadata when applicable
                if stage_label == 'thermal':
                    # Expect user to set environment; we tag run index only
                    measure.setdefault('result_summary', {})
                    measure['result_summary']['thermal_run_index'] = run_idx
                results.append(measure)
                _print_measure_summary(port, measure)
                if pcb_id is not None:
                    post_measure_tests(client, pcb_id, measure, stage_label=stage_label, run_index=run_idx)
            else:
                print(f"[MEASURE-ERR] {port:<8} Unable to obtain measure_sequence result (run {run_idx})")
        # Deep sleep measurement removed per request
        if pcb_id is not None:
            show_pcb_summary(client, pcb_id)
            # Optional visualization
            try:
                choice = input("View plot (v to visualize, Enter to skip): ").strip().lower()
            except Exception:
                choice = ""
            if choice == 'v' and pcb_id is not None:
                visualize_tests(client, pcb_id)

    return 0


def ensure_pcb_stage(client: AutoTQClient, mac: str, fw: Optional[str], hw: Optional[str], stage_label: str, allow_create: bool) -> Optional[Dict[str, Any]]:
    """Upsert PCB by MAC using PUT /pcbs/by-mac/{mac}; ensure stage label and versions.
    If allow_create=False, still safe: by-mac will update existing.
    """
    try:
        body: Dict[str, Any] = {
            "name": "AutoTQ PCB",
            "current_stage_label": stage_label,
        }
        if hw:
            body["hardware_version"] = hw
        if fw:
            body["firmware_version"] = fw if fw.startswith('v') else f"v{fw}"

        # Preferred path: upsert by MAC (no /api/v1 prefix; admin/technician required per server config)
        r = client.session.put(f"{client.base_url}/pcbs/by-mac/{mac}", json=body, timeout=15)
        if r.status_code in (200, 201):
            data = r.json()
            print(f"[PCB] upserted id={data.get('id')} stage={data.get('current_stage_label')}")
            return data
        if r.status_code == 403:
            try:
                detail = r.json().get('detail')
            except Exception:
                detail = r.text
            print(f"[PCB-ERR] 403 Forbidden on upsert-by-mac: {detail}")
            return None

        # Fallback: search -> create/update using standard endpoints
        resp = api_get(client, "/pcbs", params={"q": mac, "limit": 5}, timeout=10)
        match = None
        if resp.status_code == 200:
            items = resp.json().get('items', [])
            match = next((it for it in items if (it.get('mac_address') or '').lower() == mac.lower()), None)
        if match is None and allow_create:
            create_body = {"mac_address": mac, **body}
            rc = api_post(client, "/pcbs", json=create_body, timeout=15)
            if rc.status_code in (200, 201):
                return rc.json()
            if rc.status_code == 403:
                try:
                    detail = rc.json().get('detail')
                except Exception:
                    detail = rc.text
                print(f"[PCB-ERR] 403 Forbidden on create: {detail}")
                return None
        if match is not None:
            pcb_id = match.get('id')
            ru = api_put(client, f"/pcbs/{pcb_id}", json=body, timeout=15)
            if ru.status_code in (200, 204):
                g = api_get(client, f"/pcbs/{pcb_id}", timeout=10)
                if g.status_code == 200:
                    return g.json()
            if ru.status_code == 403:
                try:
                    detail = ru.json().get('detail')
                except Exception:
                    detail = ru.text
                print(f"[PCB-ERR] 403 Forbidden on update: {detail}")
                return match
            return match
        return None
    except Exception as e:
        print(f"[PCB-ERR] {e}")
        return None


def post_measure_tests(client: AutoTQClient, pcb_id: int, data: Dict[str, Any], stage_label: str = 'factory', run_index: int = 1) -> None:
    """Create device-idle, pump, and valve tests from measure_sequence data."""
    idle = data.get('idle', {}) if isinstance(data.get('idle'), dict) else {}
    pump = data.get('pump_on', {}) if isinstance(data.get('pump_on'), dict) else {}
    valve = data.get('valve_on', {}) if isinstance(data.get('valve_on'), dict) else {}

    def _post(path: str, measured: Dict[str, Any], rindex: int) -> None:
        body = {
            'stage_label': stage_label,
            'measured_values': measured,
            'status': 'pass'
        }
        body['result_summary'] = {'type': path, 'run_index': rindex}
        # Ensure non-versioned PCB path
        r = client.session.post(f"{client.base_url}/pcbs/{pcb_id}/tests/{path}", json=body, timeout=15)
        if r.status_code in (200, 201):
            tid = r.json().get('id')
            print(f"[TEST] {path} id={tid} run={rindex}")
        else:
            try:
                detail = r.json().get('detail')
            except Exception:
                detail = r.text
            print(f"[TEST-ERR] {path} -> {r.status_code} {detail}")

    # idle
    iv = idle.get('voltage_v')
    ii = idle.get('current_a')
    measured_idle = {}
    if iv is not None:
        measured_idle['voltage_v'] = iv
    if ii is not None:
        measured_idle['current_mA'] = ii * 1000
    # Add PPK overlays if present
    if idle.get('ppk_voltage_v') is not None:
        measured_idle['ppk_voltage_v'] = idle.get('ppk_voltage_v')
    if idle.get('ppk_current_mA') is not None:
        measured_idle['ppk_current_mA'] = idle.get('ppk_current_mA')
    if idle.get('ppk_min_mA') is not None:
        measured_idle['ppk_min_mA'] = idle.get('ppk_min_mA')
    if idle.get('ppk_max_mA') is not None:
        measured_idle['ppk_max_mA'] = idle.get('ppk_max_mA')
    if measured_idle:
        _post('device-idle', measured_idle, run_index)

    # pump
    pv = pump.get('voltage_v')
    pi = pump.get('pump_driver_mA')
    measured_pump = {}
    if pv is not None:
        measured_pump['voltage_v'] = pv
    if pi is not None:
        measured_pump['pump_current_mA'] = pi
    # Also include device total current during pump if reported
    if pump.get('current_a') is not None:
        measured_pump['current_mA'] = pump.get('current_a') * 1000
    # PPK overlays
    if pump.get('ppk_voltage_v') is not None:
        measured_pump['ppk_voltage_v'] = pump.get('ppk_voltage_v')
    if pump.get('ppk_current_mA') is not None:
        measured_pump['ppk_current_mA'] = pump.get('ppk_current_mA')
    if pump.get('ppk_min_mA') is not None:
        measured_pump['ppk_min_mA'] = pump.get('ppk_min_mA')
    if pump.get('ppk_max_mA') is not None:
        measured_pump['ppk_max_mA'] = pump.get('ppk_max_mA')
    if measured_pump:
        _post('pump', measured_pump, run_index)

    # valve
    vv = valve.get('voltage_v')
    vi = valve.get('valve_driver_mA')
    measured_valve = {}
    if vv is not None:
        measured_valve['voltage_v'] = vv
    if vi is not None:
        measured_valve['valve_current_mA'] = vi
    # Also include device total current during valve if reported
    if valve.get('current_a') is not None:
        measured_valve['current_mA'] = valve.get('current_a') * 1000
    # PPK overlays
    if valve.get('ppk_voltage_v') is not None:
        measured_valve['ppk_voltage_v'] = valve.get('ppk_voltage_v')
    if valve.get('ppk_current_mA') is not None:
        measured_valve['ppk_current_mA'] = valve.get('ppk_current_mA')
    if valve.get('ppk_min_mA') is not None:
        measured_valve['ppk_min_mA'] = valve.get('ppk_min_mA')
    if valve.get('ppk_max_mA') is not None:
        measured_valve['ppk_max_mA'] = valve.get('ppk_max_mA')
    if measured_valve:
        _post('valve', measured_valve, run_index)


def show_pcb_summary(client: AutoTQClient, pcb_id: int) -> None:
    try:
        r = api_get(client, f"/pcbs/{pcb_id}", timeout=10)
        if r.status_code == 200:
            pcb = r.json()
            print(f"[PCB] id={pcb.get('id')} mac={pcb.get('mac_address')} stage={pcb.get('current_stage_label')} hw={pcb.get('hardware_version')} fw={pcb.get('firmware_version')}")
        rt = api_get(client, f"/pcbs/{pcb_id}/tests", params={"limit": 20}, timeout=10)
        if rt.status_code == 200:
            payload = rt.json()
            items = payload.get('items') if isinstance(payload, dict) else None
            if isinstance(items, list) and items:
                print("[TESTS]")
                for t in items:
                    try:
                        ttype = (t.get('result_summary') or {}).get('type') if isinstance(t, dict) else 'n/a'
                        ts = t.get('test_timestamp') if isinstance(t, dict) else None
                        status = t.get('status') if isinstance(t, dict) else None
                        mv = t.get('measured_values') if isinstance(t, dict) else None
                        print(f"  id={t.get('id')} type={ttype or 'n/a'} status={status} at={ts} measured={mv}")
                    except Exception:
                        print(f"  {t}")
    except Exception as e:
        print(f"[SUMMARY-ERR] {e}")


def resolve_pcb_id_by_mac(client: AutoTQClient, mac: str) -> Optional[int]:
    try:
        r = api_get(client, "/pcbs", params={"q": mac, "limit": 5}, timeout=10)
        if r.status_code == 200:
            items = r.json().get('items', [])
            match = next((it for it in items if (it.get('mac_address') or '').lower() == mac.lower()), None)
            return match.get('id') if match else None
    except Exception:
        return None
    return None


def visualize_tests(client: AutoTQClient, pcb_id: int) -> None:
    if not HAS_MPL:
        print("matplotlib not installed. Run: pip install matplotlib")
        return
    r = api_get(client, f"/pcbs/{pcb_id}/tests", params={"limit": 200}, timeout=15)
    if r.status_code != 200:
        print("Failed to fetch tests for visualization")
        return
    items = r.json().get('items', []) if isinstance(r.json(), dict) else []
    # Collect per type
    import datetime as dt
    series = {
        'device-idle': {'x': [], 'v': [], 'i': [], 'ppk': [], 'stage': []},
        'pump': {'x': [], 'v': [], 'i': [], 'ppk': [], 'stage': []},
        'valve': {'x': [], 'v': [], 'i': [], 'ppk': [], 'stage': []},
    }
    type_map = {'device_idle': 'device-idle', 'device-idle': 'device-idle', 'pump': 'pump', 'valve': 'valve'}
    for t in items:
        if not isinstance(t, dict):
            continue
        rs = t.get('result_summary') or {}
        ttype = rs.get('type') or t.get('type') or 'unknown'
        ttype = type_map.get(str(ttype).replace('_', '-'), str(ttype))
        if ttype not in series:
            continue
        mv = t.get('measured_values') or {}
        ts = t.get('test_timestamp')
        try:
            x = dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) if isinstance(ts, str) else None
        except Exception:
            x = None
        v = mv.get('voltage_v')
        if ttype == 'device-idle':
            i = mv.get('current_mA')
            ppk = mv.get('ppk_current_mA')
        elif ttype == 'pump':
            i = mv.get('pump_current_mA')
            ppk = mv.get('ppk_current_mA')
        else:
            i = mv.get('valve_current_mA')
            ppk = mv.get('ppk_current_mA')
        if x is not None and v is not None and i is not None:
            series[ttype]['x'].append(x)
            series[ttype]['v'].append(v)
            series[ttype]['i'].append(i)
            series[ttype]['ppk'].append(ppk)
            series[ttype]['stage'].append(t.get('stage_label') or 'unknown')

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for idx, key in enumerate(['device-idle', 'pump', 'valve']):
        ax = axes[idx]
        data = series[key]
        if not data['x']:
            ax.set_title(f"{key} (no data)")
            continue
        # Color by stage
        colors = {'factory': 'tab:blue', 'post_thermal': 'tab:orange', 'unknown': 'tab:gray'}
        c = [colors.get(s, 'tab:gray') for s in data['stage']]
        ax.plot(data['x'], data['v'], marker='o', linestyle='-', color='tab:green', label='Voltage (V)')
        ax2 = ax.twinx()
        ax2.scatter(data['x'], data['i'], c=c, label='Device current (mA)')
        # Overlay PPK if present
        if any(p is not None for p in data['ppk']):
            y_ppk = [p if isinstance(p, (int, float)) else None for p in data['ppk']]
            # Plot PPK points in red X markers, skipping None
            x_ppk = [data['x'][idx] for idx, val in enumerate(y_ppk) if val is not None]
            y_ppk2 = [val for val in y_ppk if val is not None]
            if x_ppk:
                ax2.scatter(x_ppk, y_ppk2, marker='x', color='tab:red', label='PPK current (mA)')
        ax.set_ylabel('Voltage (V)')
        ax2.set_ylabel('Current (mA)')
        ax.set_title(key)
        # Legend with stage tags
        from matplotlib.lines import Line2D
        handles = [Line2D([0], [0], color='tab:green', label='Voltage (V)'),
                   Line2D([0], [0], marker='o', color='w', markerfacecolor='tab:blue', label='factory', markersize=8),
                   Line2D([0], [0], marker='o', color='w', markerfacecolor='tab:orange', label='post_thermal', markersize=8),
                   Line2D([0], [0], marker='x', color='tab:red', label='PPK current', markersize=8)]
        ax.legend(handles=handles, loc='upper left')
    plt.tight_layout()
    plt.show()


def _find_ppk_comport() -> Optional[str]:
    """Try to find Nordic PPK/PPK2 serial port by VID:PID=1915:C00A or known description.
    Returns a COM port string like 'COM44' or None if not found.
    """
    try:
        if list_ports is None:
            return None
        ports = list(list_ports.comports())
        # Prefer VID:PID match
        for p in ports:
            try:
                if getattr(p, 'vid', None) == 0x1915 and getattr(p, 'pid', None) == 0xC00A:
                    return p.device
            except Exception:
                continue
        # Fallback: description contains nRF Connect USB CDC ACM
        for p in ports:
            desc = (getattr(p, 'description', '') or '').lower()
            if 'nrf connect usb cdc acm' in desc or 'ppk' in desc:
                return p.device
        # If COM44 is present, use it
        for p in ports:
            if str(p.device).upper() == 'COM44':
                return p.device
    except Exception:
        pass
    # Last resort: try COM44 if on Windows
    return 'COM44'


def _auto_setup_ppk(voltage_mv: int = 4200, power_cycle: bool = False) -> bool:
    """Auto-detect and configure PPK at given voltage; optionally power-cycle DUT.
    Returns True if PPK was found and configured, else False.
    """
    global GLOBAL_PPK
    if PPK2_API is None:
        return False
    try:
        port = _find_ppk_comport()
        if not port:
            return False
        # Reuse existing connection if already opened on same port
        if GLOBAL_PPK is not None:
            ppk = GLOBAL_PPK
        else:
            ppk = PPK2_API(port)
            GLOBAL_PPK = ppk
        try:
            try:
                ppk.get_modifiers()
            except Exception:
                pass
            if PPK_MEASURE_ONLY:
                # Meter-only: disable source and just sample current
                try:
                    ppk.use_ampere_meter()
                except Exception:
                    # Some APIs: use_meas_amperage()
                    try:
                        ppk.use_meas_amperage()  # type: ignore
                    except Exception:
                        pass
                try:
                    ppk.toggle_DUT_power("OFF")
                except Exception:
                    try:
                        ppk.toggle_DUT_power(False)  # type: ignore
                    except Exception:
                        pass
                try:
                    ppk.start_measuring()
                except Exception:
                    pass
            else:
                # Source mode at 4.2V: power the pump drivers
                ppk.use_source_meter()
                ppk.set_source_voltage(int(voltage_mv))
                # Attempt to remove current limit if API supports it
                try:
                    ppk.set_source_current_limit(0)  # 0 often means unlimited in APIs
                except Exception:
                    try:
                        ppk.set_current_limit(0)  # alternate naming
                    except Exception:
                        pass
                try:
                    ppk.start_measuring()
                except Exception:
                    pass
                # Ensure power is on
                try:
                    ppk.toggle_DUT_power("ON")
                except Exception:
                    try:
                        ppk.toggle_DUT_power(True)  # type: ignore
                    except Exception:
                        pass
            if power_cycle:
                # Brief power cycle: off then on
                try:
                    ppk.toggle_DUT_power("OFF")
                except Exception:
                    try:
                        ppk.toggle_DUT_power(False)  # type: ignore
                    except Exception:
                        pass
                time.sleep(0.3)
                try:
                    ppk.toggle_DUT_power("ON")
                except Exception:
                    try:
                        ppk.toggle_DUT_power(True)  # type: ignore
                    except Exception:
                        pass
                time.sleep(0.2)
            return True
        finally:
            # Do not stop measuring here; keep session active to maintain power
            pass
    except Exception:
        return False


def _reset_esp32_devices(esp_ports: List[str]) -> None:
    """Toggle DTR/RTS to reset ESP32-S3 on each provided port."""
    if serial is None:
        return
    for port in esp_ports:
        try:
            params = AutoTQDeviceProgrammer.SERIAL_PARAMS
            ser = serial.Serial(port, **params)
            try:
                # Clear buffers before reset
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass
                time.sleep(0.05)
                # Typical ESP32 auto-reset: assert RTS (EN low), deassert DTR (GPIO0 high), then release RTS
                ser.dtr = False
                ser.rts = True
                time.sleep(0.05)
                ser.rts = False
                time.sleep(0.3)
                # After reset, give boot ROM time, then clear buffers again
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
            print(f"[RESET] Toggled DTR/RTS on {port}")
        except Exception as e:
            print(f"[RESET-ERR] {port}: {e}")


def _run_ppk_current_monitor(port: Optional[str] = None) -> None:
    """Initialize PPK, set 4.2V, enable power, and print 1-second average current until Ctrl+C."""
    if PPK2_API is None:
        print("ppk2_api not installed. Run: pip install ppk2_api")
        return
    try:
        ppk_port = port or _find_ppk_comport()
        if not ppk_port:
            print("Could not find PPK COM port. Specify manually or check connection.")
            return
        print(f"Initializing PPK on {ppk_port} ...")
        ppk = PPK2_API(ppk_port)
        try:
            # Configure as source meter and set voltage
            try:
                ppk.get_modifiers()
            except Exception:
                pass
            ppk.use_source_meter()
            ppk.set_source_voltage(4200)
            # Enable DUT power and start measuring
            try:
                ppk.toggle_DUT_power("ON")
            except Exception:
                # Some versions accept boolean
                try:
                    ppk.toggle_DUT_power(True)  # type: ignore
                except Exception:
                    pass
            ppk.start_measuring()
            print("PPK output set to 4.2 V. Logging average current every 1s. Press Ctrl+C to stop.")
            while True:
                window_start = time.time()
                total_microamps = 0.0
                total_samples = 0
                # Accumulate samples for ~1s
                while (time.time() - window_start) < 1.0:
                    try:
                        data_chunk = ppk.get_data()
                        if data_chunk:
                            samples, _ = ppk.get_samples(data_chunk)
                            if samples:
                                total_microamps += float(sum(samples))
                                total_samples += len(samples)
                    except Exception:
                        # Short sleep to avoid tight loop on errors
                        time.sleep(0.01)
                    # Yield briefly to avoid hogging CPU
                    time.sleep(0.01)
                if total_samples > 0:
                    avg_ma = (total_microamps / total_samples) / 1000.0
                    print(f"Avg current: {avg_ma:.3f} mA")
                else:
                    print("Avg current: n/a (no samples)")
        except KeyboardInterrupt:
            print("\nStopping PPK measurement...")
        finally:
            try:
                ppk.stop_measuring()
            except Exception:
                pass
            try:
                ppk.toggle_DUT_power("OFF")
            except Exception:
                try:
                    ppk.toggle_DUT_power(False)  # type: ignore
                except Exception:
                    pass
            print("PPK stopped and DUT power disabled.")
    except Exception as e:
        print(f"PPK error: {e}")


def visualize_all_tests(client: AutoTQClient) -> None:
    if not HAS_MPL:
        print("matplotlib not installed. Run: pip install matplotlib")
        return
    # Fetch many PCBs
    pcbs = []
    try:
        r = api_get(client, "/pcbs", params={"limit": 200, "offset": 0}, timeout=20)
        if r.status_code == 200:
            pcbs = r.json().get('items', [])
    except Exception:
        pass
    if not pcbs:
        print("No PCBs found to visualize.")
        return
    # Aggregate across PCBs
    import datetime as dt
    series = {
        'device-idle': {'x': [], 'i': [], 'ppk': [], 'stage': []},
        'pump': {'x': [], 'i': [], 'ppk': [], 'stage': []},
        'valve': {'x': [], 'i': [], 'ppk': [], 'stage': []},
    }
    type_map = {'device_idle': 'device-idle', 'device-idle': 'device-idle', 'pump': 'pump', 'valve': 'valve'}
    for pcb in pcbs:
        pid = pcb.get('id')
        if pid is None:
            continue
        try:
            rt = api_get(client, f"/pcbs/{pid}/tests", params={"limit": 200}, timeout=15)
            if rt.status_code != 200:
                continue
            items = rt.json().get('items', []) if isinstance(rt.json(), dict) else []
            for t in items:
                if not isinstance(t, dict):
                    continue
                rs = t.get('result_summary') or {}
                ttype = rs.get('type') or t.get('type') or 'unknown'
                ttype = type_map.get(str(ttype).replace('_', '-'), str(ttype))
                if ttype not in series:
                    continue
                mv = t.get('measured_values') or {}
                ts = t.get('test_timestamp')
                try:
                    x = dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) if isinstance(ts, str) else None
                except Exception:
                    x = None
                if ttype == 'device-idle':
                    i = mv.get('current_mA')
                    ppk = mv.get('ppk_current_mA')
                elif ttype == 'pump':
                    i = mv.get('pump_current_mA')
                    ppk = mv.get('ppk_current_mA')
                else:
                    i = mv.get('valve_current_mA')
                    ppk = mv.get('ppk_current_mA')
                if x is not None and i is not None:
                    series[ttype]['x'].append(x)
                    series[ttype]['i'].append(i)
                    series[ttype]['ppk'].append(ppk)
                    series[ttype]['stage'].append(t.get('stage_label') or 'unknown')
        except Exception:
            continue
    # Plot currents over time for each test type
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for idx, key in enumerate(['device-idle', 'pump', 'valve']):
        ax = axes[idx]
        data = series[key]
        if not data['x']:
            ax.set_title(f"{key} (no data)")
            continue
        colors = {'factory': 'tab:blue', 'post_thermal': 'tab:orange', 'unknown': 'tab:gray'}
        c = [colors.get(s, 'tab:gray') for s in data['stage']]
        ax.scatter(data['x'], data['i'], c=c, label='Device current (mA)')
        if any(p is not None for p in data['ppk']):
            x_ppk = [data['x'][idx] for idx, val in enumerate(data['ppk']) if val is not None]
            y_ppk = [val for val in data['ppk'] if val is not None]
            if x_ppk:
                ax.scatter(x_ppk, y_ppk, marker='x', color='tab:red', label='PPK current (mA)')
        ax.set_ylabel('Current (mA)')
        ax.set_title(f"{key} current vs time (all units)")
    plt.tight_layout()
    plt.show()


def _run_measure_on_port(port: str, timeout_s: float = 20.0) -> Optional[Dict[str, Any]]:
    if serial is None:
        return None
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    try:
        ser = _open_serial_safely(port, params)
        if ser is None:
            return None
        time.sleep(2)
    except Exception:
        return None
    try:
        # Pre-measurement: clear buffers and small delay to avoid stale data
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass
        time.sleep(0.05)
        # Timings used by device side; also used to window PPK averages
        settle_ms = 500
        pump_ms = 3000
        valve_ms = 2000
        total_ms = settle_ms + pump_ms + valve_ms
        cmd = {"command": "measure_sequence", "settle_ms": settle_ms, "pump_ms": pump_ms, "valve_ms": valve_ms}
        payload = (json.dumps(cmd) + "\n").encode("utf-8")
        if VERBOSE_SERIAL:
            print(f"[TX] {payload.decode('utf-8', errors='ignore').strip()}")
        ser.write(payload)
        start_time = time.time()
        deadline = start_time + timeout_s
        # Prepare PPK accumulation windows (middle 50% of each phase) if PPK active
        ppk = GLOBAL_PPK
        ppk_windows = None
        ppk_mid_windows = None  # time windows (start_s, end_s) in absolute time
        last_ppk_fetch_time = None
        if ppk is not None:
            ppk_windows = {
                'idle': {'sum_ua': 0.0, 'count': 0, 'v_mv': GLOBAL_PPK_VOLTAGE_MV, 'min_ua': None, 'max_ua': None},
                'pump_on': {'sum_ua': 0.0, 'count': 0, 'v_mv': GLOBAL_PPK_VOLTAGE_MV, 'min_ua': None, 'max_ua': None},
                'valve_on': {'sum_ua': 0.0, 'count': 0, 'v_mv': GLOBAL_PPK_VOLTAGE_MV, 'min_ua': None, 'max_ua': None},
            }
            # Compute absolute mid-windows based on device timing model
            settle_s = settle_ms / 1000.0
            pump_window_s = max(0.0, (pump_ms - settle_ms) / 1000.0)
            valve_window_s = max(0.0, (valve_ms - settle_ms) / 1000.0)
            idle_start = start_time + 0.25 * settle_s
            idle_end = start_time + 0.75 * settle_s
            pump_start = start_time + 2.0 * settle_s
            pump_mid_start = pump_start + 0.25 * pump_window_s
            pump_mid_end = pump_start + 0.75 * pump_window_s
            valve_start = pump_start + pump_window_s + 2.0 * settle_s
            valve_mid_start = valve_start + 0.25 * valve_window_s
            valve_mid_end = valve_start + 0.75 * valve_window_s
            ppk_mid_windows = {
                'idle': (idle_start, idle_end) if idle_end > idle_start else None,
                'pump_on': (pump_mid_start, pump_mid_end) if pump_mid_end > pump_mid_start else None,
                'valve_on': (valve_mid_start, valve_mid_end) if valve_mid_end > valve_mid_start else None,
            }
        # Helper to update PPK windows distributing samples across elapsed time since last read
        def _ppk_update() -> None:
            nonlocal last_ppk_fetch_time
            if ppk is None:
                return
            try:
                data_chunk = ppk.get_data()
                if not data_chunk:
                    return
                samples, _ = ppk.get_samples(data_chunk)
                if not samples:
                    return
                now = time.time()
                # Distribute samples uniformly across interval since previous fetch
                if last_ppk_fetch_time is None:
                    last_ppk_fetch_time = now
                    # Without a previous timestamp, distribute only samples that land within mid-windows
                    n0 = len(samples)
                    if ppk_mid_windows is not None and n0 > 0:
                        # Assume samples spread over a short default span (e.g., 10 ms) to place them near 'now'
                        dt0 = 0.01
                        dt_per0 = dt0 / n0
                        for idx, ua in enumerate(samples):
                            t_sample = now - dt0 + (idx + 0.5) * dt_per0
                            for bucket, bounds in (ppk_mid_windows.items() if ppk_mid_windows else []):
                                if not bounds:
                                    continue
                                start_w, end_w = bounds
                                if start_w <= t_sample <= end_w:
                                    win = ppk_windows[bucket]
                                    win['sum_ua'] += float(ua)
                                    win['count'] += 1
                                    if win['min_ua'] is None or ua < win['min_ua']:
                                        win['min_ua'] = float(ua)
                                    if win['max_ua'] is None or ua > win['max_ua']:
                                        win['max_ua'] = float(ua)
                    return
                dt = max(0.0, now - last_ppk_fetch_time)
                last_ppk_fetch_time = now
                n = len(samples)
                if n == 0 or dt <= 0:
                    return
                dt_per = dt / n
                # Assign each sample to bucket by its estimated capture time
                for idx, ua in enumerate(samples):
                    t_sample = now - dt + (idx + 0.5) * dt_per
                    # Use mid-windows only
                    if ppk_mid_windows is None:
                        continue
                    for bucket, bounds in ppk_mid_windows.items():
                        if not bounds:
                            continue
                        start_w, end_w = bounds
                        if start_w <= t_sample <= end_w:
                            win = ppk_windows[bucket]
                            win['sum_ua'] += float(ua)
                            win['count'] += 1
                            if win['min_ua'] is None or ua < win['min_ua']:
                                win['min_ua'] = float(ua)
                            if win['max_ua'] is None or ua > win['max_ua']:
                                win['max_ua'] = float(ua)
            except Exception:
                pass
        buffer = ""
        while time.time() < deadline:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                if VERBOSE_SERIAL and data:
                    for line in data.splitlines():
                        if line.strip():
                            print(f"[RX] {line.strip()}")
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("command") == "measure_sequence" and obj.get("status"):
                            # Attach PPK averages if available
                            if ppk_windows is not None:
                                for key in ('idle', 'pump_on', 'valve_on'):
                                    w = ppk_windows.get(key) or {}
                                    cnt = w.get('count') or 0
                                    if cnt > 0:
                                        avg_ma = (w.get('sum_ua', 0.0) / cnt) / 1000.0
                                        v_v = (w.get('v_mv') or 0) / 1000.0
                                        obj.setdefault(key, {})['ppk_current_mA'] = avg_ma
                                        obj.setdefault(key, {})['ppk_voltage_v'] = v_v
                                        # Also include min/max within the middle window
                                        min_ma = (w.get('min_ua') / 1000.0) if w.get('min_ua') is not None else None
                                        max_ma = (w.get('max_ua') / 1000.0) if w.get('max_ua') is not None else None
                                        if min_ma is not None:
                                            obj.setdefault(key, {})['ppk_min_mA'] = min_ma
                                        if max_ma is not None:
                                            obj.setdefault(key, {})['ppk_max_mA'] = max_ma
                            return obj
                    except Exception:
                        continue
            # Poll PPK as fast as practical
            _ppk_update()
            time.sleep(0.001)
        return None
    finally:
        try:
            ser.close()
        except Exception:
            pass


def _print_measure_summary(port: str, data: Dict[str, Any]) -> None:
    idle = data.get("idle", {}) if isinstance(data.get("idle"), dict) else {}
    pump = data.get("pump_on", {}) if isinstance(data.get("pump_on"), dict) else {}
    valve = data.get("valve_on", {}) if isinstance(data.get("valve_on"), dict) else {}
    iv = idle.get("voltage_v")
    ii = idle.get("current_a")
    pv = pump.get("voltage_v")
    pi = pump.get("pump_driver_mA")
    vv = valve.get("voltage_v")
    vi = valve.get("valve_driver_mA")
    # PPK overlays (if present)
    ip_ma = idle.get("ppk_current_mA")
    iv_v = idle.get("ppk_voltage_v")
    ip_min = idle.get("ppk_min_mA")
    ip_max = idle.get("ppk_max_mA")
    pp_ma = pump.get("ppk_current_mA")
    pv_v_ppk = pump.get("ppk_voltage_v")
    pp_min = pump.get("ppk_min_mA")
    pp_max = pump.get("ppk_max_mA")
    vp_ma = valve.get("ppk_current_mA")
    vv_v_ppk = valve.get("ppk_voltage_v")
    vp_min = valve.get("ppk_min_mA")
    vp_max = valve.get("ppk_max_mA")
    # Print concise, single line
    base = f"[MEASURE] {port:<8} "
    def _fmt_v(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "?"
    def _fmt_i_ma(i):
        return f"{i:.2f}" if isinstance(i, (int, float)) else "?"
    # Device values
    idle_part = f"idle: V={_fmt_v(iv)} I={_fmt_i_ma(ii*1000 if isinstance(ii, (int, float)) else None)}mA"
    pump_part = f"pump: V={_fmt_v(pv)} I={_fmt_i_ma(pi)}mA"
    valve_part = f"valve: V={_fmt_v(vv)} I={_fmt_i_ma(vi)}mA"
    # Append PPK values if available
    if ip_ma is not None or iv_v is not None:
        extra = f" [PPK V={_fmt_v(iv_v)} I={_fmt_i_ma(ip_ma)}mA"
        if ip_min is not None and ip_max is not None:
            extra += f" min={_fmt_i_ma(ip_min)} max={_fmt_i_ma(ip_max)}"
        idle_part += extra + "]"
    if pp_ma is not None or pv_v_ppk is not None:
        extra = f" [PPK V={_fmt_v(pv_v_ppk)} I={_fmt_i_ma(pp_ma)}mA"
        if pp_min is not None and pp_max is not None:
            extra += f" min={_fmt_i_ma(pp_min)} max={_fmt_i_ma(pp_max)}"
        pump_part += extra + "]"
    if vp_ma is not None or vv_v_ppk is not None:
        extra = f" [PPK V={_fmt_v(vv_v_ppk)} I={_fmt_i_ma(vp_ma)}mA"
        if vp_min is not None and vp_max is not None:
            extra += f" min={_fmt_i_ma(vp_min)} max={_fmt_i_ma(vp_max)}"
        valve_part += extra + "]"
    print(base + idle_part + " | " + pump_part + " | " + valve_part)


def send_sleep_command(port: str, timeout_s: float = 3.0, seconds: int = 0, defer_until_usb_unplug: bool = True) -> bool:
    """Ask device to enter low-power sleep using the shutdown command.
    If defer_until_usb_unplug is True and USB is connected, device defers sleep until unplug.
    """
    if serial is None:
        return False
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    ser = None
    try:
        ser = _open_serial_safely(port, params)
        if ser is None:
            return False
        time.sleep(0.05)
        cmd = {"command": "shutdown", "seconds": int(seconds), "defer_until_usb_unplug": bool(defer_until_usb_unplug)}
        try:
            ser.reset_output_buffer()
            ser.write((json.dumps(cmd) + "\n").encode("utf-8"))
            ser.flush()
            time.sleep(0.05)
        except Exception:
            return False
        # Optionally wait briefly for any ack
        t_end = time.time() + max(0.2, timeout_s)
        while time.time() < t_end:
            try:
                if ser.in_waiting > 0:
                    _ = ser.read(ser.in_waiting)
            except Exception:
                break
            time.sleep(0.05)
        return True
    except Exception:
        return False
    finally:
        try:
            if ser:
                ser.close()
        except Exception:
            pass

def run_ppk_sleep_measure(duration_s: float = 3.0, live_plot: bool = False, discard_initial_s: float = 0.0) -> Optional[Dict[str, Any]]:
    """Measure average current using PPK only for a quiet/sleep window.
    If live_plot is True and matplotlib is available, plot current in real time.
    Returns measured dict with ppk averages or None if PPK not available.
    """
    ppk = GLOBAL_PPK
    if ppk is None:
        return None
    try:
        # Ensure meter is running
        try:
            ppk.start_measuring()
        except Exception:
            pass
        t_end = time.time() + max(0.2, duration_s)
        sum_ua = 0.0
        cnt = 0
        min_ua = None
        max_ua = None
        # Live plot setup and time tracking (independent of plotting)
        fig = None
        ax = None
        line = None
        xs: list = []
        ys: list = []
        t0 = time.time()
        last_fetch_time: Optional[float] = None
        rel_time_s: float = 0.0  # advances regardless of live_plot
        if live_plot and HAS_MPL:
            try:
                import matplotlib.pyplot as _plt  # type: ignore
                _plt.ion()
                fig, ax = _plt.subplots(1, 1)
                ax.set_title("PPK Sleep Current (mA)")
                ax.set_xlabel("Time (s)")
                ax.set_ylabel("Current (mA)")
                line, = ax.plot([], [], lw=1.0)
                ax.set_xlim(0, duration_s)
                ax.set_ylim(0, 5)
            except Exception:
                fig = None
                ax = None
                line = None
        while time.time() < t_end:
            try:
                data_chunk = ppk.get_data()
                if not data_chunk:
                    time.sleep(0.001)
                    continue
                samples, _ = ppk.get_samples(data_chunk)
                now = time.time()
                n = len(samples or [])
                if n > 0:
                    # Distribute samples uniformly across time since last fetch
                    if last_fetch_time is None:
                        dt = max(0.001, now - t0)
                    else:
                        dt = max(0.001, now - last_fetch_time)
                    last_fetch_time = now
                    dt_per = dt / n
                    for _idx, ua in enumerate(samples or []):
                        val = float(ua)
                        rel_time_s += dt_per
                        # Accumulate stats only after discard window
                        if rel_time_s >= max(0.0, discard_initial_s):
                            sum_ua += val
                            cnt += 1
                            if min_ua is None or val < min_ua:
                                min_ua = val
                            if max_ua is None or val > max_ua:
                                max_ua = val
                        if live_plot and line is not None:
                            xs.append(rel_time_s)
                            ys.append(val / 1000.0)
                    if live_plot and line is not None:
                        try:
                            # Update plot
                            line.set_data(xs, ys)
                            if ax is not None:
                                ax.set_xlim(0, max(duration_s, xs[-1] if xs else duration_s))
                                # Auto-scale Y to data range with some headroom
                                ymin = 0.0
                                ymax = max(5.0, max(ys) * 1.1 if ys else 5.0)
                                ax.set_ylim(ymin, ymax)
                            import matplotlib.pyplot as _plt  # type: ignore
                            _plt.pause(0.001)
                        except Exception:
                            pass
            except Exception:
                time.sleep(0.001)
                continue
        if cnt == 0:
            return None
        avg_ma = (sum_ua / cnt) / 1000.0
        v_v = (GLOBAL_PPK_VOLTAGE_MV or 0) / 1000.0
        measured = {
            'ppk_voltage_v': v_v,
            'ppk_current_mA': avg_ma,
            'ppk_min_mA': (min_ua / 1000.0) if min_ua is not None else None,
            'ppk_max_mA': (max_ua / 1000.0) if max_ua is not None else None,
            'window_s': duration_s,
        }
        # Close plot window if we created one
        if live_plot and HAS_MPL and fig is not None:
            try:
                import matplotlib.pyplot as _plt  # type: ignore
                _plt.ioff()
                _plt.show(block=False)
                _plt.close(fig)
            except Exception:
                pass
        return measured
    except Exception:
        return None


def post_power_test(client: AutoTQClient, pcb_id: int, measured: Dict[str, Any], stage_label: str = 'factory', run_index: int = 1) -> None:
    body = {
        'stage_label': stage_label,
        'measured_values': measured,
        'status': 'pass',
        'result_summary': {'type': 'power', 'run_index': run_index}
    }
    r = client.session.post(f"{client.base_url}/pcbs/{pcb_id}/tests/power", json=body, timeout=15)
    if r.status_code in (200, 201):
        tid = r.json().get('id')
        print(f"[TEST] power id={tid} run={run_index}")
    else:
        try:
            detail = r.json().get('detail')
        except Exception:
            detail = r.text
        print(f"[TEST-ERR] power -> {r.status_code} {detail}")


if __name__ == "__main__":
    raise SystemExit(main())


