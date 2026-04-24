#!/usr/bin/env python3
"""Herwerkt sectie 13 (BirdDog) van peplink.json:
- mode-specifieke panels filteren via `and on(device) birddog_operation_mode_{decode,encode}`
- statustabel krijgt duidelijkere transforms + instance/job/__name__/Time verbergen
- layout netter: 4 info-stats + 4 status-stats + 2 framerate-charts + 2 charts + tabel
"""
import json
import shutil
from pathlib import Path

DASH = Path(__file__).parent / "provisioning" / "dashboards" / "peplink.json"

dash = json.loads(DASH.read_text(encoding="utf-8"))

# Verwijder alle oude BirdDog panels (row 220 + ids 221-233)
BIRDDOG_IDS = {220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233}
dash["panels"] = [p for p in dash["panels"] if p.get("id") not in BIRDDOG_IDS]

PROM_DS = {"type": "prometheus", "uid": "prometheus"}

def stat(pid, title, expr, x, y, w, h, mappings=None, thresholds=None, unit="short",
         text_mode="auto", color_mode="background", legend_format="{{device}}",
         instant=True):
    panel = {
        "id": pid,
        "type": "stat",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto",
            "textMode": text_mode,
            "colorMode": color_mode,
            "graphMode": "none",
            "justifyMode": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "mappings": mappings or [],
                "thresholds": thresholds or {"mode": "absolute", "steps": [{"value": None, "color": "blue"}]},
                "unit": unit,
            },
            "overrides": [],
        },
        "targets": [{
            "datasource": PROM_DS,
            "expr": expr,
            "legendFormat": legend_format,
            "instant": instant,
        }],
        "datasource": PROM_DS,
    }
    return panel


def timeseries(pid, title, targets, x, y, w, h, unit="none"):
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "tooltip": {"mode": "multi", "sort": "none"},
            "legend": {"displayMode": "list", "placement": "bottom"},
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"lineWidth": 2, "fillOpacity": 10, "spanNulls": False},
            },
            "overrides": [],
        },
        "targets": targets,
        "datasource": PROM_DS,
    }


ROW_Y = 170
# Mappings
online_map = [
    {"type": "value", "options": {"0": {"text": "OFFLINE", "color": "red"}}},
    {"type": "value", "options": {"1": {"text": "ONLINE", "color": "green"}}},
]
online_thr = {"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]}

mode_map = [
    {"type": "value", "options": {"0": {"text": "ENCODE", "color": "blue"}}},
    {"type": "value", "options": {"1": {"text": "DECODE", "color": "green"}}},
]
mode_thr = {"mode": "absolute", "steps": [{"value": None, "color": "blue"}, {"value": 1, "color": "green"}]}

connected_map = [
    {"type": "value", "options": {"0": {"text": "GEEN BRON", "color": "red"}}},
    {"type": "value", "options": {"1": {"text": "VERBONDEN", "color": "green"}}},
]
connected_thr = {"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]}

new_panels = []

# Row header
new_panels.append({
    "id": 220,
    "type": "row",
    "title": "13. BirdDog Device Monitoring",
    "collapsed": False,
    "gridPos": {"x": 0, "y": ROW_Y, "w": 24, "h": 1},
    "panels": [],
    "datasource": PROM_DS,
})

# --- Rij 1 (y=171, h=4): algemene info, alle devices ---
y = ROW_Y + 1
new_panels.append(stat(
    221, "Device Online", "birddog_device_online",
    x=0, y=y, w=6, h=4, mappings=online_map, thresholds=online_thr,
))
new_panels.append(stat(
    222, "Operation Mode", "birddog_operation_mode_decode",
    x=6, y=y, w=6, h=4, mappings=mode_map, thresholds=mode_thr,
))
new_panels.append(stat(
    228, "Hostname", 'birddog_device_info',
    x=12, y=y, w=6, h=4, text_mode="name",
    legend_format="{{hostname}}",
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "blue"}]},
))
new_panels.append(stat(
    229, "Firmware versie", 'birddog_device_info',
    x=18, y=y, w=6, h=4, text_mode="name",
    legend_format="{{firmware}}",
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "blue"}]},
))

# --- Rij 2 (y=175, h=4): status per mode ---
y = ROW_Y + 5
# Decode Connected (alleen decoders)
new_panels.append(stat(
    223, "Decode Connected (decoders)",
    'birddog_decode_connected and on(device) birddog_operation_mode_decode == 1',
    x=0, y=y, w=6, h=4, mappings=connected_map, thresholds=connected_thr,
))
# NDI bronnen zichtbaar (alle devices)
new_panels.append(stat(
    224, "NDI Bronnen gevonden", "birddog_ndi_sources_count",
    x=6, y=y, w=6, h=4,
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]},
))
# Encode Clients (alleen encoders)
new_panels.append(stat(
    232, "Encode Clients (encoders)",
    'birddog_encode_clients_connected and on(device) birddog_operation_mode_encode == 1',
    x=12, y=y, w=6, h=4,
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "yellow"}, {"value": 1, "color": "green"}]},
))
# Encode Bitrate (alleen encoders)
new_panels.append(stat(
    233, "Encode Bitrate (encoders)",
    'birddog_encode_bitrate_kbps and on(device) birddog_operation_mode_encode == 1',
    x=18, y=y, w=6, h=4, unit="Kbits",
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1000, "color": "green"}]},
))

