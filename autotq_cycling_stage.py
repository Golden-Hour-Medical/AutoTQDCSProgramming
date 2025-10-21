#!/usr/bin/env python3
"""
AutoTQ Cycling Stage Controller

Drives the ESPEC chamber directly (no stored program) through the sequence:
  RT → 60°C (dwell) → 48°C (dwell + tests) → −20°C (quench) → 10°C (dwell + tests) → RT (dwell + tests)
Repeats for N cycles. Runs 3 repeats of idle/pump/valve tests for each connected device
at RT baseline (once), then at 48°C and 10°C each cycle, and again at RT after each cycle.

PPK is NOT used in this flow. Measurements will only include device-reported values.

Robustness: If chamber comms fail, the script retries periodically and proceeds once available.
If devices change (connect/disconnect), the script refreshes the port list for each test block.
"""
import argparse
import sys
import time
from typing import Dict, Any, Optional, List

from autotq_client import AutoTQClient
from autotq_quick_check import (
    _list_esp_ports,
    read_mac_via_status,
    read_mac,
    read_device_info_via_serial,
    read_fw_version_via_serial,
    ensure_pcb_stage,
    _run_measure_on_port,
    _print_measure_summary,
    post_measure_tests,
)

import gpib


def log(msg: str) -> None:
    print(msg, flush=True)


def get_temp(mon: Dict[str, Any]) -> Optional[float]:
    t = mon.get('specimen_C') if isinstance(mon, dict) else None
    if t is None and isinstance(mon, dict):
        t = mon.get('chamber_C')
    return t if isinstance(t, (int, float)) else None


def wait_for_chamber_available(retry_s: float = 5.0):
    while True:
        try:
            inst = gpib.open_chamber()
            try:
                mon = gpib.read_mon_parsed(inst)
                if isinstance(mon, dict) and not mon.get('error'):
                    return inst
            except Exception:
                pass
            try:
                inst.close()
            except Exception:
                pass
        except Exception as e:
            log(f"[CHAMBER] Not available yet: {e}")
        time.sleep(retry_s)


def discover_devices_and_pcbs(client: AutoTQClient, stage_label: str) -> Dict[str, int]:
    port_to_pcb: Dict[str, int] = {}
    ports = _list_esp_ports()
    if not ports:
        log("[USB] No devices detected. Waiting for devices to connect...")
        # Wait loop until at least one device appears
        t0 = time.time()
        while not ports and (time.time() - t0) < 300:  # 5 minutes
            time.sleep(2)
            ports = _list_esp_ports()
    for port in ports:
        mac = read_mac_via_status(port) or read_mac(port) or None
        dinfo = read_device_info_via_serial(port) or {}
        fw = dinfo.get("firmware_version") or read_fw_version_via_serial(port)
        hw = dinfo.get("hardware_version")
        if not mac:
            log(f"[USB] Skipping {port}: MAC not readable")
            continue
        if not client.is_authenticated():
            client.set_api_key(prompt_if_missing=True)
        pcb = ensure_pcb_stage(client, mac, fw, hw, stage_label=stage_label, allow_create=True)
        if pcb and pcb.get('id') is not None:
            port_to_pcb[port] = pcb['id']
            log(f"[PCB] {port} -> PCB #{pcb['id']} ({mac})")
        else:
            log(f"[PCB] Failed to ensure PCB for {port} ({mac})")
    return port_to_pcb


def run_repeats_for_all(client: AutoTQClient, port_to_pcb: Dict[str, int], stage_label: str, cycle_index: int, repeats: int = 3) -> None:
    ports = _list_esp_ports()
    if not ports:
        log("[USB] No devices present for this test block.")
        return
    for port in ports:
        pcb_id = port_to_pcb.get(port)
        if not pcb_id:
            log(f"[USB] {port}: no PCB mapped; skipping")
            continue
        for r in range(1, repeats + 1):
            result = _run_measure_on_port(port)
            if result:
                _print_measure_summary(port, result)
                try:
                    post_measure_tests(client, pcb_id, result, stage_label=stage_label, run_index=(cycle_index - 1) * repeats + r)
                except Exception as e:
                    log(f"[POST] Error posting tests for PCB {pcb_id}: {e}")
            else:
                log(f"[MEASURE] {port}: failed to obtain result (repeat {r})")


