#!/usr/bin/env python3
"""
AutoTQ PCBs CLI

Interactive and scripted CLI for managing PCBs and their tests via the server API.
This tool reuses the auth token flow provided by autotq_client.AutoTQClient
(loads/saves token in autotq_token.json and attaches Authorization headers).

Commands:
  - list                 List/search PCBs
  - create               Create a new PCB (interactive if fields omitted)
  - get                  Get a PCB by id
  - tests                List tests for a PCB
  - test-create          Create a test for a PCB (interactive if fields omitted)
  - interactive          Start interactive text UI

Usage examples:
  python autotq_pcbs_cli.py list --stage bringup --limit 20
  python autotq_pcbs_cli.py create --mac AA:BB:CC:DD:EE:FF --name PCB-23
  python autotq_pcbs_cli.py get --id 123
  python autotq_pcbs_cli.py tests --id 123 --type valve
  python autotq_pcbs_cli.py test-create --id 123 --type pump --measured "current_mA=420,pressure_kPa=55" --status pass
"""

import argparse
import json
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple
import time
import threading

try:
    import serial  # type: ignore
except Exception:
    serial = None  # Will warn at runtime if used without install

from autotq_client import AutoTQClient
from urllib.parse import urlparse, urlunparse
from contextlib import redirect_stdout, redirect_stderr
import io
# Thread-safe registry of currently detected devices
# Thread-safe registry of currently detected devices
from autotq_firmware_programmer import AutoTQFirmwareProgrammer
from autotq_device_programmer import AutoTQDeviceProgrammer
import math

# Remember the last detected MAC during watch mode to prefill Create PCB
LAST_DETECTED_MAC: Optional[str] = None

# Thread-safe registry of currently detected devices
DEVICE_REGISTRY: Dict[str, Dict[str, Any]] = {}
DEVICE_LOCK = threading.Lock()
WATCHER_THREAD: Optional[threading.Thread] = None
WATCHER_STOP = threading.Event()


def ensure_authenticated(client: AutoTQClient, username: Optional[str], password: Optional[str]) -> bool:
    if client.is_authenticated():
        return True
    return client.login(username=username, password=password)


