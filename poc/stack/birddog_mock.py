#!/usr/bin/env python3
"""
BirdDog REST API Mock Server — Bachelorproef Mediaventures
Bootst de BirdDog RESTful API 2.0 na (https://birddog.tv/AV/API/index.html).
Draait op poort 8090 (8080 is bezet door incontrol2-exporter).

Env-variabelen:
  BIRDDOG_MOCK_FAIL=1       Alle endpoints retourneren 503 (simuleert offline device).
  MOCK_PORT=8090            Luisterpoort (standaard 8090).
  MOCK_MODE=decode          Operatiemodus: "decode" (standaard) of "encode".
  MOCK_HOSTNAME=birddog-mock-01   Hostnaam die /about retourneert.
  MOCK_FIRMWARE=MOCK-3.2.1  Firmwareversie die /about retourneert.
  MOCK_SERIAL=MOCK-0001     Serienummer.
"""
import os
import logging
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

app = Flask(__name__)
MOCK_PORT = int(os.environ.get('MOCK_PORT', '8090'))
MOCK_MODE = os.environ.get('MOCK_MODE', 'decode').lower()
MOCK_HOSTNAME = os.environ.get('MOCK_HOSTNAME', 'birddog-mock-01')
MOCK_FIRMWARE = os.environ.get('MOCK_FIRMWARE', 'MOCK-3.2.1')
MOCK_SERIAL = os.environ.get('MOCK_SERIAL', 'MOCK-0001')


STATE = {
    'offline': os.environ.get('BIRDDOG_MOCK_FAIL', '0') == '1',
    'decode_connected': True,
    'encode_clients': 2,
}


def fail_mode():
    return STATE['offline']


@app.before_request
def check_fail():
    if fail_mode() and not request.path.startswith("/control/"):
        return jsonify({"error": "device unavailable"}), 503


# ── Test control endpoints (niet in echte BirdDog API — enkel voor scenario 9) ──

@app.route('/control/offline', methods=['POST'])
def control_offline():
    STATE['offline'] = True
    return jsonify({"ok": True, "state": dict(STATE)})


@app.route('/control/online', methods=['POST'])
def control_online():
    STATE['offline'] = False
    return jsonify({"ok": True, "state": dict(STATE)})


@app.route('/control/disconnect', methods=['POST'])
def control_disconnect():
    STATE['decode_connected'] = False
    STATE['encode_clients'] = 0
    return jsonify({"ok": True, "state": dict(STATE)})


@app.route('/control/connect', methods=['POST'])
def control_connect():
    STATE['decode_connected'] = True
    STATE['encode_clients'] = 2
    return jsonify({"ok": True, "state": dict(STATE)})


@app.route('/about')
def about():
    return jsonify({
        "FirmwareVersion": MOCK_FIRMWARE,
        "HostName": MOCK_HOSTNAME,
        "IPAddress": "10.1.1.100",
        "SerialNumber": MOCK_SERIAL,
        "Status": "OK",
        "NetworkConfig": "Static",
        "NetworkMask": "255.255.255.0",
        "Model": "BirdDog P200 (Mock)"
    })


@app.route('/version')
def version():
    return f"BirdDog-MOCK P200A4_A5 ({MOCK_MODE})", 200, {'Content-Type': 'text/plain'}


@app.route('/operationmode', methods=['GET'])
def operationmode():
    return MOCK_MODE, 200, {'Content-Type': 'text/plain'}


# ── Decode endpoints ──────────────────────────────────────────────────────────

@app.route('/decodeStatus')
def decode_status():
    if MOCK_MODE != 'decode':
        return jsonify({"error": "not in decode mode"}), 404
    connected = STATE['decode_connected']
    return jsonify({
        "connected": connected,
        "sourceName": "OBSERVABILITY (NDI Test Stream)" if connected else "",
        "framerate": 25.0 if connected else 0.0,
        "resolution": "1280x720" if connected else "",
        "bitrateKbps": 25000 if connected else 0,
        "droppedFrames": 0
    })


@app.route('/decodesetup', methods=['GET'])
def decodesetup():
    return jsonify({
        "NDIDecodeSlots": 1,
        "LowLatency": "off",
        "DecodeMode": "Quality"
    })


# ── Encode endpoints ──────────────────────────────────────────────────────────

@app.route('/encodeStatus')
def encode_status():
    if MOCK_MODE != 'encode':
        return jsonify({"error": "not in encode mode"}), 404
    clients = STATE['encode_clients']
    return jsonify({
        "sourceName": f"{MOCK_HOSTNAME.upper()} (HDMI)",
        "framerate": 25.0,
        "resolution": "1920x1080",
        "bitrateKbps": 50000 if clients > 0 else 0,
        "clientsConnected": clients,
        "droppedFrames": 0
    })


@app.route('/encodeSetup', methods=['GET'])
def encode_setup():
    return jsonify({
        "NDIEncodeSlots": 1,
        "BitrateMode": "CBR",
        "TargetBitrateKbps": 50000,
        "Resolution": "1920x1080",
        "FrameRate": "25"
    })


# ── NDI discovery ──────────────────────────────────────────────────────────────

@app.route('/list')
def ndi_list():
    """NDIFinder bronnenlijst — officieel endpoint is GET /list (BirdDog API 2.0)."""
    return jsonify([
        {"name": "OBSERVABILITY (NDI Test Stream)", "url": "10.1.1.100:5960"},
        {"name": "MOCK-CAM-01", "url": "10.1.1.200:5961"},
        {"name": "MOCK-CAM-02", "url": "10.1.1.201:5961"}
    ])


@app.route('/refresh', methods=['GET', 'POST'])
def ndi_refresh():
    return jsonify({"status": "refreshed"})


@app.route('/videooutputinterface', methods=['GET'])
def videooutputinterface():
    return jsonify({"videooutputinterface": "hdmi"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=MOCK_PORT)
