#!/usr/bin/env python3
"""
PCB Stage Report - aggregate tests/metrics across stages per PCB and export CSVs.

Usage:
  python pcb_stage_report.py --url https://... [--no-ssl-verify] [--api-key XXXX]
  python pcb_stage_report.py --csv out/report.csv --per-stage out/per_stage.csv
  python pcb_stage_report.py --plot  # requires matplotlib
"""
import argparse
import json
import csv
import sys
from typing import Any, Dict, List, Optional

from autotq_client import AutoTQClient
from autotq_quick_check import api_get  # uses the v1/legacy fallback helper

try:
    import matplotlib.pyplot as plt  # type: ignore
    HAS_MPL = True
except Exception:
    HAS_MPL = False


MAX_PCB_PAGE = 200
MAX_TESTS_PAGE = 500

VERBOSE = False

def _vprint(msg: str) -> None:
    if VERBOSE:
        print(msg)


def fetch_all_pcbs(client: AutoTQClient, limit: int = 5000) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page_size = min(MAX_PCB_PAGE, max(1, limit - offset))
        params = {"limit": page_size, "offset": offset}
        _vprint(f"[REQ] GET {client.base_url}/pcbs params={params} timeout=20s")
        r = api_get(client, "/pcbs", params=params, timeout=20)
        if r.status_code != 200:
            _vprint(f"[RESP] /pcbs status={r.status_code} body={r.text[:200] if hasattr(r, 'text') else ''}")
            break
        data = r.json()
        if isinstance(data, dict):
            page = data.get("items", []) or data.get("data", [])
        elif isinstance(data, list):
            page = data
        else:
            page = []
        if not page:
            _vprint(f"[RESP] /pcbs items=0 (done)")
            break
        items.extend(page)
        _vprint(f"[RESP] /pcbs items={len(page)} total_so_far={len(items)} next_offset={offset + len(page)}")
        offset += len(page)
        if offset >= limit:
            break
    return items


def fetch_tests_for_pcb(client: AutoTQClient, pcb_id: int, limit: int = 5000) -> List[Dict[str, Any]]:
    """Fetch all tests for a PCB by paging each type separately to avoid server-side per-table pagination."""
    all_items: List[Dict[str, Any]] = []

    def _fetch_type(tname: Optional[str]) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page_size = min(MAX_TESTS_PAGE, max(1, limit - len(collected)))
            params: Dict[str, Any] = {"limit": page_size, "offset": offset}
            if tname:
                params["type"] = tname
            _vprint(f"[REQ] GET {client.base_url}/pcbs/{pcb_id}/tests params={params} timeout=20s")
            r = api_get(client, f"/pcbs/{pcb_id}/tests", params=params, timeout=20)
            if r.status_code != 200:
                _vprint(f"[RESP] /pcbs/{pcb_id}/tests status={r.status_code} body={r.text[:200] if hasattr(r, 'text') else ''}")
                break
            data = r.json()
            if isinstance(data, dict):
                page = data.get("items", []) or data.get("data", []) or []
            elif isinstance(data, list):
                page = data
            else:
                page = []
            if not page:
                _vprint(f"[RESP] /pcbs/{pcb_id}/tests type={tname or 'any'} items=0 (done)")
                break
            collected.extend(page)
            _vprint(f"[RESP] /pcbs/{pcb_id}/tests type={tname or 'any'} items={len(page)} collected={len(collected)} next_offset={offset + len(page)}")
            offset += len(page)
            if len(collected) >= limit:
                break
        return collected

    # Server accepts: pump, valve, device_active, device_idle, power
    for t in ["pump", "valve", "device_active", "device_idle", "power"]:
        got = _fetch_type(t)
        _vprint(f"[AGG] pcb_id={pcb_id} type={t} total_added={len(got)}")
        all_items.extend(got)

    # De-duplicate if any overlap and sort by timestamp desc
    seen = set()
    unique_items: List[Dict[str, Any]] = []
    for it in all_items:
        rtype = it.get("type") or ((it.get("result_summary") or {}).get("type"))
        rid = it.get("id")
        if rid is not None and rtype:
            key = (str(rtype), int(rid))
        else:
            key = (
                json.dumps(
                    {
                        "type": rtype,
                        "stage": it.get("stage_label"),
                        "ts": it.get("test_timestamp"),
                    },
                    sort_keys=True,
                    default=str,
                )
                + "|"
                + json.dumps(it.get("result_summary", {}), sort_keys=True, default=str)
            )
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(it)
    unique_items.sort(key=lambda x: x.get("test_timestamp") or "", reverse=True)
    _vprint(f"[AGG] pcb_id={pcb_id} unique_tests={len(unique_items)}")
    return unique_items


