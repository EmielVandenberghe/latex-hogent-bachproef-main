#!/usr/bin/env python3
"""
NDI Exporter — Bachelorproef Mediaventures
Verbindt met een NDI-bron, pollt frame-performance via NDI SDK ctypes,
en exposed metrics op http://0.0.0.0:9118/metrics.
Valt terug op mDNS-discovery (zeroconf) als NDI SDK niet beschikbaar is.
"""
import ctypes
import ctypes.util
import threading
import time
import os
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

NDI_SOURCE_NAME = os.environ.get('NDI_SOURCE_NAME', 'NDI Test Stream')
EXPORTER_PORT = int(os.environ.get('EXPORTER_PORT', '9118'))
COLLECT_INTERVAL = int(os.environ.get('COLLECT_INTERVAL', '5'))
# NDI_EXTRA_IPS: komma-gescheiden lijst van IPs waar de exporter extra zoekt naar bronnen.
# Nuttig als mDNS/Avahi niet beschikbaar is (bijv. loopback naar lokale sender).
# Standaard: 127.0.0.1 voor lokale teststream op dezelfde host.
NDI_EXTRA_IPS = os.environ.get('NDI_EXTRA_IPS', '127.0.0.1')

_metrics = {
    'sdk_available': 0,
    'source_count': 0,
    'stream_active': 0,
    'frames_received_total': 0,
    'frames_dropped_total': 0,
    'frame_drop_rate': 0.0,
    'video_fps': 0.0,
    'video_width': 0,
    'video_height': 0,
    'queue_depth': 0,
}
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# NDI SDK ctypes bindings
# ---------------------------------------------------------------------------

class NDIlib_source_t(ctypes.Structure):
    _fields_ = [('p_ndi_name', ctypes.c_char_p),
                ('p_url_address', ctypes.c_char_p)]

class NDIlib_find_create_t(ctypes.Structure):
    _fields_ = [('show_local_sources', ctypes.c_bool),
                ('p_groups', ctypes.c_char_p),
                ('p_extra_ips', ctypes.c_char_p)]

class NDIlib_recv_create_v3_t(ctypes.Structure):
    _fields_ = [('source_to_connect_to', NDIlib_source_t),
                ('color_format', ctypes.c_int32),
                ('bandwidth', ctypes.c_int32),
                ('allow_video_fields', ctypes.c_bool),
                ('p_ndi_recv_name', ctypes.c_char_p)]

class NDIlib_video_frame_v2_t(ctypes.Structure):
    _fields_ = [('xres', ctypes.c_int32),
                ('yres', ctypes.c_int32),
                ('FourCC', ctypes.c_int32),
                ('frame_rate_N', ctypes.c_int32),
                ('frame_rate_D', ctypes.c_int32),
                ('picture_aspect_ratio', ctypes.c_float),
                ('frame_format_type', ctypes.c_int32),
                ('timecode', ctypes.c_int64),
                ('p_data', ctypes.c_void_p),
                ('line_stride_in_bytes', ctypes.c_int32),
                ('p_metadata', ctypes.c_char_p),
                ('timestamp', ctypes.c_int64)]

class NDIlib_recv_performance_t(ctypes.Structure):
    _fields_ = [('video_frames', ctypes.c_int64),
                ('audio_frames', ctypes.c_int64),
                ('metadata_frames', ctypes.c_int64)]

class NDIlib_recv_queue_t(ctypes.Structure):
    _fields_ = [('video_frames', ctypes.c_int32),
                ('audio_frames', ctypes.c_int32),
                ('metadata_frames', ctypes.c_int32)]

# NDI constants
NDI_FRAME_TYPE_VIDEO = 1
NDI_RECV_COLOR_FORMAT_FASTEST = 100
NDI_RECV_BANDWIDTH_HIGHEST = 100