def get_safe_humidity_for_temp(target_c: float, requested_rh: Optional[float]) -> Optional[float]:
    """Calculate safe humidity setpoint based on temperature to prevent chamber alarms."""
    if requested_rh is None:
        return None
    
    # Special case: if user explicitly sets 0% RH, respect it (disable humidity control)
    if requested_rh == 0.0:
        log(f"[CHAMBER] Humidity control explicitly disabled (--rh 0)")
        return None
    
    # Temperature-based humidity limits for typical ESPEC chambers
    if target_c <= -10.0:
        # Very low temperatures: disable humidity control to prevent ice formation
        log(f"[CHAMBER] Disabling humidity control at {target_c:.1f}°C (too cold for safe RH control)")
        return None
    elif target_c <= 5.0:
        # Low temperatures: limit to very low humidity to prevent condensation
        safe_rh = min(requested_rh, 20.0)
        if safe_rh != requested_rh:
            log(f"[CHAMBER] Limiting humidity to {safe_rh:.1f}% at {target_c:.1f}°C (requested {requested_rh:.1f}%)")
        return safe_rh
    elif target_c <= 15.0:
        # Cool temperatures: moderate humidity limit
        safe_rh = min(requested_rh, 60.0)
        if safe_rh != requested_rh:
            log(f"[CHAMBER] Limiting humidity to {safe_rh:.1f}% at {target_c:.1f}°C (requested {requested_rh:.1f}%)")
        return safe_rh
    elif target_c >= 70.0:
        # High temperatures: may need lower humidity to prevent over-saturation
        safe_rh = min(requested_rh, 80.0)
        if safe_rh != requested_rh:
            log(f"[CHAMBER] Limiting humidity to {safe_rh:.1f}% at {target_c:.1f}°C (requested {requested_rh:.1f}%)")
        return safe_rh
    else:
        # Normal temperature range: use requested humidity
        return requested_rh


