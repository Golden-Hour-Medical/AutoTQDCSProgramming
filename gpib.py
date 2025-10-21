#!/usr/bin/env python3
"""
ESPEC SH-241 / P-300 CLI over GPIB (NI-VISA + PyVISA)

Install:
  pip install -U pyvisa
(You also need NI-VISA installed; match Python bitness.)

Features
- Set Constant mode setpoints (TEMP/HUMI) and confirm
- Live monitor (temp, RH, mode, alarms) at 1 Hz
- Write general programs interactively
- Build & run a specific cycle:
    RT → 60°C (no soak) → 48°C (10m) → -20°C (no soak) → 10°C (10m) → RT (10m), repeat ×3

Command notes (from ESPEC command manual):
- Set constant temperature:  "TEMP, S23.0"
- Confirm constant temp:     "CONSTANT SET?,TEMP"  -> "23.0,ON"
- Live monitor (universal):  "MON?" -> "temp[,RH], MODE, alarms"
- Live monitor (PTC):        "MON PTC?" -> "spec, chamber[,RH], MODE, alarms"
- Program editing flow:      "PRGM DATA WRITE, PGM1, EDIT START ... EDIT END"
- Run a program:             "PRGM, RUN, RAM:1, STEP1"
"""
import time, sys
try:
    import pyvisa  # type: ignore
except Exception:
    pyvisa = None  # type: ignore

# --- CONFIG ---
GPIB_ADDRESS = 1                      # change if your chamber isn't GPIB addr 1
RESOURCE = f"GPIB0::{GPIB_ADDRESS}::INSTR"
WRITE_TERM = '\n'                     # match the chamber's GPIB delimiter (often \n)
READ_TERM  = '\n'
QUERY_DELAY = 0.30                    # gentle pacing between commands

def open_chamber():
    if pyvisa is None:
        raise RuntimeError("pyvisa not installed. Install NI-VISA and pip install pyvisa.")
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(RESOURCE)
    inst.write_termination = WRITE_TERM
    inst.read_termination  = READ_TERM
    inst.timeout = 8000
    return inst

def tx(inst, cmd):
    """Send a setting command and try to read one line of response."""
    inst.write(cmd)
    time.sleep(QUERY_DELAY)
    try:
        resp = inst.read().strip()
    except Exception:
        resp = ""
    return resp

def q(inst, cmd):
    """Send a query and return the reply."""
    resp = inst.query(cmd).strip()
    time.sleep(QUERY_DELAY)
    return resp

def is_ok(reply: str) -> bool:
    return reply.startswith("OK:") or reply == ""

# ---------- Monitoring ----------
def _parse_mon_generic(resp: str):
    """Robust parser for MON? or MON PTC? replies."""
    if not resp or resp.startswith("NA:"):
        return {"error": resp or "No reply"}
    parts = [p.strip() for p in resp.split(",")]
    if len(parts) < 2:
        return {"error": f"Unexpected MON format: {resp}"}
    alarms = parts[-1]
    mode   = parts[-2]
    nums   = parts[:-2]  # 1..3 numeric-ish tokens

    def _to_float(s):
        try:
            return float(s)
        except:
            return None

    vals = list(map(_to_float, nums))
    mon = {"mode": mode, "alarms": alarms,
           "specimen_C": None, "chamber_C": None, "rh": None, "raw": resp}

    if len(vals) == 1:                 # temp-only: temp
        mon["specimen_C"] = vals[0]
    elif len(vals) == 2:               # PTC: specimen, chamber
        mon["specimen_C"], mon["chamber_C"] = vals
    elif len(vals) >= 3:               # PTC: specimen, chamber, RH
        mon["specimen_C"], mon["chamber_C"], mon["rh"] = vals[:3]
    return mon

def monitor_once(inst):
    # Try MON? (universal). If it errors, try MON PTC? (older/optional feature).
    r = q(inst, "MON?")
    mon = _parse_mon_generic(r)
    if mon.get("error"):
        r2 = q(inst, "MON PTC?")
        mon = _parse_mon_generic(r2)

    if mon.get("error"):
        print(f"Monitor error -> {mon['error']}")
        return mon

    spec = f"{mon['specimen_C']:.1f}°C" if mon["specimen_C"] is not None else "—"
    chamb = f"{mon['chamber_C']:.1f}°C" if mon["chamber_C"] is not None else "—"
    rh = f"{int(mon['rh'])}%" if mon["rh"] is not None else "—"
    print(f"Specimen: {spec} | Chamber: {chamb} | RH: {rh} | Mode: {mon['mode']} | Alarms: {mon['alarms']}")
    return mon