def load_ndi_sdk():
    """Laad de NDI SDK shared library via ctypes. Geeft (lib, None) of (None, error)."""
    for name in ('libndi.so.6', 'libndi.so.5', 'libndi.so.4', 'libndi.so'):
        try:
            lib = ctypes.CDLL(name)
            # Prototypes instellen
            lib.NDIlib_initialize.restype = ctypes.c_bool
            lib.NDIlib_initialize.argtypes = []

            lib.NDIlib_find_create_v2.restype = ctypes.c_void_p
            lib.NDIlib_find_create_v2.argtypes = [ctypes.POINTER(NDIlib_find_create_t)]

            lib.NDIlib_find_wait_for_sources.restype = ctypes.c_bool
            lib.NDIlib_find_wait_for_sources.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

            lib.NDIlib_find_get_current_sources.restype = ctypes.POINTER(NDIlib_source_t)
            lib.NDIlib_find_get_current_sources.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]

            lib.NDIlib_find_destroy.restype = None
            lib.NDIlib_find_destroy.argtypes = [ctypes.c_void_p]

            lib.NDIlib_recv_create_v3.restype = ctypes.c_void_p
            lib.NDIlib_recv_create_v3.argtypes = [ctypes.POINTER(NDIlib_recv_create_v3_t)]

            lib.NDIlib_recv_capture_v2.restype = ctypes.c_int32
            lib.NDIlib_recv_capture_v2.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(NDIlib_video_frame_v2_t),
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint32,
            ]

            lib.NDIlib_recv_free_video_v2.restype = None
            lib.NDIlib_recv_free_video_v2.argtypes = [ctypes.c_void_p,
                                                       ctypes.POINTER(NDIlib_video_frame_v2_t)]

            lib.NDIlib_recv_get_performance.restype = None
            lib.NDIlib_recv_get_performance.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(NDIlib_recv_performance_t),
                ctypes.POINTER(NDIlib_recv_performance_t),
            ]

            lib.NDIlib_recv_get_queue.restype = None
            lib.NDIlib_recv_get_queue.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(NDIlib_recv_queue_t)]

            lib.NDIlib_recv_destroy.restype = None
            lib.NDIlib_recv_destroy.argtypes = [ctypes.c_void_p]

            lib.NDIlib_destroy.restype = None
            lib.NDIlib_destroy.argtypes = []

            if not lib.NDIlib_initialize():
                return None, 'NDIlib_initialize() returned False'
            log.info('NDI SDK geladen: %s', name)
            return lib, None
        except OSError:
            continue
    return None, 'libndi.so.5/4 niet gevonden'


# ---------------------------------------------------------------------------
# Receiver loop (volledig NDI SDK)
# ---------------------------------------------------------------------------