def parse_key_value_pairs(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if not text:
        return result
    pairs = [p for p in text.split(',') if p.strip()]
    for pair in pairs:
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Try to coerce to int or float; otherwise keep string
        try:
            if value.lower() in ["true", "false"]:
                coerced: Any = value.lower() == "true"
            elif value.startswith('0') and value != '0' and not value.startswith('0.'):
                coerced = value
            elif '.' in value or 'e' in value.lower():
                coerced = float(value)
            else:
                coerced = int(value)
        except Exception:
            coerced = value
        result[key] = coerced
    return result


def prompt_nonempty(prompt_text: str) -> str:
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        print("Value cannot be empty.")


def prompt_with_default(prompt_text: str, default_value: Optional[str]) -> str:
    if default_value:
        text = input(f"{prompt_text} [{default_value}]: ").strip()
        return text or default_value
    return prompt_nonempty(prompt_text)


class suppress_output:
    """Context manager to temporarily silence stdout/stderr."""
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


def api_get(client: AutoTQClient, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        resp = client.session.get(f"{client.base_url}{path}", params=params, timeout=30)
        if resp.status_code in [200]:
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        print(f"❌ GET {path} failed: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        print(f"❌ GET {path} error: {e}")
        return None


def api_post(client: AutoTQClient, path: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        resp = client.session.post(f"{client.base_url}{path}", json=body, timeout=30)
        if resp.status_code in [200, 201]:
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        print(f"❌ POST {path} failed: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        print(f"❌ POST {path} error: {e}")
        return None


def cmd_list(client: AutoTQClient, args: argparse.Namespace) -> int:
    params: Dict[str, Any] = {}
    if args.q:
        params["q"] = args.q
    if args.stage:
        params["stage"] = args.stage
    if args.device_id is not None:
        params["device_id"] = args.device_id
    params["limit"] = args.limit
    params["offset"] = args.offset

    data = api_get(client, "/pcbs", params)
    if not data:
        return 1

    total = data.get("total")
    items = data.get("items", [])
    print(f"Total: {total} | Showing {len(items)}")
    for pcb in items:
        print(f"- id={pcb.get('id')} mac={pcb.get('mac_address')} name={pcb.get('name')} stage={pcb.get('current_stage_label')} fw={pcb.get('firmware_version')}")
    return 0


def cmd_get(client: AutoTQClient, args: argparse.Namespace) -> int:
    data = api_get(client, f"/pcbs/{args.id}")
    if not data:
        return 1
    print(json.dumps(data, indent=2))
    return 0


def _list_current_macs() -> List[Tuple[str, str]]:
    """Return list of (mac, port). Only items with a known MAC are included."""
    with DEVICE_LOCK:
        items = []
        for port, info in DEVICE_REGISTRY.items():
            mac = info.get("mac")
            if mac:
                items.append((mac, port))
        return items


def select_mac_from_devices(prompt_title: str = "Select MAC") -> Optional[str]:
    items = _list_current_macs()
    if not items:
        print("⚠️ No connected devices with known MACs.")
        return None
    print(f"\n{prompt_title}:")
    for idx, (mac, port) in enumerate(items, 1):
        print(f"  {idx}. {mac} ({port})")
    try:
        choice = input("Enter number (or blank to cancel): ").strip()
        if not choice:
            return None
        n = int(choice)
        if 1 <= n <= len(items):
            return items[n-1][0]
    except Exception:
        pass
    print("❌ Invalid selection")
    return None


def cmd_create(client: AutoTQClient, args: argparse.Namespace) -> int:
    mac = args.mac or prompt_with_default("MAC address", LAST_DETECTED_MAC or select_mac_from_devices() or LAST_DETECTED_MAC)
    # Default PCB name to "AutoTQ PCB"
    default_name = args.name or "AutoTQ PCB"
    name = prompt_with_default("Name", default_name)
    hw = args.hardware_version or input("Hardware version (optional): ").strip() or None
    fw = args.firmware_version or input("Firmware version (optional): ").strip() or None
    stage = args.stage or input("Current stage label (optional): ").strip() or None
    device_gs1 = args.device_gs1 or input("Device GS1 (optional): ").strip() or None
    device_id = args.device_id

    body: Dict[str, Any] = {
        "mac_address": mac,
        "name": name,
    }
    if hw:
        body["hardware_version"] = hw
    if fw:
        body["firmware_version"] = fw
    if stage:
        body["current_stage_label"] = stage
    if device_gs1:
        body["device_gs1"] = device_gs1
    if device_id is not None:
        body["device_id"] = device_id

    data = api_post(client, "/pcbs", body)
    if not data:
        return 1
    print("✅ PCB created:")
    print(json.dumps(data, indent=2))
    return 0


def cmd_tests(client: AutoTQClient, args: argparse.Namespace) -> int:
    params: Dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.type:
        params["type"] = args.type
    data = api_get(client, f"/pcbs/{args.id}/tests", params)
    if not data:
        return 1
    items = data.get("items", [])
    print(f"Found {len(items)} test(s)")
    for t in items:
        ttype = t.get('result_summary', {}).get('type') or args.type or 'unknown'
        print(f"- id={t.get('id')} type={ttype} status={t.get('status')} at={t.get('test_timestamp')}")
    return 0


def _prompt_measured_values(existing: Optional[str]) -> Dict[str, Any]:
    if existing:
        return parse_key_value_pairs(existing)
    print("Enter measured values as key=value pairs separated by commas (e.g., current_mA=420,pressure_kPa=55)")
    text = input("Measured values: ").strip()
    return parse_key_value_pairs(text)


def _prompt_result_summary(existing: Optional[str]) -> Dict[str, Any]:
    if existing:
        try:
            return json.loads(existing)
        except Exception:
            pass
    print("Optional: Enter result_summary JSON (or leave blank)")
    text = input("result_summary JSON: ").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        print("Invalid JSON. Ignoring result_summary.")
        return {}


def cmd_test_create(client: AutoTQClient, args: argparse.Namespace) -> int:
    test_type = args.type
    if not test_type:
        print("Choose test type: pump | valve | device-active | device-idle | power")
        test_type = prompt_nonempty("Type: ")

    # Normalize path name
    path_type = test_type.strip().lower().replace('_', '-').replace(' ', '-')
    if path_type not in ["pump", "valve", "device-active", "device-idle", "power"]:
        print("❌ Invalid test type")
        return 1

    # Determine PCB id; if not provided, allow selection via MAC
    pcb_id = getattr(args, 'id', None)
    if pcb_id is None:
        chosen_mac = select_mac_from_devices("Choose device for test (by MAC)") or LAST_DETECTED_MAC
        if chosen_mac:
            # Try to resolve PCB by mac
            search = api_get(client, "/pcbs", {"q": chosen_mac, "limit": 10, "offset": 0})
            items = (search or {}).get("items", [])
            candidates = [it for it in items if (it.get("mac_address") or "").lower() == chosen_mac.lower()]
            if len(candidates) == 1:
                pcb_id = candidates[0].get("id")
                print(f"🔗 Using PCB id {pcb_id} for MAC {chosen_mac}")
            elif len(candidates) > 1:
                print("Multiple PCBs match this MAC:")
                for i, it in enumerate(candidates, 1):
                    print(f"  {i}. id={it.get('id')} name={it.get('name')}")
                try:
                    sel = int(input("Pick number: ").strip())
                    if 1 <= sel <= len(candidates):
                        pcb_id = candidates[sel-1].get("id")
                except Exception:
                    pass
        if pcb_id is None:
            try:
                pcb_id = int(input("PCB id (no match found, enter id): ").strip())
            except Exception:
                print("❌ Need a PCB id to create a test")
                return 1

    stage_label = args.stage_label or input("Stage label (optional): ").strip() or None
    status = args.status or input("Status (pass/fail/warn) (optional): ").strip() or None
    measured = _prompt_measured_values(args.measured)
    result_summary = _prompt_result_summary(args.result_summary) if args.result_summary or input("Add result_summary JSON? (y/N): ").strip().lower() == 'y' else {}

    timestamp = args.test_timestamp
    if not timestamp:
        ts_choice = input("Use current time for test_timestamp? (Y/n): ").strip().lower()
        if ts_choice in ["", "y", "yes"]:
            timestamp = datetime.utcnow().isoformat() + "Z"
        else:
            timestamp = input("Enter ISO-8601 timestamp (e.g., 2025-01-01T12:34:56Z): ").strip() or None

    body: Dict[str, Any] = {
        "measured_values": measured,
    }
    if stage_label:
        body["stage_label"] = stage_label
    if status:
        body["status"] = status
    if result_summary:
        body["result_summary"] = result_summary
    if timestamp:
        body["test_timestamp"] = timestamp

    data = api_post(client, f"/pcbs/{pcb_id}/tests/{path_type}", body)
    if not data:
        return 1
    print("✅ Test created:")
    print(json.dumps(data, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoTQ PCBs CLI")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL verification")
    parser.add_argument("--username", help="Username for login")
    parser.add_argument("--password", help="Password for login")

    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List/search PCBs")
    p_list.add_argument("--q", help="Search query (mac/name)")
    p_list.add_argument("--stage", help="Stage label")
    p_list.add_argument("--device-id", type=int, help="Device id")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--offset", type=int, default=0)

    p_get = sub.add_parser("get", help="Get a PCB by id")
    p_get.add_argument("--id", type=int, required=True)

    p_create = sub.add_parser("create", help="Create a new PCB")
    p_create.add_argument("--mac", help="MAC address (AA:BB:CC:DD:EE:FF)")
    p_create.add_argument("--name", help="Name")
    p_create.add_argument("--hardware-version", dest="hardware_version", help="Hardware version")
    p_create.add_argument("--firmware-version", dest="firmware_version", help="Firmware version")
    p_create.add_argument("--stage", help="Current stage label")
    p_create.add_argument("--device-gs1", dest="device_gs1", help="Device GS1 barcode")
    p_create.add_argument("--device-id", type=int, help="Device id")

    p_tests = sub.add_parser("tests", help="List tests for a PCB")
    p_tests.add_argument("--id", type=int, required=True)
    p_tests.add_argument("--type", choices=["pump", "valve", "device_active", "device_idle", "power"].copy(), help="Filter by type")
    p_tests.add_argument("--limit", type=int, default=100)
    p_tests.add_argument("--offset", type=int, default=0)

    p_test_create = sub.add_parser("test-create", help="Create a test for a PCB")
    p_test_create.add_argument("--id", type=int, help="PCB id (optional; if omitted you can select by MAC)")
    p_test_create.add_argument("--type", choices=["pump", "valve", "device-active", "device-idle", "power"], help="Test type")
    p_test_create.add_argument("--stage-label")
    p_test_create.add_argument("--status", choices=["pass", "fail", "warn"], help="Status")
    p_test_create.add_argument("--measured", help="key=value pairs, comma-separated")
    p_test_create.add_argument("--result-summary", dest="result_summary", help="JSON string for result_summary")
    p_test_create.add_argument("--test-timestamp", dest="test_timestamp", help="ISO-8601 timestamp")

    sub.add_parser("interactive", help="Interactive text UI")

    p_watch = sub.add_parser("watch", help="Watch serial ports for ESP32-S3 devices and read MAC")
    p_watch.add_argument("--hold-open", action="store_true", help="Keep a serial connection open to the device after reading MAC")
    p_watch.add_argument("--interval", type=float, default=1.5, help="Polling interval seconds (default 1.5)")

    p_measure = sub.add_parser("measure-sequence", help="Run measure_sequence on a connected device and display results")
    p_measure.add_argument("--mac", help="Target device MAC (optional)")
    p_measure.add_argument("--port", help="Target serial port (optional)")
    p_measure.add_argument("--settle-ms", type=int, default=500)
    p_measure.add_argument("--pump-ms", type=int, default=3000)
    p_measure.add_argument("--valve-ms", type=int, default=2000)
    p_measure.add_argument("--all", action="store_true", help="Run on all connected devices")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Build initial client
    client = AutoTQClient(base_url=args.url, verify_ssl=not args.no_ssl_verify)

    # Smart connectivity fallback: try common URL/SSL combos automatically
    if not client.check_connection():
        candidates = []
        parsed = urlparse(args.url)
        # Prefer HTTPS variants when not explicitly secure
        https_url = urlunparse(parsed._replace(scheme='https'))
        http_url = urlunparse(parsed._replace(scheme='http'))
        # Candidate tuples: (url, verify_ssl)
        candidates.append((https_url, False))
        candidates.append((https_url, True))
        candidates.append((http_url, True))
        candidates.append((http_url, False))
        connected = False
        for url, verify in candidates:
            try:
                trial = AutoTQClient(base_url=url, verify_ssl=verify)
                if trial.check_connection():
                    client = trial
                    print(f"🔗 Connected using {url} (verify_ssl={verify})")
                    connected = True
                    break
            except Exception:
                continue
        if not connected:
            print("❌ Could not reach the API. If your server runs with self-signed HTTPS, try: --url https://localhost:8000 --no-ssl-verify")
            return 1

    if not ensure_authenticated(client, args.username, args.password):
        print("❌ Authentication required.")
        return 1

    if args.command == "list":
        return cmd_list(client, args)
    if args.command == "get":
        return cmd_get(client, args)
    if args.command == "create":
        return cmd_create(client, args)
    if args.command == "tests":
        return cmd_tests(client, args)
    if args.command == "test-create":
        return cmd_test_create(client, args)
    if args.command == "measure-sequence":
        return cmd_measure_sequence(args)
    if args.command == "watch":
        return run_watch_loop(args)
    if args.command == "interactive":
        # Start background watcher by default for interactive UI
        global WATCHER_THREAD
        if WATCHER_THREAD is None or not WATCHER_THREAD.is_alive():
            WATCHER_STOP.clear()
            WATCHER_THREAD = threading.Thread(target=_watcher_bg_loop, args=(1.5,), daemon=True)
            WATCHER_THREAD.start()
        # Simple text UI loop
        while True:
            print("\n=== AutoTQ PCBs Interactive ===")
            print("1) List PCBs")
            print("2) Create PCB")
            print("3) Get PCB")
            print("4) List tests for a PCB")
            print("5) Create a test for a PCB")
            print("6) Run measure sequence on a device")
            print("0) Exit")
            choice = input("Select option: ").strip()
            if choice == '0':
                WATCHER_STOP.set()
                if WATCHER_THREAD and WATCHER_THREAD.is_alive():
                    WATCHER_THREAD.join(timeout=2)
                return 0
            elif choice == '1':
                q = input("Search (q, blank for all): ").strip() or None
                stage = input("Stage (blank for any): ").strip() or None
                try:
                    limit = int(input("Limit [50]: ").strip() or '50')
                except Exception:
                    limit = 50
                try:
                    offset = int(input("Offset [0]: ").strip() or '0')
                except Exception:
                    offset = 0
                ns = argparse.Namespace(q=q, stage=stage, device_id=None, limit=limit, offset=offset)
                cmd_list(client, ns)
            elif choice == '2':
                ns = argparse.Namespace(
                    mac=None, name=None, hardware_version=None, firmware_version=None,
                    stage=None, device_gs1=None, device_id=None
                )
                cmd_create(client, ns)
            elif choice == '3':
                try:
                    pid = int(input("PCB id: ").strip())
                except Exception:
                    print("Invalid id")
                    continue
                ns = argparse.Namespace(id=pid)
                cmd_get(client, ns)
            elif choice == '4':
                try:
                    pid = int(input("PCB id: ").strip())
                except Exception:
                    print("Invalid id")
                    continue
                t = input("Type (pump|valve|device_active|device_idle|power, blank for all): ").strip() or None
                try:
                    limit = int(input("Limit [100]: ").strip() or '100')
                except Exception:
                    limit = 100
                try:
                    offset = int(input("Offset [0]: ").strip() or '0')
                except Exception:
                    offset = 0
                ns = argparse.Namespace(id=pid, type=t, limit=limit, offset=offset)
                cmd_tests(client, ns)
            elif choice == '5':
                try:
                    pid = int(input("PCB id: ").strip())
                except Exception:
                    print("Invalid id")
                    continue
                t = input("Type (pump|valve|device-active|device-idle|power): ").strip()
                ns = argparse.Namespace(
                    id=pid, type=t, stage_label=None, status=None, measured=None,
                    result_summary=None, test_timestamp=None
                )
                cmd_test_create(client, ns)
            elif choice == '6':
                items = _list_current_macs()
                if not items:
                    print("⚠️ No devices connected.")
                else:
                    for i, (mac, port) in enumerate(items, 1):
                        print(f"  {i}. {mac} ({port})")
                    try:
                        sel = int(input("Pick device number: ").strip())
                        mac = items[sel-1][0] if 1 <= sel <= len(items) else None
                    except Exception:
                        mac = None
                    ms = argparse.Namespace(mac=mac, port=None, settle_ms=500, pump_ms=3000, valve_ms=2000)
                    cmd_measure_sequence(ms)
            else:
                print("Invalid selection")
        return 0
    return 0


def _build_esptool_cmd(esptool_path: str, args: list) -> list:
    import sys as _sys
    import os as _os
    if esptool_path.startswith(_sys.executable) and "-m esptool" in esptool_path:
        return [_sys.executable, "-m", "esptool"] + args
    elif _os.path.isfile(esptool_path):
        return [_sys.executable, esptool_path] + args
    else:
        return [esptool_path] + args


def _read_mac_for_port(port: str) -> Optional[str]:
    """Use esptool read_mac to fetch MAC for the given serial port."""
    try:
        # Silence verbose logs during detection
        with suppress_output():
            prog = AutoTQFirmwareProgrammer()
        if not prog.esptool_path:
            print("❌ esptool not available; install with: pip install esptool")
            return None
        # Build read_mac command
        cmd = _build_esptool_cmd(prog.esptool_path, ["--port", port, "--baud", "115200", "read_mac"])
        print(f"🔎 Reading MAC on {port}...")
        import subprocess
        # Suppress esptool internal noise; we parse stdout later
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if result.returncode != 0:
            # Only show a concise error line
            err = (result.stderr or "").strip().splitlines()[:1]
            print(f"❌ read_mac failed on {port}: {' '.join(err) if err else 'unknown error'}")
            return None
        out = result.stdout
        # Parse lines like: "MAC: AA:BB:CC:DD:EE:FF"
        for line in out.splitlines():
            line = line.strip()
            if line.lower().startswith("mac:"):
                mac = line.split(":", 1)[1].strip()
                print(f"✅ Device: {port}  MAC: {mac}")
                return mac
        # Some esptool versions print base MAC differently
        import re
        m = re.search(r"([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})", out)
        if m:
            mac = m.group(1)
            print(f"✅ Device: {port}  MAC: {mac}")
            return mac
        print("⚠️ Could not parse MAC from esptool output")
        return None
    except Exception as e:
        print(f"❌ Error reading MAC on {port}: {e}")
        return None


def run_watch_loop(args: argparse.Namespace) -> int:
    if serial is None:
        print("❌ pyserial not installed. Run: pip install pyserial")
        return 1

    # Use firmware programmer to identify ESP32-S3 ports
    with suppress_output():
        prog = AutoTQFirmwareProgrammer()
    seen: Dict[str, Dict[str, Any]] = {}

    print("👀 Watching for ESP32-S3 devices. Press Ctrl+C to stop.")
    try:
        while True:
            # Silence verbose scanning output
            with suppress_output():
                ports = prog.list_available_ports()
            # Only keep 🎯 ports
            esp_ports = [p for p, desc in ports if '🎯' in desc]

            # Detect new ports
            for port in esp_ports:
                if port not in seen:
                    mac = _read_mac_for_port(port)
                    if mac:
                        global LAST_DETECTED_MAC
                        LAST_DETECTED_MAC = mac
                    # Hold the serial line open if requested
                    ser = None
                    if args.hold_open:
                        try:
                            params = AutoTQDeviceProgrammer.SERIAL_PARAMS
                            ser = serial.Serial(port, **params)
                            print(f"🔗 Held open connection on {port}")
                        except Exception as e:
                            print(f"⚠️ Could not open serial on {port}: {e}")
                    seen[port] = {"mac": mac, "serial": ser}
                    print(f"📟 Device: port={port} mac={mac or 'unknown'} (tracking)")

            # Detect removed ports
            for port in list(seen.keys()):
                if port not in esp_ports:
                    ser = seen[port].get("serial")
                    if ser and ser.is_open:
                        try:
                            ser.close()
                        except Exception:
                            pass
                    print(f"🔌 Device removed: {port}")
                    del seen[port]

            time.sleep(max(0.5, float(getattr(args, 'interval', 1.5))))
    except KeyboardInterrupt:
        print("\n👋 Stopping watch...")
    finally:
        for info in seen.values():
            ser = info.get("serial")
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass
    return 0


def _watcher_bg_loop(interval: float) -> None:
    """Background watcher used by interactive UI to keep DEVICE_REGISTRY updated."""
    if serial is None:
        return
    prog = AutoTQFirmwareProgrammer()
    seen_local: Dict[str, Dict[str, Any]] = {}
    while not WATCHER_STOP.is_set():
        try:
            with suppress_output():
                ports = prog.list_available_ports()
            esp_ports = [p for p, desc in ports if '🎯' in desc]

            # New ports
            for port in esp_ports:
                if port not in seen_local:
                    mac = _read_mac_for_port(port)
                    if mac:
                        global LAST_DETECTED_MAC
                        LAST_DETECTED_MAC = mac
                    seen_local[port] = {"mac": mac}
                    with DEVICE_LOCK:
                        DEVICE_REGISTRY[port] = {"mac": mac}
                    print(f"📟 (+) {port} MAC={mac or 'unknown'}")

            # Removed ports
            for port in list(seen_local.keys()):
                if port not in esp_ports:
                    del seen_local[port]
                    with DEVICE_LOCK:
                        if port in DEVICE_REGISTRY:
                            del DEVICE_REGISTRY[port]
                    print(f"🔌 (-) {port}")

            time.sleep(max(0.5, interval))
        except Exception:
            time.sleep(max(0.5, interval))


def _pick_port_for_mac(target_mac: Optional[str]) -> Optional[str]:
    if target_mac:
        with DEVICE_LOCK:
            for port, info in DEVICE_REGISTRY.items():
                if (info.get("mac") or "").lower() == target_mac.lower():
                    return port
    # fallback to first connected
    with DEVICE_LOCK:
        for port, info in DEVICE_REGISTRY.items():
            if info.get("mac"):
                return port
    return None


def _pretty_measure_output(data: Dict[str, Any]) -> None:
    print("\n=== Measure Sequence ===")
    status = data.get("status")
    print(f"Status: {status}")
    # idle: voltage + current
    idle = data.get("idle", {}) if isinstance(data.get("idle"), dict) else {}
    v = idle.get("voltage_v")
    i = idle.get("current_a")
    print(f"- idle:")
    if v is not None:
        print(f"    Voltage: {v:.3f} V")
    if i is not None:
        print(f"    Current: {i*1000:.2f} mA")

    # pump_on: voltage + pump driver current
    pump = data.get("pump_on", {}) if isinstance(data.get("pump_on"), dict) else {}
    v = pump.get("voltage_v")
    pd = pump.get("pump_driver_mA")
    print(f"- pump_on:")
    if v is not None:
        print(f"    Voltage: {v:.3f} V")
    if pd is not None:
        print(f"    Pump current: {pd:.2f} mA")

    # valve_on: voltage + valve driver current
    valve = data.get("valve_on", {}) if isinstance(data.get("valve_on"), dict) else {}
    v = valve.get("voltage_v")
    vd = valve.get("valve_driver_mA")
    print(f"- valve_on:")
    if v is not None:
        print(f"    Voltage: {v:.3f} V")
    if vd is not None:
        print(f"    Valve current: {vd:.2f} mA")
    print()


def cmd_measure_sequence(args: argparse.Namespace) -> int:
    # If --all, run against all known devices sequentially and print a compact table
    if getattr(args, 'all', False):
        with DEVICE_LOCK:
            targets = [(info.get('mac'), port) for port, info in DEVICE_REGISTRY.items() if info.get('mac')]
        if not targets:
            print("❌ No connected devices.")
            return 1
        rows = []
        for mac, port in targets:
            result = _run_measure_on_port(port, args)
            if result:
                idle = result.get('idle', {}) if isinstance(result.get('idle'), dict) else {}
                pump = result.get('pump_on', {}) if isinstance(result.get('pump_on'), dict) else {}
                valve = result.get('valve_on', {}) if isinstance(result.get('valve_on'), dict) else {}
                rows.append({
                    'mac': mac,
                    'port': port,
                    'idle_v': idle.get('voltage_v'),
                    'idle_i_mA': (idle.get('current_a') or 0) * 1000,
                    'pump_v': pump.get('voltage_v'),
                    'pump_i_mA': pump.get('pump_driver_mA'),
                    'valve_v': valve.get('voltage_v'),
                    'valve_i_mA': valve.get('valve_driver_mA'),
                })
        # Print compact table
        print("\nMAC               PORT   IDLE(V)  IDLE(mA)  PUMP(V)  PUMP(mA)  VALVE(V)  VALVE(mA)")
        for r in rows:
            print(f"{r['mac']:<17} {r['port']:<6} {r['idle_v'] if r['idle_v'] is not None else '':>7}  {r['idle_i_mA'] if r['idle_i_mA'] is not None else '':>8}  {r['pump_v'] if r['pump_v'] is not None else '':>7}  {r['pump_i_mA'] if r['pump_i_mA'] is not None else '':>8}  {r['valve_v'] if r['valve_v'] is not None else '':>8}  {r['valve_i_mA'] if r['valve_i_mA'] is not None else '':>9}")
        return 0

    # Single device path
    port = args.port or _pick_port_for_mac(args.mac)
    if not port:
        print("❌ No device port available. Plug in a device or specify --port.")
        return 1
    result_obj = _run_measure_on_port(port, args)
    if not result_obj:
        return 1
    _pretty_measure_output(result_obj)
    return 0


def _run_measure_on_port(port: str, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    params = AutoTQDeviceProgrammer.SERIAL_PARAMS
    try:
        ser = serial.Serial(port, **params)
        time.sleep(2)
    except Exception as e:
        print(f"❌ Failed to open serial {port}: {e}")
        return None

    try:
        cmd = {
            "command": "measure_sequence",
            "settle_ms": int(getattr(args, 'settle_ms', 500)),
            "pump_ms": int(getattr(args, 'pump_ms', 3000)),
            "valve_ms": int(getattr(args, 'valve_ms', 2000)),
        }
        ser.write((json.dumps(cmd) + "\n").encode("utf-8"))

        deadline = time.time() + 20
        buffer = ""
        result_obj: Optional[Dict[str, Any]] = None
        while time.time() < deadline:
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
                        if obj.get("command") == "measure_sequence" and obj.get("status"):
                            result_obj = obj
                            break
                    except Exception:
                        continue
            if result_obj:
                break
            time.sleep(0.05)
        if not result_obj:
            print(f"❌ No measure_sequence result received from {port}")
            return None
        return result_obj
    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())