def monitor_loop(inst):
    print("Ctrl+C to stop.\n")
    try:
        while True:
            monitor_once(inst)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

# ---------- Constant mode ----------
def confirm_temp(inst, target_c):
    r = q(inst, "CONSTANT SET?,TEMP")  # 'temp,ON'
    try:
        val = float(r.split(",")[0])
        return abs(val - float(target_c)) <= 0.2, r
    except Exception:
        return False, r

def confirm_humi(inst, target_rh):
    r = q(inst, "CONSTANT SET?,HUMI")  # 'rh,ON|OFF'
    try:
        val = int(r.split(",")[0])
        return abs(val - int(target_rh)) <= 1, r
    except Exception:
        return False, r

def set_constant(inst):
    tgt = input("Target temperature (°C): ").strip()
    humi = input("Target humidity %RH (blank if not equipped): ").strip()

    r1 = tx(inst, f"TEMP, S{float(tgt):.1f}")   # constant setup setpoint
    if not is_ok(r1):
        print(f"Chamber reply -> {r1}")

    ok_temp, echo = confirm_temp(inst, float(tgt))
    print(f"Confirm TEMP -> {echo}  [{'OK' if ok_temp else 'Mismatch'}]")

    if humi:
        r2 = tx(inst, f"HUMI, S{int(humi)}")
        if not is_ok(r2):
            print(f"Chamber reply -> {r2}")
        else:
            ok_h, echoh = confirm_humi(inst, int(humi))
            print(f"Confirm HUMI -> {echoh}  [{'OK' if ok_h else 'Mismatch'}]")

    # Ensure mode & power
    r3 = tx(inst, "MODE, CONSTANT")
    r4 = tx(inst, "POWER, ON")
    for tag, r in [("MODE", r3), ("POWER", r4)]:
        if r: print(f"{tag} reply -> {r}")

# ---------- Non-interactive helpers for automation ----------
def read_mon_parsed(inst):
    """Return monitor dict without printing; tries MON? then MON PTC?."""
    try:
        r = q(inst, "MON?")
        mon = _parse_mon_generic(r)
        if mon.get("error"):
            r2 = q(inst, "MON PTC?")
            mon = _parse_mon_generic(r2)
        return mon
    except Exception as e:
        return {"error": str(e)}

def power_on(inst) -> None:
    try:
        tx(inst, "MODE, CONSTANT")
        tx(inst, "POWER, ON")
    except Exception:
        pass

def power_off(inst) -> None:
    try:
        tx(inst, "POWER, OFF")
    except Exception:
        pass

def set_constant_temp(inst, target_c: float) -> bool:
    try:
        r1 = tx(inst, f"TEMP, S{float(target_c):.1f}")
        ok, _echo = confirm_temp(inst, float(target_c))
        return ok or is_ok(r1)
    except Exception:
        return False

def set_humidity(inst, rh_percent: float) -> bool:
    """Attempt to set relative humidity; returns False if not supported or failed."""
    try:
        r = tx(inst, f"HUMI, S{int(max(0, min(100, rh_percent)))}")
        ok, _echo = confirm_humi(inst, int(rh_percent))
        return ok or is_ok(r)
    except Exception:
        return False

def check_humidity_capability(inst) -> bool:
    """Check if chamber has humidity control capability."""
    try:
        # Try to query current humidity setting
        r = q(inst, "CONSTANT SET?,HUMI")
        # If we get a valid response (not NA: or error), humidity is supported
        if r and not r.startswith("NA:") and not r.startswith("ER:"):
            return True
        return False
    except Exception:
        return False

