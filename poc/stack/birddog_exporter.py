#!/usr/bin/env python3
"""
BirdDog Exporter — Bachelorproef Mediaventures
Scrapt de BirdDog REST API 2.0 (officieel: birddog.tv/AV/API/index.html) per device
en exposed Prometheus-metrics op http://0.0.0.0:9119/metrics.

Env-variabelen:
  BIRDDOG_TARGETS   Komma-gescheiden lijst van "naam:host:poort"
                    bijv. "mock-01:birddog-mock:8090,cam01:192.168.1.50:8080"
  EXPORTER_PORT     Luisterpoort (standaard 9119)
  SCRAPE_INTERVAL   Seconden tussen scrapes (standaard 15)
"""
import os
import time
import threading
import logging
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

EXPORTER_PORT = int(os.environ.get('EXPORTER_PORT', '9119'))
SCRAPE_INTERVAL = int(os.environ.get('SCRAPE_INTERVAL', '15'))

_raw_targets = os.environ.get('BIRDDOG_TARGETS', 'mock-01:birddog-mock:8090')
TARGETS = []
for entry in _raw_targets.split(','):
    entry = entry.strip()
    if not entry:
        continue
    parts = entry.split(':')
    if len(parts) == 3:
        TARGETS.append({'name': parts[0], 'host': parts[1], 'port': parts[2]})
    else:
        log.warning("Ongeldige BIRDDOG_TARGETS entry (verwacht naam:host:poort): %s", entry)

_state: dict[str, dict] = {}
_lock = threading.Lock()


def fetch_json(url: str, timeout: int = 5):
    try:
        req = Request(url, headers={'Accept': 'application/json'})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (URLError, HTTPError, json.JSONDecodeError, Exception):
        return None


def fetch_text(url: str, timeout: int = 5) -> str | None:
    try:
        req = Request(url)
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip().strip('"')
    except Exception:
        return None


def scrape_device(name: str, host: str, port: str) -> dict:
    base = f"http://{host}:{port}"
    result = {
        'online': 0,
        'hostname': '',
        'firmware_version': '',
        'model': '',
        'operation_mode': 'unknown',
        'decode_connected': 0,
        'decode_fps': 0.0,
        'decode_width': 0,
        'decode_height': 0,
        'decode_dropped_total': 0,
        'encode_fps': 0.0,
        'encode_bitrate_kbps': 0,
        'encode_clients': 0,
        'ndi_sources_count': 0,
        'scrape_errors': 0,
        'scrape_duration': 0.0,
    }
    t0 = time.monotonic()

    about = fetch_json(f"{base}/about")
    if about is None:
        result['scrape_errors'] += 1
        result['scrape_duration'] = time.monotonic() - t0
        return result

    result['online'] = 1
    result['hostname'] = about.get('HostName', '')
    result['firmware_version'] = about.get('FirmwareVersion', '')
    result['model'] = about.get('Model', '')

    mode = fetch_text(f"{base}/operationmode")
    if mode:
        result['operation_mode'] = mode
    else:
        result['scrape_errors'] += 1

    if result['operation_mode'] == 'decode':
        status = fetch_json(f"{base}/decodeStatus")
        if status:
            result['decode_connected'] = 1 if status.get('connected', False) else 0
            result['decode_fps'] = float(status.get('framerate', 0.0))
            res = status.get('resolution', '0x0')
            try:
                w, h = res.split('x')
                result['decode_width'] = int(w)
                result['decode_height'] = int(h)
            except (ValueError, AttributeError):
                pass
            result['decode_dropped_total'] = int(status.get('droppedFrames', 0))
        else:
            result['scrape_errors'] += 1
    elif result['operation_mode'] == 'encode':
        status = fetch_json(f"{base}/encodeStatus")
        if status:
            result['encode_fps'] = float(status.get('framerate', 0.0))
            result['encode_bitrate_kbps'] = int(status.get('bitrateKbps', 0))
            result['encode_clients'] = int(status.get('clientsConnected', 0))
        else:
            result['scrape_errors'] += 1

    sources = fetch_json(f"{base}/list")
    if isinstance(sources, list):
        result['ndi_sources_count'] = len(sources)
    else:
        result['scrape_errors'] += 1

    result['scrape_duration'] = time.monotonic() - t0
    return result


def scrape_loop():
    while True:
        for t in TARGETS:
            data = scrape_device(t['name'], t['host'], t['port'])
            with _lock:
                _state[t['name']] = data
            log.info("BirdDog[%s] online=%d mode=%s hostname=%s fw=%s ndi_sources=%d errors=%d",
                     t['name'], data['online'], data['operation_mode'],
                     data['hostname'], data['firmware_version'],
                     data['ndi_sources_count'], data['scrape_errors'])
        time.sleep(SCRAPE_INTERVAL)


