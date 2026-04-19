#!/usr/bin/env python3
"""Add NDI section 12 to Grafana dashboard."""
import json, sys

PATH = '/opt/observability/provisioning/dashboards/peplink.json'
d = json.load(open(PATH))

DS = {"type": "prometheus", "uid": "prometheus"}

def stat(pid, title, x, y, w, h, expr, legend, mappings=None, unit="short", decimals=None, thresholds=None):
    p = {
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
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p

def gauge(pid, title, x, y, w, h, expr, legend, unit, thresh_steps, max_val=None, decimals=None):
    p = {
        "id": pid, "type": "gauge", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto", "showThresholdLabels": False, "showThresholdMarkers": True
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": thresh_steps}
            },
            "overrides": []
        },
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend}],
        "datasource": DS
    }
    if max_val is not None:
        p["fieldConfig"]["defaults"]["max"] = max_val
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p

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

Y = 149
row = {
    "id": 200, "type": "row", "title": "12. NDI Stream Kwaliteit",
    "collapsed": False,
    "gridPos": {"x": 0, "y": Y, "w": 24, "h": 1},
    "panels": [],
    "datasource": DS
}

y1 = Y + 1
# Row 1: 4 stat/gauge panels (stream active, fps, drop rate, resolution)
p_active = stat(201, "Stream Active", 0, y1, 4, 4,
                'ndi_stream_active{source=~".*"}', "{{source}}",
                mappings=[
                    {"type": "value", "options": {"0": {"text": "OFFLINE", "color": "red"}}},
                    {"type": "value", "options": {"1": {"text": "LIVE", "color": "green"}}}
                ],
                thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]})

p_fps = gauge(202, "Frame Rate (fps)", 4, y1, 5, 4,
              'ndi_video_fps{source=~".*"}', "{{source}}", "none",
              [{"value": None, "color": "red"}, {"value": 23, "color": "yellow"}, {"value": 24, "color": "green"}],
              max_val=60, decimals=1)

p_drop = gauge(203, "Frame Drop Rate (%)", 9, y1, 5, 4,
               'ndi_frame_drop_rate{source=~".*"}', "{{source}}", "percent",
               [{"value": None, "color": "green"}, {"value": 1, "color": "yellow"}, {"value": 5, "color": "red"}],
               max_val=10, decimals=2)

p_sources = stat(207, "Bronnen gedetecteerd (mDNS)", 14, y1, 5, 4,
                 'ndi_sources_detected', "", unit="short",
                 thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1, "color": "green"}]})

p_sdk = stat(208, "NDI SDK", 19, y1, 5, 4,
             'ndi_sdk_available', "",
             mappings=[
                 {"type": "value", "options": {"0": {"text": "DISCOVERY-ONLY", "color": "yellow"}}},
                 {"type": "value", "options": {"1": {"text": "SDK GELADEN", "color": "green"}}}
             ],
             thresholds={"mode": "absolute", "steps": [{"value": None, "color": "yellow"}, {"value": 1, "color": "green"}]})

# Row 2: fps + queue depth, frames rate
y2 = y1 + 4
p_fps_ts = timeseries(204, "Framerate over tijd", 0, y2, 12, 8,
                      [{"datasource": DS, "expr": 'ndi_video_fps{source=~".*"}', "legendFormat": "{{source}} fps"}],
                      unit="none")

p_queue = timeseries(205, "Receiver Queue Depth (buffer)", 12, y2, 12, 8,
                     [{"datasource": DS, "expr": 'ndi_queue_depth_frames{source=~".*"}', "legendFormat": "{{source}}"}],
                     unit="short")

# Row 3: drops + frames received
y3 = y2 + 8
p_drops_ts = timeseries(206, "Frames ontvangen vs. gedropt (rate/s)", 0, y3, 12, 8,
                        [
                            {"datasource": DS, "expr": 'rate(ndi_frames_received_total[1m])', "legendFormat": "ontvangen/s"},
                            {"datasource": DS, "expr": 'rate(ndi_frames_dropped_total[1m])', "legendFormat": "gedropt/s"}
                        ],
                        unit="short",
                        overrides=[
                            {"matcher": {"id": "byName", "options": "ontvangen/s"},
                             "properties": [{"id": "color", "value": {"fixedColor": "#73BF69", "mode": "fixed"}}]},
                            {"matcher": {"id": "byName", "options": "gedropt/s"},
                             "properties": [{"id": "color", "value": {"fixedColor": "#F2495C", "mode": "fixed"}}]}
                        ])

p_drop_ts = timeseries(209, "Frame Drop Rate (%) over tijd", 12, y3, 12, 8,
                       [{"datasource": DS, "expr": 'ndi_frame_drop_rate{source=~".*"}', "legendFormat": "{{source}}"}],
                       unit="percent",
                       overrides=[{"matcher": {"id": "byName", "options": "NDI Test Stream"},
                                   "properties": [{"id": "color", "value": {"fixedColor": "#FF9830", "mode": "fixed"}}]}])

new_panels = [row, p_active, p_fps, p_drop, p_sources, p_sdk, p_fps_ts, p_queue, p_drops_ts, p_drop_ts]

existing_ids = {p['id'] for p in d['panels']}
for p in new_panels:
    if p['id'] in existing_ids:
        print(f"SKIP duplicate id {p['id']}", file=sys.stderr)
        sys.exit(1)

d['panels'].extend(new_panels)
json.dump(d, open(PATH, 'w'), indent=2)
print(f"added {len(new_panels)} panels (ids 200-209), max_y now {y3+8}")