# --- Rij 3 (y=179, h=8): framerates per mode ---
y = ROW_Y + 9
new_panels.append(timeseries(
    225, "Decode Framerate (decoders)",
    targets=[{
        "datasource": PROM_DS,
        "expr": 'birddog_decode_fps and on(device) birddog_operation_mode_decode == 1',
        "legendFormat": "{{device}} fps",
    }],
    x=0, y=y, w=12, h=8,
))
new_panels.append(timeseries(
    231, "Encode Framerate (encoders)",
    targets=[{
        "datasource": PROM_DS,
        "expr": 'birddog_encode_fps and on(device) birddog_operation_mode_encode == 1',
        "legendFormat": "{{device}} fps",
    }],
    x=12, y=y, w=12, h=8,
))

# --- Rij 4 (y=187, h=8): bronnen over tijd + dropped frames ---
y = ROW_Y + 17
new_panels.append(timeseries(
    230, "NDI Bronnen gezien (tijdreeks)",
    targets=[{
        "datasource": PROM_DS,
        "expr": "birddog_ndi_sources_count",
        "legendFormat": "{{device}}",
    }],
    x=0, y=y, w=12, h=8, unit="short",
))
new_panels.append(timeseries(
    226, "Gedropt frames cumulatief (decoders)",
    targets=[{
        "datasource": PROM_DS,
        "expr": 'birddog_decode_dropped_frames_total and on(device) birddog_operation_mode_decode == 1',
        "legendFormat": "{{device}} dropped",
    }],
    x=12, y=y, w=12, h=8, unit="short",
))

# --- Rij 5 (y=195, h=6): Status tabel ---
y = ROW_Y + 25
tabel = {
    "id": 227,
    "type": "table",
    "title": "BirdDog Status Overzicht",
    "gridPos": {"x": 0, "y": y, "w": 24, "h": 6},
    "options": {"showHeader": True},
    "fieldConfig": {
        "defaults": {
            "custom": {"align": "auto"},
        },
        "overrides": [
            {
                "matcher": {"id": "byName", "options": "Online"},
                "properties": [
                    {"id": "mappings", "value": [
                        {"type": "value", "options": {"0": {"text": "OFFLINE", "color": "red"}}},
                        {"type": "value", "options": {"1": {"text": "ONLINE", "color": "green"}}},
                    ]},
                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                ],
            },
            {
                "matcher": {"id": "byName", "options": "Mode"},
                "properties": [
                    {"id": "mappings", "value": [
                        {"type": "value", "options": {"0": {"text": "ENCODE", "color": "blue"}}},
                        {"type": "value", "options": {"1": {"text": "DECODE", "color": "green"}}},
                    ]},
                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                ],
            },
        ],
    },
    "targets": [
        {"datasource": PROM_DS, "expr": "birddog_device_online", "legendFormat": "{{device}}", "instant": True, "refId": "A"},
        {"datasource": PROM_DS, "expr": "birddog_operation_mode_decode", "legendFormat": "{{device}}", "instant": True, "refId": "B"},
        {"datasource": PROM_DS, "expr": "birddog_ndi_sources_count", "legendFormat": "{{device}}", "instant": True, "refId": "C"},
        {"datasource": PROM_DS, "expr": "birddog_decode_fps", "legendFormat": "{{device}}", "instant": True, "refId": "D"},
        {"datasource": PROM_DS, "expr": "birddog_encode_fps", "legendFormat": "{{device}}", "instant": True, "refId": "E"},
        {"datasource": PROM_DS, "expr": "birddog_encode_bitrate_kbps", "legendFormat": "{{device}}", "instant": True, "refId": "F"},
        {"datasource": PROM_DS, "expr": "birddog_decode_dropped_frames_total", "legendFormat": "{{device}}", "instant": True, "refId": "G"},
    ],
    "datasource": PROM_DS,
    "transformations": [
        {"id": "labelsToFields", "options": {"mode": "columns"}},
        {"id": "joinByField", "options": {"byField": "device", "mode": "outer"}},
        {"id": "organize", "options": {
            "excludeByName": {
                "Time 1": True, "Time 2": True, "Time 3": True, "Time 4": True,
                "Time 5": True, "Time 6": True, "Time 7": True,
                "__name__ 1": True, "__name__ 2": True, "__name__ 3": True, "__name__ 4": True,
                "__name__ 5": True, "__name__ 6": True, "__name__ 7": True,
                "instance 1": True, "instance 2": True, "instance 3": True, "instance 4": True,
                "instance 5": True, "instance 6": True, "instance 7": True,
                "job 1": True, "job 2": True, "job 3": True, "job 4": True,
                "job 5": True, "job 6": True, "job 7": True,
            },
            "renameByName": {
                "device": "Device",
                "Value #A": "Online",
                "Value #B": "Mode",
                "Value #C": "NDI bronnen",
                "Value #D": "Decode FPS",
                "Value #E": "Encode FPS",
                "Value #F": "Bitrate (kbps)",
                "Value #G": "Dropped frames",
            },
            "indexByName": {
                "Device": 0, "Online": 1, "Mode": 2, "NDI bronnen": 3,
                "Decode FPS": 4, "Encode FPS": 5, "Bitrate (kbps)": 6, "Dropped frames": 7,
            },
        }},
    ],
}
new_panels.append(tabel)

# Append panels
dash["panels"].extend(new_panels)

DASH.write_text(json.dumps(dash, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Updated {DASH} — {len(new_panels)} BirdDog panels geschreven.")
