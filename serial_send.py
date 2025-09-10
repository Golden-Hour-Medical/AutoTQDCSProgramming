import argparse, time, os, json
import serial
from serial.tools import list_ports

def open_port(port: str, baud: int) -> serial.Serial:
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 1
    s.write_timeout = 2
    s.dsrdtr = False
    s.rtscts = False
    try:
        # Pre-deassert before opening to avoid boot/reset glitches
        s.dtr = False
        s.rts = False
    except Exception:
        pass
    s.open()
    s.setDTR(False)
    s.setRTS(False)
    time.sleep(0.05)
    return s

def list_serial_ports() -> list:
    ports = list(list_ports.comports())
    for idx, p in enumerate(ports, 1):
        print(f"{idx}) {p.device} - {p.description} - {p.hwid}")
    return ports

def choose_port_interactively() -> str:
    ports = list_serial_ports()
    if not ports:
        raise SystemExit("No serial ports found.")
    while True:
        try:
            choice = input("Select port [1]: ").strip()
            if choice == "":
                return ports[0].device
            idx = int(choice)
            if 1 <= idx <= len(ports):
                return ports[idx - 1].device
        except Exception:
            pass
        print("Invalid selection. Try again.")

def apply_newline(text: str, newline: str) -> bytes:
    if newline == "none":
        return text.encode("utf-8")
    elif newline == "lf":
        return (text + "\n").encode("utf-8")
    elif newline == "cr":
        return (text + "\r").encode("utf-8")
    elif newline == "crlf":
        return (text + "\r\n").encode("utf-8")
    else:
        return text.encode("utf-8")

def read_response(s: serial.Serial, duration_s: float) -> str:
    end = time.time() + duration_s
    buf = bytearray()
    while time.time() < end:
        available = s.in_waiting if hasattr(s, "in_waiting") else 0
        if available:
            buf.extend(s.read(available))
        else:
            time.sleep(0.01)
    return buf.decode("utf-8", errors="replace")

def send_text(port: str, baud: int, text: str):
    s = open_port(port, baud)
    s.write(text.encode('utf-8'))
    s.flush()
    s.close()

def send_file(port: str, baud: int, path: str, chunk_bytes: int = 4096, inter_chunk_s: float = 0.005):
    size = os.path.getsize(path)
    s = open_port(port, baud)
    sent = 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_bytes)
            if not chunk:
                break
            s.write(chunk)
            s.flush()
            sent += len(chunk)
            time.sleep(inter_chunk_s)
    s.close()

def send_and_read(port: str, baud: int, text: str, newline: str, read_seconds: float, stabilize_ms: int = 0, verbose: bool = False):
    s = open_port(port, baud)
    try:
        if stabilize_ms and stabilize_ms > 0:
            time.sleep(stabilize_ms / 1000.0)
        payload = apply_newline(text, newline)
        if verbose:
            print(f"[serial_send] -> {port}@{baud}: {payload!r}")
        s.write(payload)
        s.flush()
        resp = read_response(s, read_seconds)
        if resp:
            print(resp, end="")
    finally:
        s.close()

def send_json_and_read(port: str, baud: int, obj: dict, read_seconds: float, stabilize_ms: int = 0, verbose: bool = False):
    s = open_port(port, baud)
    try:
        if stabilize_ms and stabilize_ms > 0:
            time.sleep(stabilize_ms / 1000.0)
        line = json.dumps(obj) + "\n"
        if verbose:
            print(f"[serial_send] -> {port}@{baud}: {line!r}")
        s.write(line.encode("utf-8"))
        s.flush()
        resp = read_response(s, read_seconds)
        if resp:
            print(resp, end="")
    finally:
        s.close()

def monitor_only(port: str, baud: int, read_seconds: float):
    s = open_port(port, baud)
    try:
        output = read_response(s, read_seconds)
        if output:
            print(output, end="")
    finally:
        s.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="Serial port (e.g., COM9). If omitted, select interactively.")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--list", action="store_true", help="List available serial ports and exit.")
    ap.add_argument("--newline", choices=["none", "lf", "cr", "crlf"], default="lf", help="Line ending to append when sending commands.")
    ap.add_argument("--read-seconds", type=float, default=2.0, help="Seconds to read after sending a command.")
    ap.add_argument("--stabilize-ms", type=int, default=2000, help="Delay after opening port before sending (ms).")
    ap.add_argument("--verbose", action="store_true", help="Print sent payloads and basic actions.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="Send raw text (no readback).")
    g.add_argument("--file", help="Send a file over serial.")
    g.add_argument("--get-status", action="store_true", help="Send JSON {\"command\":\"get_status\"} and read reply.")
    g.add_argument("--wifi-get-mac", action="store_true", help="Send JSON {\"command\":\"wifi_get_mac\"} and read reply.")
    g.add_argument("--send-and-read", help="Send a text command with chosen newline and read reply.")
    g.add_argument("--json", help="Send a JSON string and read reply, e.g. '{\"command\":\"list_files\"}'.")
    g.add_argument("--monitor", action="store_true", help="Only read/print from the port for --read-seconds.")
    args = ap.parse_args()

    if args.list:
        list_serial_ports()
        raise SystemExit(0)

    port = args.port if args.port else choose_port_interactively()
    if args.text is not None:
        send_text(port, args.baud, args.text)
    else:
        if args.file is not None:
            send_file(port, args.baud, args.file)
        elif args.get_status:
            send_json_and_read(port, args.baud, {"command": "get_status"}, args.read_seconds, args.stabilize_ms, args.verbose)
        elif args.wifi_get_mac:
            send_json_and_read(port, args.baud, {"command": "wifi_get_mac"}, args.read_seconds, args.stabilize_ms, args.verbose)
        elif args.json is not None:
            try:
                obj = json.loads(args.json)
            except json.JSONDecodeError as e:
                raise SystemExit(f"Invalid JSON for --json: {e}")
            send_json_and_read(port, args.baud, obj, args.read_seconds, args.stabilize_ms, args.verbose)
        elif args.monitor:
            monitor_only(port, args.baud, args.read_seconds)
        else:
            # --send-and-read
            send_and_read(port, args.baud, args.send_and_read, args.newline, args.read_seconds, args.stabilize_ms, args.verbose)