def ndi_receiver_loop(lib):
    extra_ips_bytes = NDI_EXTRA_IPS.encode() if NDI_EXTRA_IPS else None
    find_cfg = NDIlib_find_create_t(show_local_sources=True,
                                     p_groups=None,
                                     p_extra_ips=extra_ips_bytes)
    log.info('NDI finder aangemaakt — extra IPs: %s', NDI_EXTRA_IPS or '(geen)')
    find_inst = lib.NDIlib_find_create_v2(ctypes.byref(find_cfg))
    if not find_inst:
        log.error('NDIlib_find_create_v2 mislukt')
        return

    recv_inst = None
    prev_total = 0
    prev_dropped = 0
    prev_ts = time.monotonic()

    with _lock:
        _metrics['sdk_available'] = 1

    while True:
        try:
            lib.NDIlib_find_wait_for_sources(find_inst, 1000)
            count = ctypes.c_uint32(0)
            src_ptr = lib.NDIlib_find_get_current_sources(find_inst, ctypes.byref(count))

            n = count.value
            with _lock:
                _metrics['source_count'] = n

            # Zoek de geconfigureerde bron
            target = None
            if src_ptr and n > 0:
                sources = (NDIlib_source_t * n).from_address(ctypes.addressof(src_ptr.contents))
                for i in range(n):
                    name = sources[i].p_ndi_name
                    if name:
                        name_str = name.decode('utf-8', errors='replace')
                        if NDI_SOURCE_NAME.lower() in name_str.lower():
                            target = sources[i]
                            break

            if target is None:
                if recv_inst:
                    lib.NDIlib_recv_destroy(recv_inst)
                    recv_inst = None
                with _lock:
                    _metrics['stream_active'] = 0
                time.sleep(COLLECT_INTERVAL)
                continue

            # Receiver aanmaken of herverbinden
            if recv_inst is None:
                cfg = NDIlib_recv_create_v3_t()
                cfg.source_to_connect_to.p_ndi_name = target.p_ndi_name
                cfg.source_to_connect_to.p_url_address = target.p_url_address
                cfg.color_format = NDI_RECV_COLOR_FORMAT_FASTEST
                cfg.bandwidth = NDI_RECV_BANDWIDTH_HIGHEST
                cfg.allow_video_fields = False
                cfg.p_ndi_recv_name = b'ndi-exporter'
                recv_inst = lib.NDIlib_recv_create_v3(ctypes.byref(cfg))
                if not recv_inst:
                    log.error('NDIlib_recv_create_v3 mislukt')
                    time.sleep(COLLECT_INTERVAL)
                    continue
                log.info('Verbonden met NDI-bron: %s',
                         target.p_ndi_name.decode('utf-8', errors='replace'))
                prev_total = 0
                prev_dropped = 0
                prev_ts = time.monotonic()

            # KRITIEK: drain de receiver continu, anders loopt de interne queue vol
            # en dropt NDI frames (zichtbaar als kunstmatige 50% drop rate met 5s-poll).
            # Bij 25 fps komt er elke 40 ms een frame binnen; we gebruiken een tight
            # drain-loop met korte timeout en een hard harvest-limiet ruim boven
            # de verwachte inflow voor het volledige COLLECT_INTERVAL.
            width = height = 0
            fps = 0.0
            drained_deadline = time.monotonic() + (COLLECT_INTERVAL - 0.1)
            max_frames_expected = COLLECT_INTERVAL * 120  # ondersteunt tot 120 fps
            drained = 0
            consecutive_empty = 0
            while time.monotonic() < drained_deadline and drained < max_frames_expected:
                vf = NDIlib_video_frame_v2_t()
                ftype = lib.NDIlib_recv_capture_v2(recv_inst, ctypes.byref(vf),
                                                   None, None, 5)
                if ftype == NDI_FRAME_TYPE_VIDEO:
                    width = vf.xres
                    height = vf.yres
                    if vf.frame_rate_D > 0:
                        fps = vf.frame_rate_N / vf.frame_rate_D
                    lib.NDIlib_recv_free_video_v2(recv_inst, ctypes.byref(vf))
                    drained += 1
                    consecutive_empty = 0
                elif ftype == 0:
                    # Queue leeg — kort wachten zodat volgend frame kan aankomen,
                    # maar blijf loopen om hele interval te bestrijken.
                    consecutive_empty += 1
                    if consecutive_empty > 3:
                        time.sleep(0.02)
                        consecutive_empty = 0

            # Performance stats
            perf_total = NDIlib_recv_performance_t()
            perf_drop = NDIlib_recv_performance_t()
            lib.NDIlib_recv_get_performance(recv_inst,
                                            ctypes.byref(perf_total),
                                            ctypes.byref(perf_drop))

            queue = NDIlib_recv_queue_t()
            lib.NDIlib_recv_get_queue(recv_inst, ctypes.byref(queue))

            now = time.monotonic()
            dt = now - prev_ts or 1e-9
            delta_total = perf_total.video_frames - prev_total
            delta_drop = perf_drop.video_frames - prev_dropped
            drop_rate = 0.0
            if (delta_total + delta_drop) > 0:
                drop_rate = delta_drop / (delta_total + delta_drop) * 100.0

            prev_total = perf_total.video_frames
            prev_dropped = perf_drop.video_frames
            prev_ts = now

            with _lock:
                _metrics['stream_active'] = 1
                _metrics['frames_received_total'] = perf_total.video_frames
                _metrics['frames_dropped_total'] = perf_drop.video_frames
                _metrics['frame_drop_rate'] = round(drop_rate, 3)
                _metrics['video_fps'] = round(fps, 2)
                _metrics['video_width'] = width
                _metrics['video_height'] = height
                _metrics['queue_depth'] = queue.video_frames

        except Exception as e:
            log.exception('NDI receiver fout: %s', e)
            if recv_inst:
                try:
                    lib.NDIlib_recv_destroy(recv_inst)
                except Exception:
                    pass
                recv_inst = None

        # Geen extra sleep — de drain-loop hierboven heeft COLLECT_INTERVAL al verbruikt.


