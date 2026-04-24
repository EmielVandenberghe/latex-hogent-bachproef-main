#!/usr/bin/env python3
"""Update BirdDog section 13 in Grafana dashboard.

Wijzigingen t.o.v. add_birddog_panels.py (initiële versie):
  1. Panels 221-224 ingekrompen van w=6 naar w=4 om ruimte te maken.
  2. Nieuw: panel 228 "Hostname" (x=16, w=4) — toont birddog_device_info label.
  3. Nieuw: panel 229 "Firmware versie" (x=20, w=4) — toont firmware label.
  4. Nieuw: panel 230 "NDI Bronnen over tijd" timeseries (x=0, w=12).
  5. Nieuw: panel 231 "Encode Framerate over tijd" timeseries (x=12, w=12).
  6. Nieuw: panel 232 "Encode Clients verbonden" stat (x=0, w=8).
  7. Nieuw: panel 233 "Encode Bitrate" stat (x=8, w=8).
  8. Panel 227 (statustabel) naar beneden verschoven (y+16).

Gebruik (op obs VM):
  python3 /opt/observability/update_birddog_panels.py
  docker compose restart grafana
"""
import json, sys, shutil, os

PATH = '/opt/observability/provisioning/dashboards/peplink.json'

bak = PATH + '.bak-pre-birddog-update'
if not os.path.exists(bak):
    shutil.copy2(PATH, bak)
    print(f"Backup: {bak}")

d = json.load(open(PATH))
DS = {"type": "prometheus", "uid": "prometheus"}

panels_by_id = {p['id']: p for p in d['panels']}

# ── 1. Bestaande stat-panels 221-224 inkrimpen van w=6 naar w=4 ───────────────
for pid in [221, 222, 223, 224]:
    if pid not in panels_by_id:
        print(f"WAARSCHUWING: panel {pid} niet gevonden, overgeslagen.", file=sys.stderr)
        continue
    panels_by_id[pid]['gridPos']['w'] = 4
print("Panels 221-224: w=6 → w=4")

# y-coördinaten vanuit add_birddog_panels.py:
#   Y=170 (row), y1=171 (stat, h=4), y2=175 (ts, h=8), y3=183 (tabel, h=6)
y1 = 171
y2 = y1 + 4   # 175
y_mid = y2 + 8  # 183 — nieuwe rij: NDI sources + encode fps
y3 = y_mid + 8  # 191 — tabel (verschoven)
y4 = y3 + 6    # 197 — encode clients/bitrate

# ── 2. Tabel (227) naar beneden schuiven ─────────────────────────────────────
if 227 in panels_by_id:
    panels_by_id[227]['gridPos']['y'] = y3
    print(f"Panel 227 (tabel): y → {y3}")


def stat_info(pid, title, x, label_key):
    """Stat-panel dat een label uit birddog_device_info toont (textMode=name)."""
    return {
        "id": pid, "type": "stat", "title": title,
        "gridPos": {"x": x, "y": y1, "w": 4, "h": 4},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto",
            "textMode": "name",
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto"
        },
        "fieldConfig": {
            "defaults": {
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"value": None, "color": "blue"}]},
                "unit": "short"
            },
            "overrides": []
        },
        "targets": [{
            "datasource": DS,
            "expr": f'birddog_device_info{{device=~".*"}}',
            "legendFormat": f"{{{{{label_key}}}}}",
            "instant": True
        }],
        "datasource": DS
    }


def stat_panel(pid, title, x, y, w, h, expr, legend, mappings=None, unit="short", thresholds=None):
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
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend, "instant": True}],
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


# ── 3. Nieuwe panels opbouwen ─────────────────────────────────────────────────
new_panels = []

# 228: Hostname
p_hostname = stat_info(228, "Hostname", 16, "hostname")
new_panels.append(p_hostname)

# 229: Firmware versie
p_firmware = stat_info(229, "Firmware versie", 20, "firmware")
new_panels.append(p_firmware)

# 230: NDI bronnen over tijd (timeseries)
p_ndi_ts = timeseries(
    230, "NDI Bronnen over tijd", 0, y_mid, 12, 8,
    [{"datasource": DS, "expr": 'birddog_ndi_sources_count{device=~".*"}',
      "legendFormat": "{{device}} bronnen"}],
    unit="short"
)
new_panels.append(p_ndi_ts)

# 231: Encode framerate over tijd (timeseries)
p_enc_fps_ts = timeseries(
    231, "Encode Framerate over tijd", 12, y_mid, 12, 8,
    [{"datasource": DS, "expr": 'birddog_encode_fps{device=~".*"}',
      "legendFormat": "{{device}} fps"}],
    unit="none",
    overrides=[{"matcher": {"id": "byName", "options": "mock-02 fps"},
                "properties": [{"id": "color", "value": {"fixedColor": "#5794F2", "mode": "fixed"}}]}]
)
new_panels.append(p_enc_fps_ts)

# 232: Encode clients verbonden
p_enc_clients = stat_panel(
    232, "Encode Clients verbonden", 0, y4, 8, 4,
    'birddog_encode_clients_connected{device=~".*"}', "{{device}}",
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "yellow"}, {"value": 1, "color": "green"}]}
)
new_panels.append(p_enc_clients)

# 233: Encode bitrate
p_enc_bitrate = stat_panel(
    233, "Encode Bitrate", 8, y4, 8, 4,
    'birddog_encode_bitrate_kbps{device=~".*"}', "{{device}}",
    unit="Kbits",
    thresholds={"mode": "absolute", "steps": [{"value": None, "color": "red"}, {"value": 1000, "color": "green"}]}
)
new_panels.append(p_enc_bitrate)

# ── 4. Deduplicatie check + toevoegen ────────────────────────────────────────
existing_ids = {p['id'] for p in d['panels']}
for p in new_panels:
    if p['id'] in existing_ids:
        print(f"FOUT: duplicate panel id {p['id']} — script al eerder uitgevoerd?", file=sys.stderr)
        sys.exit(1)

d['panels'].extend(new_panels)
json.dump(d, open(PATH, 'w'), indent=2)
print(f"OK: {len(new_panels)} nieuwe panels toegevoegd (ids 228-233)")
print(f"  Tabel (227) verschoven naar y={y3}")
print(f"  NDI bronnen timeseries (230) op y={y_mid}")
print(f"  Encode fps timeseries (231) op y={y_mid}")
print(f"  Encode clients (232) + bitrate (233) op y={y4}")
print("Herstart Grafana: docker compose restart grafana")