def chamber_set_and_wait(inst, target_c: float, tol: float, stable_samples: int, poll_s: float, min_dwell_s: float = 0.0, label: str = "", rh_percent: Optional[float] = None) -> None:
    ok = gpib.set_constant_temp(inst, target_c)
    if not ok:
        log(f"[CHAMBER] Could not confirm setpoint {target_c:.1f}°C (continuing anyway)")
    gpib.power_on(inst)
    
    # Calculate temperature-appropriate humidity setpoint
    safe_rh = get_safe_humidity_for_temp(target_c, rh_percent)
    
    # Attempt to set humidity (optional; ignore failures)
    if safe_rh is not None:
        # Validate humidity range (typical chamber range is 10-95% RH)
        if safe_rh < 10.0 or safe_rh > 95.0:
            log(f"[CHAMBER] WARNING: Humidity {safe_rh:.1f}% is outside typical range (10-95%). This may cause AL26 or other chamber alarms.")
            if safe_rh < 10.0:
                safe_rh = 10.0
                log(f"[CHAMBER] Adjusting humidity to minimum safe value: {safe_rh:.1f}%")
        try:
            ok_h = gpib.set_humidity(inst, safe_rh)
            if not ok_h:
                log(f"[CHAMBER] Humidity control not available or failed; continuing without RH control")
            else:
                log(f"[CHAMBER] Humidity setpoint: {safe_rh:.1f}% RH at {target_c:.1f}°C")
        except Exception as e:
            log(f"[CHAMBER] Humidity set attempt failed ({e}); continuing without RH control")
    else:
        # Explicitly turn off humidity control for dry run
        log(f"[CHAMBER] Turning humidity OFF (dry run mode) for {target_c:.1f}°C")
        try:
            ok_off = gpib.turn_humidity_off(inst)
            if ok_off:
                log(f"[CHAMBER] ✅ Humidity control disabled successfully")
            else:
                log(f"[CHAMBER] ⚠️  Could not confirm humidity OFF command")
                log(f"[CHAMBER] This may be normal if your chamber doesn't support humidity control")
                log(f"[CHAMBER] Continuing with temperature cycling (humidity will float naturally)")
        except Exception as e:
            log(f"[CHAMBER] Humidity OFF command failed ({e}); continuing anyway")
    
    log(f"[CHAMBER] Waiting for {label or f'{target_c:.1f}°C'} within ±{tol}°C...")
    gpib.wait_until_temp(inst, target_c, tol=tol, stable_samples=stable_samples, poll_s=poll_s)
    if min_dwell_s > 0:
        log(f"[CHAMBER] Dwell {min_dwell_s/60:.1f} minutes at {label or f'{target_c:.1f}°C'}...")
        time.sleep(min_dwell_s)


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoTQ Cycling Stage Controller")
    parser.add_argument("--url", default="https://seahorse-app-ax33h.ondigitalocean.app", help="Server URL")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL verification")
    parser.add_argument("--api-key", help="API key (X-API-Key)")
    parser.add_argument("--cycles", type=int, default=3, help="Number of thermal cycles")
    parser.add_argument("--rt", type=float, default=25.0, help="Room temperature setpoint")
    parser.add_argument("--hi", type=float, default=60.0, help="High temperature setpoint")
    parser.add_argument("--lo", type=float, default=-20.0, help="Low temperature setpoint (quench)")
    parser.add_argument("--dwell60-min", type=float, default=30.0, help="Dwell at 60C (minutes)")
    parser.add_argument("--dwell48-min", type=float, default=10.0, help="Dwell at 48C before tests (minutes)")
    parser.add_argument("--dwell10-min", type=float, default=10.0, help="Dwell at 10C before tests (minutes)")
    parser.add_argument("--dwellRT-min", type=float, default=10.0, help="Dwell at RT before tests (minutes)")
    parser.add_argument("--tol", type=float, default=0.5, help="Temperature tolerance (°C)")
    parser.add_argument("--stable-samples", type=int, default=5, help="Consecutive in-tolerance samples to accept stability")
    parser.add_argument("--poll-sec", type=float, default=1.0, help="Chamber poll interval (seconds)")
    parser.add_argument("--rh", type=float, default=45.0, help="Target relative humidity percentage. Auto-adjusts based on temperature: disabled at ≤-10°C, limited at low/high temps to prevent chamber alarms")
    parser.add_argument("--dry-prep", action="store_true", help="Pre-dry the chamber before cycling (runs 40°C @ 10%% RH for 30min to remove moisture)")
    parser.add_argument("--dry-prep-temp", type=float, default=40.0, help="Dry prep temperature (default: 40°C)")
    parser.add_argument("--dry-prep-rh", type=float, default=10.0, help="Dry prep humidity (default: 10%%)")
    parser.add_argument("--dry-prep-min", type=float, default=30.0, help="Dry prep duration in minutes (default: 30)")
    args = parser.parse_args()

    client = AutoTQClient(base_url=args.url, verify_ssl=not args.no_ssl_verify)
    if getattr(args, 'api_key', None):
        client.set_api_key(args.api_key, prompt_if_missing=False)
    if not client.is_authenticated():
        client.set_api_key(prompt_if_missing=True)

    stage_label = 'cycling'

    # Chamber availability loop
    log("[CHAMBER] Connecting...")
    inst = wait_for_chamber_available(retry_s=5.0)
    log("[CHAMBER] Connected.")

    # Optional: Pre-dry the chamber to remove ambient moisture
    if args.dry_prep:
        log("[CHAMBER] Starting dry prep cycle to remove moisture...")
        gpib.dry_chamber_prep(inst, dry_temp=args.dry_prep_temp, dry_rh=args.dry_prep_rh, dry_duration_min=args.dry_prep_min)
        log("[CHAMBER] Dry prep complete. Chamber is now moisture-reduced.")

    # Device discovery and PCB ensure
    port_to_pcb = discover_devices_and_pcbs(client, stage_label=stage_label)
    if not port_to_pcb:
        log("[USB] No valid devices found; continuing. Devices can be plugged in later.")

    # Baseline at RT
    chamber_set_and_wait(inst, args.rt, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=args.dwellRT_min * 60, label="RT", rh_percent=args.rh)
    log("[RUN] Baseline tests at RT (init)")
    run_repeats_for_all(client, port_to_pcb, stage_label='cycling-rt-init', cycle_index=1, repeats=3)

    # Cycle loop
    for cycle in range(1, int(args.cycles) + 1):
        log(f"\n=== Cycle {cycle}/{args.cycles} ===")
        # 60C dwell
        chamber_set_and_wait(inst, args.hi, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=args.dwell60_min * 60, label="60C", rh_percent=args.rh)

        # 48C dwell + tests
        chamber_set_and_wait(inst, 48.0, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=args.dwell48_min * 60, label="48C", rh_percent=args.rh)
        log("[RUN] Tests at 48C")
        # Refresh mapping for any new devices
        new_map = discover_devices_and_pcbs(client, stage_label=stage_label)
        port_to_pcb.update(new_map)
        run_repeats_for_all(client, port_to_pcb, stage_label='cycling-48c', cycle_index=cycle, repeats=3)

        # -20C quench
        chamber_set_and_wait(inst, args.lo, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=0, label="-20C", rh_percent=args.rh)

        # 10C dwell + tests
        chamber_set_and_wait(inst, 10.0, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=args.dwell10_min * 60, label="10C", rh_percent=args.rh)
        log("[RUN] Tests at 10C")
        new_map = discover_devices_and_pcbs(client, stage_label=stage_label)
        port_to_pcb.update(new_map)
        run_repeats_for_all(client, port_to_pcb, stage_label='cycling-10c', cycle_index=cycle, repeats=3)

        # Return to RT dwell + tests
        chamber_set_and_wait(inst, args.rt, tol=args.tol, stable_samples=args.stable_samples, poll_s=args.poll_sec, min_dwell_s=args.dwellRT_min * 60, label="RT", rh_percent=args.rh)
        log("[RUN] Tests at RT (post)")
        new_map = discover_devices_and_pcbs(client, stage_label=stage_label)
        port_to_pcb.update(new_map)
        run_repeats_for_all(client, port_to_pcb, stage_label='cycling-rt-post', cycle_index=cycle, repeats=3)

    try:
        gpib.power_off(inst)
        inst.close()
    except Exception:
        pass
    log("[DONE] Cycling campaign complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