# ---------------------------------------------------------------------------
# Fallback: mDNS discovery via zeroconf
# ---------------------------------------------------------------------------

def discovery_only_loop():
    try:
        from zeroconf import Zeroconf, ServiceBrowser

        class _Listener:
            def __init__(self):
                self._names = {}

            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                label = name.replace(f'.{type_}', '').replace('._ndi._tcp.local.', '')
                self._names[name] = label
                log.info('NDI bron ontdekt: %s', label)
                self._sync()

            def remove_service(self, zc, type_, name):
                self._names.pop(name, None)
                self._sync()

            def update_service(self, zc, type_, name):
                pass

            def _sync(self):
                with _lock:
                    _metrics['source_count'] = len(self._names)

        zc = Zeroconf()
        lst = _Listener()
        ServiceBrowser(zc, '_ndi._tcp.local.', lst)
        log.info('NDI SDK niet beschikbaar — discovery-only modus actief')
        while True:
            time.sleep(10)
    except ImportError:
        log.warning('zeroconf niet geïnstalleerd — geen NDI discovery mogelijk')
        while True:
            time.sleep(60)


# ---------------------------------------------------------------------------
# Prometheus output
# ---------------------------------------------------------------------------

def build_prometheus_output() -> str:
    with _lock:
        m = dict(_metrics)
    src = NDI_SOURCE_NAME
    defs = [
        ('ndi_sdk_available', 'gauge',
         '1 als NDI SDK beschikbaar is geladen', '', m['sdk_available']),
        ('ndi_sources_detected', 'gauge',
         'Aantal NDI-bronnen zichtbaar op het netwerk', '', m['source_count']),
        ('ndi_stream_active', 'gauge',
         '1 als een NDI-stream actief ontvangen wordt', f'{{source="{src}"}}', m['stream_active']),
        ('ndi_frames_received_total', 'counter',
         'Totaal ontvangen videoframes sinds start', f'{{source="{src}"}}', m['frames_received_total']),
        ('ndi_frames_dropped_total', 'counter',
         'Totaal gedropte videoframes sinds start', f'{{source="{src}"}}', m['frames_dropped_total']),
        ('ndi_frame_drop_rate', 'gauge',
         'Percentage gedropte frames in huidig meetinterval', f'{{source="{src}"}}', m['frame_drop_rate']),
        ('ndi_video_fps', 'gauge',
         'Huidige videoframerate', f'{{source="{src}"}}', m['video_fps']),
        ('ndi_video_width', 'gauge',
         'Videobeeldbreedte in pixels', f'{{source="{src}"}}', m['video_width']),
        ('ndi_video_height', 'gauge',
         'Videobeeldhoogte in pixels', f'{{source="{src}"}}', m['video_height']),
        ('ndi_queue_depth_frames', 'gauge',
         'Receiver video-wachtrijdiepte (bufferbezetting)', f'{{source="{src}"}}', m['queue_depth']),
    ]
    lines = []
    for name, kind, help_text, labels, value in defs:
        lines.append(f'# HELP {name} {help_text}')
        lines.append(f'# TYPE {name} {kind}')
        lines.append(f'{name}{labels} {value}')
    return '\n'.join(lines) + '\n'


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/metrics', '/metrics/'):
            body = build_prometheus_output().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(302)
            self.send_header('Location', '/metrics')
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    log.info('NDI Exporter gestart — bron="%s" poort=%d', NDI_SOURCE_NAME, EXPORTER_PORT)

    lib, err = load_ndi_sdk()
    if lib:
        t = threading.Thread(target=ndi_receiver_loop, args=(lib,), daemon=True)
    else:
        log.warning('NDI SDK niet geladen (%s) — valt terug op discovery', err)
        t = threading.Thread(target=discovery_only_loop, daemon=True)
    t.start()

    server = HTTPServer(('0.0.0.0', EXPORTER_PORT), MetricsHandler)
    log.info('Metrics beschikbaar op http://0.0.0.0:%d/metrics', EXPORTER_PORT)
    server.serve_forever()