def turn_humidity_off(inst) -> bool:
    """Explicitly turn off humidity control (dry run mode). Tries multiple command formats."""
    try:
        # Try method 1: HUA, OFF (humidity automation off)
        r1 = tx(inst, "HUA, OFF")
        if is_ok(r1) or r1 == "":
            print(f"[DEBUG] Humidity OFF successful with: HUA, OFF")
            return True
        
        # Try method 2: HUMI, OFF (some chambers use this)
        r2 = tx(inst, "HUMI, OFF")
        if is_ok(r2) or r2 == "":
            print(f"[DEBUG] Humidity OFF successful with: HUMI, OFF")
            return True
        
        # Try method 3: Set humidity to OFF state in constant mode
        r3 = tx(inst, "CONSTANT SET, HUMI, OFF")
        if is_ok(r3) or r3 == "":
            print(f"[DEBUG] Humidity OFF successful with: CONSTANT SET, HUMI, OFF")
            return True
        
        # None worked, log responses for debugging
        print(f"[DEBUG] Humidity OFF command responses:")
        print(f"[DEBUG]   HUA, OFF -> '{r1}'")
        print(f"[DEBUG]   HUMI, OFF -> '{r2}'")
        print(f"[DEBUG]   CONSTANT SET, HUMI, OFF -> '{r3}'")
        
        # Check if chamber even has humidity capability
        has_humidity = check_humidity_capability(inst)
        if not has_humidity:
            print(f"[DEBUG] Chamber appears to be temperature-only (no humidity control)")
            return True  # Return True since there's nothing to turn off
        
        return False
    except Exception as e:
        print(f"[DEBUG] Humidity OFF exception: {e}")
        return False

def dry_chamber_prep(inst, dry_temp: float = 40.0, dry_rh: float = 10.0, dry_duration_min: float = 30.0) -> None:
    """Pre-conditioning: Run low humidity at elevated temp to dry the chamber before cycling."""
    print(f"[DRY PREP] Pre-drying chamber: {dry_temp:.1f}°C @ {dry_rh:.0f}% RH for {dry_duration_min:.0f} minutes")
    set_constant_temp(inst, dry_temp)
    set_humidity(inst, dry_rh)
    power_on(inst)
    print(f"[DRY PREP] Waiting for temperature stability...")
    wait_until_temp(inst, dry_temp, tol=1.0, stable_samples=3, poll_s=2.0)
    print(f"[DRY PREP] Drying in progress... ({dry_duration_min:.0f} min)")
    time.sleep(dry_duration_min * 60)
    print(f"[DRY PREP] Dry prep complete. Turning humidity OFF for cycling.")
    turn_humidity_off(inst)

def wait_until_temp(inst, target_c: float, tol: float = 0.5, stable_samples: int = 5, poll_s: float = 1.0, timeout_s: float = None):
    """Block until specimen/chamber temp within tol for stable_samples; returns last mon dict or None on timeout."""
    start = time.time()
    consecutive = 0
    last = None
    while True:
        try:
            mon = read_mon_parsed(inst)
        except Exception as e:
            mon = {"error": str(e)}
        last = mon
        t = None
        if isinstance(mon, dict):
            t = mon.get('specimen_C') if mon.get('specimen_C') is not None else mon.get('chamber_C')
        if isinstance(t, (int, float)) and abs(t - float(target_c)) <= float(tol):
            consecutive += 1
            if consecutive >= int(stable_samples):
                return mon
        else:
            consecutive = 0
        if timeout_s is not None and (time.time() - start) > float(timeout_s):
            return last
        time.sleep(float(poll_s))

# ---------- Program write/run ----------
def write_program(inst):
    try:
        pat = int(input("Program pattern number (1-8): ").strip() or "1")
    except KeyboardInterrupt:
        print("\nCancelled."); return
    except Exception:
        print("Invalid pattern."); return

    steps = []
    try:
        nsteps = int(input("How many steps? ").strip())
        for i in range(1, nsteps+1):
            t = float(input(f" Step {i}: temperature °C: ").strip())
            hrmn = input(f" Step {i}: soak time (H:MM, e.g. 0:30): ").strip()
            humi = input(f" Step {i}: humidity %RH (blank to skip): ").strip()
            steps.append((t, hrmn, humi))
    except KeyboardInterrupt:
        print("\nCancelled."); return

    name = input("Program name (<=15 chars, optional): ").strip() or "PY-PROGRAM"
    end = (input("End action [HOLD | OFF | STANDBY | CONST] (default HOLD): ").strip().upper() or "HOLD")

    base = f"PRGM DATA WRITE, PGM{pat}"
    replies = []
    replies.append(tx(inst, f"{base}, EDIT START"))

    for idx, (t, hrmn, humi) in enumerate(steps, start=1):
        atoms = [f"{base}, STEP{idx}", f"TEMP{t:.1f}", f"TIME{hrmn}"]
        if humi:
            atoms.append(f"HUMI{int(humi)}")
        replies.append(tx(inst, ", ".join(atoms)))

    replies.append(tx(inst, f"{base}, NAME, {name}"))
    replies.append(tx(inst, f"{base}, END, {end}"))
    replies.append(tx(inst, f"{base}, EDIT END"))

    print("Program write replies:")
    for r in replies:
        if r:
            print("  ", r)

    print("Pattern header ->", q(inst, f"PRGM DATA?, RAM:{pat}"))
    for i in range(1, len(steps)+1):
        print("  Step", i, "->", q(inst, f"PRGM DATA?, RAM:{pat}, STEP{i}"))

