#!/usr/bin/env python3
"""Add BirdDog section 13 to Grafana dashboard.

Gebruik (op obs VM):
  python3 /opt/observability/add_birddog_panels.py
  # Herstart Grafana om nieuwe provisioning op te pikken:
  docker compose restart grafana
"""
import json, sys

PATH = '/opt/observability/provisioning/dashboards/peplink.json'

import shutil, os
bak = PATH + '.bak-pre-birddog'
if not os.path.exists(bak):
    shutil.copy2(PATH, bak)
    print(f"Backup: {bak}")

d = json.load(open(PATH))
DS = {"type": "prometheus", "uid": "prometheus"}


def stat(pid, title, x, y, w, h, expr, legend, mappings=None, unit="short", thresholds=None):
    return {
        "id": pid, "type": "stat", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto", "textMode": "auto",
            "colorMode": "background", "graphMode": "none", "justifyMode": "auto"
        },
        "fieldConfig": {
            "defaults": {
                "mappings": mappings or [],
                "thresholds": thresholds or {"mode": "absolute", "steps": [{"value": None, "color": "green"}]},
                "unit": unit
            },
            "overrides": []
        },
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend}],
        "datasource": DS
    }


def timeseries(pid, title, x, y, w, h, targets, unit="short", overrides=None):
    return {
        "id": pid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "tooltip": {"mode": "multi", "sort": "none"},
            "legend": {"displayMode": "list", "placement": "bottom"}
        },
        "fieldConfig": {
            "defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10, "spanNulls": False}},
            "overrides": overrides or []
        },
        "targets": targets,
        "datasource": DS
    }


def table_panel(pid, title, x, y, w, h, targets):
    return {
        "id": pid, "type": "table", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"showHeader": True},
        "fieldConfig": {"defaults": {}, "overrides": []},
        "targets": targets,
        "datasource": DS,
        "transformations": [
            {"id": "labelsToFields", "options": {"mode": "columns"}},
            {"id": "joinByField", "options": {"byField": "device", "mode": "outer"}},
            {"id": "organize", "options": {
                "renameByName": {
                    "Value #A": "Online",
                    "Value #B": "Decode connected",
                    "Value #C": "FPS",
                    "Value #D": "NDI bronnen",
                    "Value #E": "Dropped frames"
                }
            }}
        ]
    }


# NDI section eindigt bij y=149+1+4+8+8=170 → BirdDog begint op y=170
Y = 170
row = {
    "id": 220, "type": "row", "title": "13. BirdDog Device Monitoring",
    "collapsed": False,
    "gridPos": {"x": 0, "y": Y, "w": 24, "h": 1},
    "panels": [],
    "datasource": DS
}

y1 = Y + 1

p_online = stat(221, "Device Online", 0, y1, 6, 4,
                'birddog_device_online{device=~".*"}', "{{device}}",
                mappings=[
                    {"type": "value", "options": {"0": {"text": "OFFLINE", "color": "red"}}},
                    {"type": "value", "options": {"1": {"text": "ONLINE", "color": "green"}}}
                ],
                thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]})

p_mode = stat(222, "Operation Mode", 6, y1, 6, 4,
              'birddog_operation_mode_decode{device=~".*"}', "{{device}}",
              mappings=[
                  {"type": "value", "options": {"0": {"text": "ENCODE", "color": "blue"}}},
                  {"type": "value", "options": {"1": {"text": "DECODE", "color": "green"}}}
              ],
              thresholds={"mode": "absolute", "steps": [{"value": None, "color": "blue"}, {"value": 1, "color": "green"}]})

p_connected = stat(223, "Decode Connected", 12, y1, 6, 4,
                   'birddog_decode_connected{device=~".*"}', "{{device}}",
                   mappings=[
                       {"type": "value", "options": {"0": {"text": "GEEN BRON", "color": "red"}}},
                       {"type": "value", "options": {"1": {"text": "VERBONDEN", "color": "green"}}}
                   ],
                   thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]})

p_sources = stat(224, "NDI Bronnen gevonden", 18, y1, 6, 4,
                 'birddog_ndi_sources_count{device=~".*"}', "{{device}}",
                 unit="short",
                 thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]})

y2 = y1 + 4

p_fps_ts = timeseries(225, "Decode Framerate over tijd", 0, y2, 12, 8,
                      [{"datasource": DS, "expr": 'birddog_decode_fps{device=~".*"}',
                        "legendFormat": "{{device}} fps"}],
                      unit="none",
                      overrides=[{"matcher": {"id": "byName", "options": "mock-01 fps"},
                                  "properties": [{"id": "color", "value": {"fixedColor": "#73BF69", "mode": "fixed"}}]}])

p_drops_ts = timeseries(226, "Gedropt frames (cumulatief)", 12, y2, 12, 8,
                        [{"datasource": DS,
                          "expr": 'birddog_decode_dropped_frames_total{device=~".*"}',
                          "legendFormat": "{{device}} dropped"}],
                        unit="short",
                        overrides=[{"matcher": {"id": "byName", "options": "mock-01 dropped"},
                                    "properties": [{"id": "color", "value": {"fixedColor": "#F2495C", "mode": "fixed"}}]}])

y3 = y2 + 8

p_table = table_panel(227, "BirdDog Status Overzicht", 0, y3, 24, 6,
                      [
                          {"datasource": DS, "expr": 'birddog_device_online{device=~".*"}',
                           "legendFormat": "{{device}}", "instant": True},
                          {"datasource": DS, "expr": 'birddog_decode_connected{device=~".*"}',
                           "legendFormat": "{{device}}", "instant": True},
                          {"datasource": DS, "expr": 'birddog_decode_fps{device=~".*"}',
                           "legendFormat": "{{device}}", "instant": True},
                          {"datasource": DS, "expr": 'birddog_ndi_sources_count{device=~".*"}',
                           "legendFormat": "{{device}}", "instant": True},
                          {"datasource": DS, "expr": 'birddog_decode_dropped_frames_total{device=~".*"}',
                           "legendFormat": "{{device}}", "instant": True},
                      ])

new_panels = [row, p_online, p_mode, p_connected, p_sources, p_fps_ts, p_drops_ts, p_table]

existing_ids = {p['id'] for p in d['panels']}
for p in new_panels:
    if p['id'] in existing_ids:
        print(f"FOUT: duplicate panel id {p['id']} — script al eerder uitgevoerd?", file=sys.stderr)
        sys.exit(1)

d['panels'].extend(new_panels)
json.dump(d, open(PATH, 'w'), indent=2)
print(f"OK: {len(new_panels)} panels toegevoegd (ids 220-227), BirdDog sectie 13 actief op y={Y}-{y3+6}")