def summarize_pcb_tests(tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Organize by stage and type
    by_stage: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for t in tests:
        if not isinstance(t, dict):
            continue
        stage = str(t.get("stage_label") or "unknown")
        rs = t.get("result_summary") or {}
        ttype_raw = str(rs.get("type") or t.get("type") or "unknown")
        ttype = ttype_raw.replace("_", "-")
        by_stage.setdefault(stage, {}).setdefault(ttype, []).append(t)
    # Build a compact summary
    summary: Dict[str, Any] = {"stages": {}}
    for stage, types in by_stage.items():
        stage_row: Dict[str, Any] = {}
        for ttype, rows in types.items():
            # Extract representative metrics
            mv_values: List[Dict[str, Any]] = [row.get("measured_values") or {} for row in rows]
            # Example metrics we care about across tests
            currents = []
            ppk_currents = []
            for mv in mv_values:
                for key in ("current_mA", "pump_current_mA", "valve_current_mA"):
                    if isinstance(mv.get(key), (int, float)):
                        currents.append(float(mv.get(key)))
                if isinstance(mv.get("ppk_current_mA"), (int, float)):
                    ppk_currents.append(float(mv.get("ppk_current_mA")))
            def _avg(xs: List[float]) -> Optional[float]:
                return (sum(xs) / len(xs)) if xs else None
            stage_row[f"{ttype}_n"] = len(rows)
            stage_row[f"{ttype}_current_mA_avg"] = _avg(currents)
            stage_row[f"{ttype}_ppk_current_mA_avg"] = _avg(ppk_currents)
        summary["stages"][stage] = stage_row
    return summary


def write_csv_per_pcb(rows: List[Dict[str, Any]], csv_path: str) -> None:
    if not rows:
        return
    # Collect all keys
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_csv_per_stage(rows: List[Dict[str, Any]], csv_path: str) -> None:
    if not rows:
        return
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def maybe_plot_per_stage(rows: List[Dict[str, Any]]) -> None:
    if not HAS_MPL:
        print("matplotlib not installed. Skipping plots.")
        return
    # Simple scatter: pump_current vs valve_current by stage
    import math
    stages = sorted(set(r.get("stage_label", "unknown") for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    ax1, ax2 = axes
    for stg in stages:
        xs = [r.get("pump_current_mA_avg") for r in rows if r.get("stage_label") == stg]
        ys = [r.get("valve_current_mA_avg") for r in rows if r.get("stage_label") == stg]
        xs = [x for x in xs if isinstance(x, (int, float))]
        ys = [y for y in ys if isinstance(y, (int, float))]
        if xs and ys and len(xs) == len(ys):
            ax1.scatter(xs, ys, label=stg)
    ax1.set_xlabel("pump_current_mA_avg")
    ax1.set_ylabel("valve_current_mA_avg")
    ax1.legend()
    # PPK avg (if present) across stages
    for stg in stages:
        ys = [r.get("device-idle_ppk_current_mA_avg") for r in rows if r.get("stage_label") == stg]
        ys = [y for y in ys if isinstance(y, (int, float))]
        if ys:
            ax2.scatter([stg]*len(ys), ys)
    ax2.set_title("PPK idle avg by stage")
    ax2.set_ylabel("mA")
    plt.tight_layout()
    plt.show()


def write_csv_tests(rows: List[Dict[str, Any]], csv_path: str) -> None:
    if not rows:
        return
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def maybe_plot_timeseries(rows: List[Dict[str, Any]], filter_mac: Optional[str] = None) -> None:
    if not HAS_MPL:
        print("matplotlib not installed. Skipping time-series plots.")
        return
    import datetime as dt
    # Optional filter by MAC
    if filter_mac:
        rows = [r for r in rows if str(r.get("mac") or "").lower() == filter_mac.lower()]
    # Build series for three types
    series: Dict[str, Dict[str, List[Any]]] = {
        'device-idle': {'t': [], 'i_dev': [], 'i_ppk': [], 'v': [], 'stage': [], 'mac': []},
        'pump': {'t': [], 'i_dev': [], 'i_ppk': [], 'v': [], 'stage': [], 'mac': []},
        'valve': {'t': [], 'i_dev': [], 'i_ppk': [], 'v': [], 'stage': [], 'mac': []},
        'power': {'t': [], 'i_dev': [], 'i_ppk': [], 'v': [], 'stage': [], 'mac': []},
    }
    for r in rows:
        ttype = str(r.get('type') or '')
        ts = r.get('test_timestamp')
        if not ts or ttype not in series:
            continue
        try:
            t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except Exception:
            continue
        # choose appropriate current for each type
        # device current by type
        if ttype == 'device-idle':
            i_dev = r.get('device_current_mA')
        elif ttype == 'pump':
            i_dev = r.get('pump_current_mA') if r.get('pump_current_mA') is not None else r.get('device_current_mA')
        elif ttype == 'valve':
            i_dev = r.get('valve_current_mA') if r.get('valve_current_mA') is not None else r.get('device_current_mA')
        else:
            i_dev = r.get('device_current_mA')
        i_ppk = r.get('ppk_current_mA')
        v = r.get('voltage_v')
        # Allow missing voltage/current; only require at least one current value
        if i_dev is None and i_ppk is None:
            continue
        series[ttype]['t'].append(t)
        series[ttype]['i_dev'].append(float(i_dev) if isinstance(i_dev, (int, float)) else None)
        series[ttype]['i_ppk'].append(float(i_ppk) if isinstance(i_ppk, (int, float)) else None)
        series[ttype]['v'].append(float(v) if isinstance(v, (int, float)) else None)
        series[ttype]['stage'].append(r.get('stage_label') or 'unknown')
        series[ttype]['mac'].append(r.get('mac'))
    # Plot
    keys = ['device-idle', 'pump', 'valve']
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    import itertools
    import matplotlib.pyplot as _plt
    cmap = _plt.get_cmap('tab10')
    for idx, key in enumerate(keys):
        ax = axes[idx]
        data = series[key]
        if not data['t']:
            ax.set_title(f"{key} (no data)")
            continue
        # Colors by MAC
        macs = list(dict.fromkeys([m for m in data['mac'] if m is not None]))
        mac_to_color = {m: cmap(i % 10) for i, m in enumerate(macs)}
        # Secondary axis for voltage
        ax2 = ax.twinx()
        handles_mac = []
        seen_mac = set()
        # Accumulate voltage time series per MAC for continuous lines
        volt_points: Dict[Any, Dict[str, List[Any]]] = {m: {'t': [], 'v': []} for m in macs}
        for i, t in enumerate(data['t']):
            mac = data['mac'][i]
            color = mac_to_color.get(mac, 'tab:gray')
            # Device current
            if isinstance(data['i_dev'][i], (int, float)):
                h = ax.scatter(t, data['i_dev'][i], color=color, marker='o', s=18)
                if mac not in seen_mac:
                    handles_mac.append((mac, h))
                    seen_mac.add(mac)
            # Voltage points (collect to draw continuous lines)
            if isinstance(data['v'][i], (int, float)) and mac in volt_points:
                volt_points[mac]['t'].append(t)
                volt_points[mac]['v'].append(data['v'][i])
        # Plot voltage lines per MAC for visibility
        for mac, tv in volt_points.items():
            if tv['t'] and tv['v']:
                # sort by time
                zipped = sorted(zip(tv['t'], tv['v']), key=lambda x: x[0])
                tt = [z[0] for z in zipped]
                vv = [z[1] for z in zipped]
                ax2.plot(tt, vv, color=mac_to_color.get(mac, 'lightgray'), alpha=0.9, linewidth=1.8, linestyle='-')
        ax.set_ylabel('Current (mA)')
        ax2.set_ylabel('Voltage (V)')
        ax.set_title(f"{key} current (device •) and voltage vs time")
        # Build legend: one entry per MAC, plus markers for device/PPK and a voltage line sample
        from matplotlib.lines import Line2D
        mac_handles = [Line2D([0], [0], marker='o', color=h.get_facecolor()[0], linestyle='None', label=str(mac)) for mac, h in handles_mac]
        style_handles = [
            Line2D([0], [0], marker='o', color='black', linestyle='None', label='Device current'),
            Line2D([0], [0], color='black', linewidth=2, label='Voltage (V)'),
        ]
        # Place legend outside to avoid clutter
        ax.legend(handles=style_handles + mac_handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    axes[-1].set_xlabel('Timestamp')
    plt.tight_layout()
    plt.show()


def maybe_plot_power(rows: List[Dict[str, Any]], filter_mac: Optional[str] = None) -> None:
    """Single plot: Power (mW) = voltage_v * device_current_mA, color by MAC, marker by type."""
    if not HAS_MPL:
        print("matplotlib not installed. Skipping power plot.")
        return
    import datetime as dt
    import matplotlib.pyplot as _plt
    # Optional filter by MAC
    if filter_mac:
        rows = [r for r in rows if str(r.get("mac") or "").lower() == filter_mac.lower()]
    # Collect points
    points: List[Dict[str, Any]] = []
    for r in rows:
        ttype = str(r.get('type') or '')
        if ttype not in ('device-idle', 'pump', 'valve', 'power'):
            continue
        ts = r.get('test_timestamp')
        if not ts:
            continue
        try:
            t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except Exception:
            continue
        v = r.get('voltage_v')
        # choose device current matching type
        if ttype == 'device-idle':
            i_dev = r.get('device_current_mA')
        elif ttype == 'pump':
            i_dev = r.get('pump_current_mA') if r.get('pump_current_mA') is not None else r.get('device_current_mA')
        elif ttype == 'valve':
            i_dev = r.get('valve_current_mA') if r.get('valve_current_mA') is not None else r.get('device_current_mA')
        else:
            i_dev = r.get('device_current_mA')
        if not isinstance(v, (int, float)) or not isinstance(i_dev, (int, float)):
            continue
        p_mw = float(v) * float(i_dev)  # volts * mA -> mW
        points.append({
            't': t,
            'p_mw': p_mw,
            'mac': r.get('mac'),
            'stage': r.get('stage_label') or 'unknown',
            'type': ttype,
        })
    if not points:
        print("No points to plot for power.")
        return
    # Color by MAC, marker by type
    macs = list(dict.fromkeys([p['mac'] for p in points if p.get('mac')]))
    cmap = _plt.get_cmap('tab10')
    mac_to_color = {m: cmap(i % 10) for i, m in enumerate(macs)}
    type_to_marker = {'device-idle': 'o', 'pump': '^', 'valve': 's', 'power': 'x'}

    fig, ax = _plt.subplots(1, 1, figsize=(12, 5))
    handles_mac = []
    seen_mac = set()
    for p in sorted(points, key=lambda x: x['t']):
        color = mac_to_color.get(p['mac'], 'tab:gray')
        marker = type_to_marker.get(p['type'], 'o')
        h = ax.scatter(p['t'], p['p_mw'], color=color, marker=marker, s=20)
        if p['mac'] not in seen_mac and p['mac'] is not None:
            handles_mac.append((p['mac'], h))
            seen_mac.add(p['mac'])
    ax.set_ylabel('Power (mW)')
    ax.set_xlabel('Timestamp')
    ax.set_title('Device power vs time (color=MAC, marker=type)')
    # Legends: style markers per type + one per MAC
    from matplotlib.lines import Line2D
    style_handles = [
        Line2D([0], [0], marker='o', color='black', linestyle='None', label='device-idle'),
        Line2D([0], [0], marker='^', color='black', linestyle='None', label='pump'),
        Line2D([0], [0], marker='s', color='black', linestyle='None', label='valve'),
        Line2D([0], [0], marker='x', color='black', linestyle='None', label='power'),
    ]
    mac_handles = [Line2D([0], [0], marker='o', color=h.get_facecolor()[0], linestyle='None', label=str(mac)) for mac, h in handles_mac]
    ax.legend(handles=style_handles + mac_handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    _plt.tight_layout()
    _plt.show()


def _build_stage_stats(rows: List[Dict[str, Any]]) -> Dict[tuple, Dict[str, float]]:
    """Aggregate per (pcb_id, mac, stage_label, type) median metrics: current (mA), voltage (V), power (mW)."""
    import statistics as stats
    buckets: Dict[tuple, Dict[str, List[float]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        pcb_id = r.get('pcb_id')
        mac = r.get('mac')
        stage = r.get('stage_label') or 'unknown'
        ttype = r.get('type') or 'unknown'
        key = (pcb_id, mac, stage, ttype)
        v = r.get('voltage_v')
        if ttype == 'device-idle':
            i = r.get('device_current_mA')
        elif ttype == 'pump':
            i = r.get('pump_current_mA') if r.get('pump_current_mA') is not None else r.get('device_current_mA')
        elif ttype == 'valve':
            i = r.get('valve_current_mA') if r.get('valve_current_mA') is not None else r.get('device_current_mA')
        else:
            i = r.get('device_current_mA')
        if not isinstance(i, (int, float)) or not isinstance(v, (int, float)):
            continue
        p = float(v) * float(i)
        b = buckets.setdefault(key, {'i': [], 'v': [], 'p': []})
        b['i'].append(float(i))
        b['v'].append(float(v))
        b['p'].append(float(p))
    out: Dict[tuple, Dict[str, float]] = {}
    for key, vals in buckets.items():
        try:
            out[key] = {
                'current_mA_median': stats.median(vals['i']) if vals['i'] else None,
                'voltage_v_median': stats.median(vals['v']) if vals['v'] else None,
                'power_mW_median': stats.median(vals['p']) if vals['p'] else None,
                'n': float(len(vals['i']))
            }
        except Exception:
            continue
    return out


def maybe_plot_stage_box(rows: List[Dict[str, Any]], metric: str = 'power') -> None:
    """Boxplots per stage for idle/pump/valve across all PCBs. metric in {'power','current'}."""
    if not HAS_MPL:
        print("matplotlib not installed. Skipping stage box plots.")
        return
    import matplotlib.pyplot as _plt
    stats_map = _build_stage_stats(rows)
    stages = sorted({k[2] for k in stats_map.keys()})
    types = ['device-idle', 'pump', 'valve']
    fig, axes = _plt.subplots(1, 3, figsize=(14, 4), sharey=True)
    for idx, ttype in enumerate(types):
        ax = axes[idx]
        data = []
        labels = []
        for stg in stages:
            vals = []
            for (pid, mac, stage, typ), m in stats_map.items():
                if stage == stg and typ == ttype:
                    if metric == 'power' and isinstance(m.get('power_mW_median'), (int, float)):
                        vals.append(m['power_mW_median'])
                    elif metric == 'current' and isinstance(m.get('current_mA_median'), (int, float)):
                        vals.append(m['current_mA_median'])
            if vals:
                data.append(vals)
                labels.append(stg)
        if data:
            ax.boxplot(data, labels=labels, showfliers=True)
        ax.set_title(f"{ttype}")
        ax.set_ylabel('mW' if metric == 'power' else 'mA')
    fig.suptitle(f"Per-stage distribution ({'power mW' if metric=='power' else 'current mA'})")
    _plt.tight_layout()
    _plt.show()


def maybe_plot_paired_deltas(rows: List[Dict[str, Any]], baseline: str = 'factory', target: str = 'post_thermal', metric: str = 'power', ttype: str = 'pump') -> None:
    """Paired line plot per PCB: baseline vs target stage. metric in {'power','current'}."""
    if not HAS_MPL:
        print("matplotlib not installed. Skipping delta plots.")
        return
    import matplotlib.pyplot as _plt
    stats_map = _build_stage_stats(rows)
    pairs = []  # list of (mac, base_val, targ_val)
    for (pid, mac, stage, typ), m in stats_map.items():
        if typ != ttype:
            continue
        if stage == baseline:
            key_t = (pid, mac, target, ttype)
            if key_t in stats_map:
                if metric == 'power':
                    base = stats_map[(pid, mac, baseline, ttype)].get('power_mW_median')
                    targ = stats_map[key_t].get('power_mW_median')
                else:
                    base = stats_map[(pid, mac, baseline, ttype)].get('current_mA_median')
                    targ = stats_map[key_t].get('current_mA_median')
                if isinstance(base, (int, float)) and isinstance(targ, (int, float)):
                    pairs.append((mac, float(base), float(targ)))
    if not pairs:
        print("No paired data available for selected stages/type.")
        return
    fig, ax = _plt.subplots(1, 1, figsize=(8, 5))
    xs = [0, 1]
    for mac, base, targ in pairs:
        ax.plot(xs, [base, targ], marker='o', linewidth=1.5, alpha=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels([baseline, target])
    ax.set_ylabel('mW' if metric == 'power' else 'mA')
    ax.set_title(f"Paired change per PCB ({ttype}, {metric})")
    _plt.tight_layout()
    _plt.show()


def maybe_plot_scatter_pump_valve(rows: List[Dict[str, Any]], stage: str = 'factory', metric: str = 'power') -> None:
    """Scatter of pump vs valve per PCB at a given stage, colored by MAC."""
    if not HAS_MPL:
        print("matplotlib not installed. Skipping scatter plot.")
        return
    import matplotlib.pyplot as _plt
    stats_map = _build_stage_stats(rows)
    pts = []
    for (pid, mac, stg, typ), m in stats_map.items():
        if stg != stage:
            continue
        if metric == 'power':
            if typ == 'pump':
                pv = m.get('power_mW_median')
                vv = stats_map.get((pid, mac, stg, 'valve'), {}).get('power_mW_median')
            else:
                continue
        else:
            if typ == 'pump':
                pv = m.get('current_mA_median')
                vv = stats_map.get((pid, mac, stg, 'valve'), {}).get('current_mA_median')
            else:
                continue
        if isinstance(pv, (int, float)) and isinstance(vv, (int, float)):
            pts.append((mac, pv, vv))
    if not pts:
        print("No points for pump vs valve at stage.")
        return
    fig, ax = _plt.subplots(1, 1, figsize=(6, 6))
    cmap = _plt.get_cmap('tab10')
    macs = list(dict.fromkeys([p[0] for p in pts]))
    mac_to_color = {m: cmap(i % 10) for i, m in enumerate(macs)}
    for mac, x, y in pts:
        ax.scatter(x, y, color=mac_to_color.get(mac, 'tab:gray'), s=30)
    ax.set_xlabel('Pump ' + ('power (mW)' if metric == 'power' else 'current (mA)'))
    ax.set_ylabel('Valve ' + ('power (mW)' if metric == 'power' else 'current (mA)'))
    ax.set_title(f"{stage}: pump vs valve ({metric})")
    _plt.tight_layout()
    _plt.show()

def main() -> int:
    p = argparse.ArgumentParser(description="PCB Stage Report")
    p.add_argument("--url", default="https://seahorse-app-ax33h.ondigitalocean.app")
    p.add_argument("--no-ssl-verify", action="store_true")
    p.add_argument("--api-key")
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--csv", default="pcb_report.csv")
    p.add_argument("--per-stage", default="pcb_report_per_stage.csv")
    p.add_argument("--plot", action="store_true")
    p.add_argument("--export-tests", default="pcb_report_tests.csv", help="Write flattened per-test CSV")
    p.add_argument("--plot-ts", action="store_true", help="Plot time-series per type")
    p.add_argument("--plot-power", action="store_true", help="Plot power (mW) vs time in a single chart")
    p.add_argument("--plot-stage-box-power", action="store_true", help="Boxplots per stage (power)")
    p.add_argument("--plot-stage-box-current", action="store_true", help="Boxplots per stage (current)")
    p.add_argument("--plot-delta-power", action="store_true", help="Paired baseline vs target delta (power)")
    p.add_argument("--plot-delta-current", action="store_true", help="Paired baseline vs target delta (current)")
    p.add_argument("--delta-baseline", default="factory")
    p.add_argument("--delta-target", default="post_thermal")
    p.add_argument("--delta-type", default="pump", choices=["device-idle","pump","valve"]) 
    p.add_argument("--plot-scatter-pump-valve", action="store_true", help="Scatter pump vs valve at a stage")
    p.add_argument("--scatter-stage", default="factory")
    p.add_argument("--scatter-metric", default="power", choices=["power","current"]) 
    p.add_argument("--filter-mac", help="Filter plots/exports to a single MAC")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    global VERBOSE
    VERBOSE = bool(args.verbose)

    client = AutoTQClient(base_url=args.url, verify_ssl=not args.no_ssl_verify)
    if args.api_key:
        client.set_api_key(args.api_key, prompt_if_missing=False)
    if not client.is_authenticated():
        client.set_api_key(prompt_if_missing=True)

    _vprint(f"[START] Fetching PCBs up to limit={args.limit}")
    pcbs = fetch_all_pcbs(client, limit=args.limit)
    _vprint(f"[DONE] PCBs fetched: {len(pcbs)}")
    if not pcbs:
        print("No PCBs returned from /pcbs. Trying legacy endpoint variations...")
        # Try without pagination
        _vprint(f"[REQ] GET {client.base_url}/pcbs params=None timeout=20s (legacy retry)")
        r_legacy = api_get(client, "/pcbs", timeout=20)
        if r_legacy.status_code == 200:
            data = r_legacy.json()
            if isinstance(data, list):
                pcbs = data
            elif isinstance(data, dict):
                pcbs = data.get("items", []) or data.get("data", []) or []
        _vprint(f"[DONE] Legacy fetch PCBs count: {len(pcbs)}")
    rows_per_pcb: List[Dict[str, Any]] = []
    rows_per_stage: List[Dict[str, Any]] = []
    rows_tests: List[Dict[str, Any]] = []

    for pcb in pcbs:
        pid = pcb.get("id")
        mac = pcb.get("mac_address") or pcb.get("mac") or pcb.get("macAddress")
        if pid is None:
            continue
        _vprint(f"[PCB] pcb_id={pid} mac={mac} -> fetching tests...")
        tests = fetch_tests_for_pcb(client, int(pid))
        summary = summarize_pcb_tests(tests)
        # Flatten per-pcb row
        flat: Dict[str, Any] = {
            "pcb_id": pid,
            "mac": mac,
        }
        for stage, metrics in summary.get("stages", {}).items():
            for k, v in metrics.items():
                flat[f"{stage}.{k}"] = v
            # Also prepare per-stage rows for easier filtering
            row_stage: Dict[str, Any] = {"pcb_id": pid, "mac": mac, "stage_label": stage}
            # Copy select averages for convenience
            for key in [
                "device-idle_current_mA_avg",
                "device-idle_ppk_current_mA_avg",
                "pump_current_mA_avg",
                "pump_ppk_current_mA_avg",
                "valve_current_mA_avg",
                "valve_ppk_current_mA_avg",
            ]:
                row_stage[key] = metrics.get(key)
            rows_per_stage.append(row_stage)
        rows_per_pcb.append(flat)
        # Flatten per-test rows for time-series and CSV export
        for t in tests:
            if not isinstance(t, dict):
                continue
            rs = t.get('result_summary') or {}
            ttype = str(rs.get('type') or t.get('type') or 'unknown').replace('_', '-')
            mv = t.get('measured_values') or {}
            row_t: Dict[str, Any] = {
                'pcb_id': pid,
                'mac': mac,
                'stage_label': t.get('stage_label') or 'unknown',
                'type': ttype,
                'test_timestamp': t.get('test_timestamp'),
                'voltage_v': mv.get('voltage_v'),
                'device_current_mA': mv.get('current_mA'),
                'pump_current_mA': mv.get('pump_current_mA'),
                'valve_current_mA': mv.get('valve_current_mA'),
                'ppk_current_mA': mv.get('ppk_current_mA'),
            }
            rows_tests.append(row_t)

    write_csv_per_pcb(rows_per_pcb, args.csv)
    write_csv_per_stage(rows_per_stage, args.per_stage)
    if args.export_tests:
        # Optional MAC filter for export as well
        to_write = rows_tests if not args.filter_mac else [r for r in rows_tests if str(r.get('mac') or '').lower() == args.filter_mac.lower()]
        write_csv_tests(to_write, args.export_tests)

    print(f"Wrote per-PCB CSV: {args.csv} ({len(rows_per_pcb)} rows)")
    print(f"Wrote per-stage CSV: {args.per_stage} ({len(rows_per_stage)} rows)")

    if args.plot:
        maybe_plot_per_stage(rows_per_stage)
    if args.plot_ts:
        maybe_plot_timeseries(rows_tests, filter_mac=args.filter_mac)
    if args.plot_power:
        maybe_plot_power(rows_tests, filter_mac=args.filter_mac)
    if args.plot_stage_box_power:
        maybe_plot_stage_box(rows_tests, metric='power')
    if args.plot_stage_box_current:
        maybe_plot_stage_box(rows_tests, metric='current')
    if args.plot_delta_power:
        maybe_plot_paired_deltas(rows_tests, baseline=args.delta_baseline, target=args.delta_target, metric='power', ttype=args.delta_type)
    if args.plot_delta_current:
        maybe_plot_paired_deltas(rows_tests, baseline=args.delta_baseline, target=args.delta_target, metric='current', ttype=args.delta_type)
    if args.plot_scatter_pump_valve:
        maybe_plot_scatter_pump_valve(rows_tests, stage=args.scatter_stage, metric=args.scatter_metric)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