def run_program(inst, pat=None, step=None):
    try:
        pat = int(pat or input("Run which pattern (1-8): ").strip() or "1")
        step = int(step or input("Start at which step (default 1): ").strip() or "1")
    except KeyboardInterrupt:
        print("\nCancelled."); return
    r = tx(inst, f"PRGM, RUN, RAM:{pat}, STEP{step}")
    print("Run reply ->", (r if r else "(no echo)"))
    print("Program state ->", q(inst, "PRGM MON?"))

# ---------- Specific cycle builder ----------
def write_cycle_program(inst, pat=1, room=25.0, hi=60.0, lo=-20.0,
                        dwell48_min=10, dwell10_min=10, dwellRT_min=10,
                        repeats=3, name="CYCLER"):
    """
    Builds: RT -> 60 (no soak) -> 48 (10m) -> -20 (no soak) -> 10 (10m) -> RT (10m)
    Repeats the block 'repeats' times using counter A.
    """
    base = f"PRGM DATA WRITE, PGM{pat}"
    replies = []
    replies.append(tx(inst, f"{base}, EDIT START"))

    def step(n, temp, soak_minutes):
        cmd = f"{base}, STEP{n}, TEMP{temp:.1f}, TIME{int(soak_minutes)}:00"
        return tx(inst, cmd)

    s = 0
    s += 1; replies.append(step(s, hi, 0))                  # 1) 60C, no soak
    s += 1; replies.append(step(s, 48.0, dwell48_min))      # 2) 48C, 10 min
    s += 1; replies.append(step(s, lo, 0))                  # 3) -20C, no soak
    s += 1; replies.append(step(s, 10.0, dwell10_min))      # 4) 10C, 10 min
    s += 1; replies.append(step(s, room, dwellRT_min))      # 5) RT, 10 min
    last_step = s

    replies.append(tx(inst, f"{base}, NAME, {name}"))
    # COUNT, A(repeat_cycles, end_step, start_step)  -> e.g., A(3. 5. 1)
    replies.append(tx(inst, f"{base}, COUNT, A({int(repeats)}. {last_step}. 1)"))
    replies.append(tx(inst, f"{base}, END, STANDBY"))
    replies.append(tx(inst, f"{base}, EDIT END"))

    print("Cycle program write replies:")
    for r in replies:
        if r:
            print("  ", r)

    print("Pattern header ->", q(inst, f"PRGM DATA?, RAM:{pat}"))
    for i in range(1, last_step+1):
        print(f"  STEP{i} ->", q(inst, f"PRGM DATA?, RAM:{pat}, STEP{i}"))

# ---------- CLI ----------
def main():
    inst = open_chamber()
    print("Connected. ROM:", q(inst, "ROM?"), "| TYPE:", q(inst, "TYPE?"), "| MODE:", q(inst, "MODE?"))
    while True:
        try:
            print("\n--- ESPEC CLI ---")
            print("1) Set Constant setpoint & start")
            print("2) Write a Program (stored on chamber)")
            print("3) Run a Program")
            print("4) Live Monitor (temp/RH/mode)")
            print("5) POWER OFF")
            print("6) Build RT↔60/−20 cycle (48°C & 10°C holds, ×3) and RUN")
            print("0) Exit")
            ch = input("> ").strip()
        except KeyboardInterrupt:
            print("\nExiting..."); break

        if ch == "1":
            set_constant(inst)
        elif ch == "2":
            write_program(inst)
        elif ch == "3":
            run_program(inst)
        elif ch == "4":
            monitor_loop(inst)
        elif ch == "5":
            print(tx(inst, "POWER, OFF"))
        elif ch == "6":
            write_cycle_program(inst, pat=1, repeats=3, name="CYCLER")
            run_program(inst, pat=1, step=1)
        elif ch == "0":
            break
        else:
            print("Pick 0–6.")
    try:
        inst.close()
    except Exception:
        pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print("Error:", e)
        sys.exit(1)