def render_metrics() -> str:
    lines = []

    def g(name, help_text, typ='gauge'):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {typ}")

    with _lock:
        state = dict(_state)

    g('birddog_device_online', 'BirdDog device bereikbaar via REST API (1=online, 0=offline)')
    for dev, d in state.items():
        lines.append(f'birddog_device_online{{device="{dev}"}} {d["online"]}')

    g('birddog_device_info', 'BirdDog device-metadata: hostname, firmware, model')
    for dev, d in state.items():
        hn = d['hostname'].replace('"', '\\"')
        fw = d['firmware_version'].replace('"', '\\"')
        mo = d['model'].replace('"', '\\"')
        lines.append(
            f'birddog_device_info{{device="{dev}",hostname="{hn}",firmware="{fw}",model="{mo}"}} 1'
        )

    g('birddog_operation_mode_encode', 'Device staat in encode-modus (1=ja, 0=nee)')
    for dev, d in state.items():
        lines.append(f'birddog_operation_mode_encode{{device="{dev}"}} {1 if d["operation_mode"] == "encode" else 0}')

    g('birddog_operation_mode_decode', 'Device staat in decode-modus (1=ja, 0=nee)')
    for dev, d in state.items():
        lines.append(f'birddog_operation_mode_decode{{device="{dev}"}} {1 if d["operation_mode"] == "decode" else 0}')

    g('birddog_decode_connected', 'BirdDog is verbonden met een NDI-bron (1=ja, 0=nee)')
    for dev, d in state.items():
        lines.append(f'birddog_decode_connected{{device="{dev}"}} {d["decode_connected"]}')

    g('birddog_decode_fps', 'Huidig ontvangen framerate van de NDI-bron')
    for dev, d in state.items():
        lines.append(f'birddog_decode_fps{{device="{dev}"}} {d["decode_fps"]:.2f}')

    g('birddog_decode_width', 'Breedte van het gedecodeerde videoframe in pixels')
    for dev, d in state.items():
        lines.append(f'birddog_decode_width{{device="{dev}"}} {d["decode_width"]}')

    g('birddog_decode_height', 'Hoogte van het gedecodeerde videoframe in pixels')
    for dev, d in state.items():
        lines.append(f'birddog_decode_height{{device="{dev}"}} {d["decode_height"]}')

    g('birddog_decode_dropped_frames_total', 'Totaal aantal gedropt frames sinds laatste reset', typ='counter')
    for dev, d in state.items():
        lines.append(f'birddog_decode_dropped_frames_total{{device="{dev}"}} {d["decode_dropped_total"]}')

    g('birddog_ndi_sources_count', 'Aantal NDI-bronnen gevonden via /list')
    for dev, d in state.items():
        lines.append(f'birddog_ndi_sources_count{{device="{dev}"}} {d["ndi_sources_count"]}')

    g('birddog_encode_fps', 'Huidig geëncodeerde framerate (alleen encode-modus)')
    for dev, d in state.items():
        lines.append(f'birddog_encode_fps{{device="{dev}"}} {d["encode_fps"]:.2f}')

    g('birddog_encode_bitrate_kbps', 'NDI encode output bitrate in kbps (alleen encode-modus)')
    for dev, d in state.items():
        lines.append(f'birddog_encode_bitrate_kbps{{device="{dev}"}} {d["encode_bitrate_kbps"]}')

    g('birddog_encode_clients_connected', 'Aantal NDI-ontvangers verbonden met de encoder')
    for dev, d in state.items():
        lines.append(f'birddog_encode_clients_connected{{device="{dev}"}} {d["encode_clients"]}')

    g('birddog_scrape_errors_total', 'Aantal mislukte endpoint-requests in de laatste scrape-cyclus', typ='counter')
    for dev, d in state.items():
        lines.append(f'birddog_scrape_errors_total{{device="{dev}"}} {d["scrape_errors"]}')

    g('birddog_scrape_duration_seconds', 'Duur van de laatste BirdDog API scrape in seconden')
    for dev, d in state.items():
        lines.append(f'birddog_scrape_duration_seconds{{device="{dev}"}} {d["scrape_duration"]:.4f}')

    return '\n'.join(lines) + '\n'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/metrics', '/metrics/'):
            body = render_metrics().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    if not TARGETS:
        log.error("Geen geldige BIRDDOG_TARGETS geconfigureerd. Exitcode 1.")
        raise SystemExit(1)

    log.info("BirdDog exporter start — targets: %s", [t['name'] for t in TARGETS])
    t = threading.Thread(target=scrape_loop, daemon=True)
    t.start()

    server = HTTPServer(('0.0.0.0', EXPORTER_PORT), Handler)
    log.info("Metrics beschikbaar op http://0.0.0.0:%d/metrics", EXPORTER_PORT)
    server.serve_forever()
