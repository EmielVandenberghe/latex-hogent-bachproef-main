#!/usr/bin/env python3
"""InControl2 + SNMP + Local API Prometheus Exporter - Mediaventures PoC"""

import os
import time
import logging
import requests
import urllib3
from prometheus_client import start_http_server, Gauge, Counter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# SNMP imports
try:
    from pysnmp.hlapi import *
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Config
IC_API_BASE = "https://api.ic.peplink.com"
IC_CLIENT_ID = os.getenv("IC_CLIENT_ID")
IC_CLIENT_SECRET = os.getenv("IC_CLIENT_SECRET")
IC_ORG_ID = os.getenv("IC_ORG_ID", "a1pokv")
IC_GROUP_ID = os.getenv("IC_GROUP_ID", "4")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "8080"))

# SNMP Config
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")
SNMP_TIMEOUT = int(os.getenv("SNMP_TIMEOUT", "2"))
SNMP_ENABLED = os.getenv("SNMP_ENABLED", "true").lower() == "true"

# Device IPs voor directe SNMP polling (configureerbaar via env)
# Format: "device_name:ip,device_name:ip"
SNMP_TARGETS_RAW = os.getenv("SNMP_TARGETS", "Bornem:10.1.1.2,Venue:10.1.2.2,Live1:10.1.3.2,Live2:10.1.4.2")
SNMP_TARGETS = {}
if SNMP_TARGETS_RAW:
    for target in SNMP_TARGETS_RAW.split(","):
        if ":" in target:
            name, ip = target.split(":", 1)
            SNMP_TARGETS[name.strip()] = ip.strip()

# Local API Config — directe polling via Peplink web admin API
# Format: "device_name:ip:password,device_name:ip:password"
LOCAL_API_TARGETS_RAW = os.getenv("LOCAL_API_TARGETS", "")
LOCAL_API_TARGETS = {}
if LOCAL_API_TARGETS_RAW:
    for target in LOCAL_API_TARGETS_RAW.split(","):
        parts = target.strip().split(":")
        if len(parts) == 3:
            LOCAL_API_TARGETS[parts[0].strip()] = {"ip": parts[1].strip(), "password": parts[2].strip()}

# InControl2 API Metrics
device_online = Gauge('peplink_device_online', 'Device online (1) or offline (0)', ['device_id', 'device_name', 'site_id', 'serial'])
device_uptime = Gauge('peplink_device_uptime_seconds', 'Device uptime in seconds', ['device_id', 'device_name', 'site_id', 'serial'])
device_clients = Gauge('peplink_device_client_count', 'Connected clients', ['device_id', 'device_name', 'site_id', 'serial'])
device_usage = Gauge('peplink_device_usage_bytes', 'Bandwidth usage', ['device_id', 'device_name', 'site_id', 'serial'])
device_tx = Gauge('peplink_device_tx_bytes', 'TX bytes', ['device_id', 'device_name', 'site_id', 'serial'])
device_rx = Gauge('peplink_device_rx_bytes', 'RX bytes', ['device_id', 'device_name', 'site_id', 'serial'])

# SNMP Direct Metrics (sneller dan API)
snmp_device_reachable = Gauge('peplink_snmp_reachable', 'Device reachable via SNMP (1=yes, 0=no)', ['device_name', 'ip'])
snmp_device_uptime = Gauge('peplink_snmp_uptime_seconds', 'Uptime via SNMP', ['device_name', 'ip'])
snmp_cpu_usage = Gauge('peplink_snmp_cpu_percent', 'CPU usage via SNMP', ['device_name', 'ip'])
snmp_memory_usage = Gauge('peplink_snmp_memory_percent', 'Memory usage via SNMP', ['device_name', 'ip'])
snmp_interface_in = Gauge('peplink_snmp_interface_in_bytes', 'Interface RX bytes', ['device_name', 'ip', 'interface'])
snmp_interface_out = Gauge('peplink_snmp_interface_out_bytes', 'Interface TX bytes', ['device_name', 'ip', 'interface'])
snmp_response_time = Gauge('peplink_snmp_response_ms', 'SNMP response time in ms', ['device_name', 'ip'])

# SNMP Enterprise WAN Metrics (enkel fysieke Peplink hardware)
snmp_wan_status = Gauge('peplink_snmp_wan_status', 'WAN status (1=disabled,2=disconnected,3=connected)', ['device_name', 'ip', 'wan_name'])
snmp_wan_link = Gauge('peplink_snmp_wan_link_up', 'WAN link up (1) or down (0)', ['device_name', 'ip', 'wan_name'])
snmp_wan_signal = Gauge('peplink_snmp_wan_signal_dbm', 'WAN signal strength in dBm', ['device_name', 'ip', 'wan_name'])
snmp_wan_healthcheck = Gauge('peplink_snmp_wan_healthcheck', 'WAN health check status', ['device_name', 'ip', 'wan_name'])
snmp_wifi_clients = Gauge('peplink_snmp_wifi_client_count', 'WiFi connected clients', ['device_name', 'ip', 'ssid'])

# Local API Metrics (via Peplink web admin)
local_cpu_load = Gauge('peplink_local_cpu_load_percent', 'CPU load via local API', ['device_name', 'ip'])
local_ap_status = Gauge('peplink_local_ap_up', 'WiFi AP enabled (1) or disabled (0)', ['device_name', 'ip'])
local_api_reachable = Gauge('peplink_local_api_reachable', 'Local API reachable (1=yes, 0=no)', ['device_name', 'ip'])

# PepVPN Tunnel Metrics
tunnel_up = Gauge('peplink_tunnel_up', 'PepVPN tunnels healthy (1=ok, 0=error/unknown)', ['device_id', 'device_name'])
recent_event_count = Gauge('peplink_recent_event_count', 'Number of events in latest event log response', ['device_id', 'device_name'])

# Exporter metrics
scrape_success = Gauge('peplink_scrape_success', 'Last scrape successful (1) or failed (0)')
scrape_duration = Gauge('peplink_scrape_duration_seconds', 'Scrape duration')
api_errors = Counter('peplink_api_errors_total', 'API errors', ['endpoint'])
snmp_errors = Counter('peplink_snmp_errors_total', 'SNMP errors', ['device_name'])
local_api_errors = Counter('peplink_local_api_errors_total', 'Local API errors', ['device_name'])


class InControl2Client:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expires = 0
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
    
    def _get_token(self):
        if self.token and time.time() < self.token_expires - 60:
            return self.token
        
        log.info("Requesting OAuth2 token...")
        try:
            resp = self.session.post(
                f"{IC_API_BASE}/api/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials"
                }
            )
            resp.raise_for_status()
            data = resp.json()
            self.token = data["access_token"]
            self.token_expires = time.time() + data.get("expires_in", 172800)
            log.info("Token acquired (expires in %ds)", data.get("expires_in", 0))
            return self.token
        except Exception as e:
            log.error("Token request failed: %s", e)
            api_errors.labels(endpoint="oauth2/token").inc()
            raise
    
    def get(self, endpoint):
        token = self._get_token()
        try:
            resp = self.session.get(
                f"{IC_API_BASE}{endpoint}",
                headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.error("API error %s: %s", endpoint, e)
            api_errors.labels(endpoint=endpoint).inc()
            raise
    
    def get_devices_with_status(self, org_id):
        """Haal devices op met live status (has_status trigger)"""
        endpoint = f"/rest/o/{org_id}/d?has_status=1"
        self.get(endpoint)  # trigger
        time.sleep(2)
        result = self.get(endpoint)  # fetch
        if result.get("resp_code") == "SUCCESS":
            return result.get("data", [])
        return []

    def get_tunnel_stat(self, org_id, group_id, device_id):
        """Poll PepVPN tunnel status. Returns True=all ok, False=error, None=pending/unknown."""
        endpoint = f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/pepvpn/tunnel_stat"
        try:
            result = self.get(endpoint)
            code = result.get("resp_code")
            if code == "SUCCESS":
                data = result.get("data", {})
                # data can be a dict (single) or list (multiple tunnels)
                if isinstance(data, list):
                    if not data:
                        return True  # no tunnels configured = no errors
                    return all(t.get("stat") == "ok" for t in data if isinstance(t, dict))
                elif isinstance(data, dict):
                    return data.get("stat") == "ok"
            # PENDING - skip update this cycle
            return None
        except Exception as e:
            log.warning("tunnel_stat failed for device %s: %s", device_id, e)
            return False

    def get_event_count(self, org_id, group_id, device_id):
        """Haal event log op en geef aantal terug."""
        endpoint = f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/event_log"
        try:
            result = self.get(endpoint)
            if result.get("resp_code") == "SUCCESS":
                return len(result.get("data", []))
        except Exception as e:
            log.warning("event_log failed for device %s: %s", device_id, e)
        return None


# =============================================================================
# SNMP POLLING
# =============================================================================

# Peplink OIDs
OIDS = {
    'sysUpTime': '1.3.6.1.2.1.1.3.0',           # Uptime in timeticks (1/100 sec)
    'sysDescr': '1.3.6.1.2.1.1.1.0',            # System description
    'sysName': '1.3.6.1.2.1.1.5.0',             # Hostname
    # Interface stats (need to walk these)
    'ifDescr': '1.3.6.1.2.1.2.2.1.2',           # Interface descriptions
    'ifInOctets': '1.3.6.1.2.1.2.2.1.10',       # RX bytes
    'ifOutOctets': '1.3.6.1.2.1.2.2.1.16',      # TX bytes
    # Peplink specific (enterprise OIDs) — enkel op fysieke hardware
    'peplinkCpuLoad': '1.3.6.1.4.1.23695.200.1.1.1.2.1',
    'peplinkMemoryUsage': '1.3.6.1.4.1.23695.200.1.1.1.3.1',
    # Peplink enterprise WAN tabel (fysieke hardware, niet FusionHub)
    'peplinkWanCount': '1.3.6.1.4.1.23695.2.1.1.0',
    'peplinkWanName': '1.3.6.1.4.1.23695.2.1.2.1.2',      # .{index} = WAN naam
    'peplinkWanStatus': '1.3.6.1.4.1.23695.2.1.2.1.3',     # 1=disabled,2=disconnected,3=connected
    'peplinkWanLink': '1.3.6.1.4.1.23695.2.1.2.1.4',       # 1=up, 0=down
    'peplinkWanSignal': '1.3.6.1.4.1.23695.2.1.2.1.5',     # dBm, -9999=N/A
    'peplinkWanHealthCheck': '1.3.6.1.4.1.23695.2.1.2.1.8', # health check status
    # Peplink WiFi AP tabel (fysieke hardware)
    'peplinkSsidName': '1.3.6.1.4.1.23695.4.2.3.1.2',      # .{index} = SSID naam
    'peplinkSsidClients': '1.3.6.1.4.1.23695.4.2.3.1.4',   # .{index} = client count
}


def snmp_get(ip, oid, community=SNMP_COMMUNITY, timeout=SNMP_TIMEOUT):
    """Single SNMP GET request"""
    if not SNMP_AVAILABLE:
        return None
    
    try:
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),  # SNMPv2c
            UdpTransportTarget((ip, 161), timeout=timeout, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        
        if errorIndication or errorStatus:
            return None
        
        for varBind in varBinds:
            return varBind[1]
    except Exception as e:
        log.debug("SNMP GET failed for %s: %s", ip, e)
        return None


def snmp_walk(ip, oid, community=SNMP_COMMUNITY, timeout=SNMP_TIMEOUT):
    """SNMP WALK for tables"""
    if not SNMP_AVAILABLE:
        return []
    
    results = []
    try:
        for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            UdpTransportTarget((ip, 161), timeout=timeout, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False
        ):
            if errorIndication or errorStatus:
                break
            for varBind in varBinds:
                results.append((str(varBind[0]), varBind[1]))
    except Exception as e:
        log.debug("SNMP WALK failed for %s: %s", ip, e)
    
    return results


def poll_device_snmp(device_name, ip):
    """Poll een device via SNMP, return dict met metrics"""
    start_time = time.time()
    metrics = {
        'reachable': 0,
        'response_ms': 0,
        'uptime': None,
        'cpu': None,
        'memory': None,
        'interfaces': []
    }
    
    # Test reachability met uptime query
    uptime_raw = snmp_get(ip, OIDS['sysUpTime'])
    response_time = (time.time() - start_time) * 1000
    
    if uptime_raw is not None:
        metrics['reachable'] = 1
        metrics['response_ms'] = response_time
        # Uptime is in timeticks (1/100 sec)
        try:
            metrics['uptime'] = int(uptime_raw) / 100
        except:
            pass
        
        # CPU (Peplink specific OID)
        cpu = snmp_get(ip, OIDS['peplinkCpuLoad'])
        if cpu is not None:
            try:
                metrics['cpu'] = int(cpu)
            except:
                pass
        
        # Memory (Peplink specific OID)
        mem = snmp_get(ip, OIDS['peplinkMemoryUsage'])
        if mem is not None:
            try:
                metrics['memory'] = int(mem)
            except:
                pass
        
        # Interface stats
        if_descr = snmp_walk(ip, OIDS['ifDescr'])
        if_in = snmp_walk(ip, OIDS['ifInOctets'])
        if_out = snmp_walk(ip, OIDS['ifOutOctets'])
        
        # Match interfaces by index
        for i, (oid, descr) in enumerate(if_descr):
            if_index = oid.split('.')[-1]
            in_bytes = None
            out_bytes = None
            
            for in_oid, val in if_in:
                if in_oid.endswith('.' + if_index):
                    try:
                        in_bytes = int(val)
                    except:
                        pass
                    break
            
            for out_oid, val in if_out:
                if out_oid.endswith('.' + if_index):
                    try:
                        out_bytes = int(val)
                    except:
                        pass
                    break
            
            if in_bytes is not None or out_bytes is not None:
                metrics['interfaces'].append({
                    'name': str(descr),
                    'in_bytes': in_bytes,
                    'out_bytes': out_bytes
                })
    
    return metrics


def poll_enterprise_snmp(device_name, ip):
    """Poll Peplink enterprise WAN OIDs (enkel beschikbaar op fysieke hardware)"""
    if not SNMP_AVAILABLE:
        return

    # Check of enterprise OIDs beschikbaar zijn (WAN count)
    wan_count_raw = snmp_get(ip, OIDS['peplinkWanCount'])
    if wan_count_raw is None:
        return  # Geen enterprise OIDs (bv. FusionHub)

    try:
        wan_count = int(wan_count_raw)
    except (ValueError, TypeError):
        return

    log.debug("Enterprise SNMP: %s has %d WAN interfaces", device_name, wan_count)

    # WAN status per interface
    wan_names = snmp_walk(ip, OIDS['peplinkWanName'])
    wan_statuses = snmp_walk(ip, OIDS['peplinkWanStatus'])
    wan_links = snmp_walk(ip, OIDS['peplinkWanLink'])
    wan_signals = snmp_walk(ip, OIDS['peplinkWanSignal'])
    wan_health = snmp_walk(ip, OIDS['peplinkWanHealthCheck'])

    for i, (oid, name) in enumerate(wan_names):
        wan_name = str(name)
        labels = [device_name, ip, wan_name]

        if i < len(wan_statuses):
            try:
                snmp_wan_status.labels(*labels).set(int(wan_statuses[i][1]))
            except (ValueError, TypeError):
                pass

        if i < len(wan_links):
            try:
                snmp_wan_link.labels(*labels).set(int(wan_links[i][1]))
            except (ValueError, TypeError):
                pass

        if i < len(wan_signals):
            try:
                sig = int(wan_signals[i][1])
                if sig != -9999:  # -9999 = niet van toepassing
                    snmp_wan_signal.labels(*labels).set(sig)
            except (ValueError, TypeError):
                pass

        if i < len(wan_health):
            try:
                snmp_wan_healthcheck.labels(*labels).set(int(wan_health[i][1]))
            except (ValueError, TypeError):
                pass

    # WiFi AP info
    ssid_names = snmp_walk(ip, OIDS['peplinkSsidName'])
    ssid_clients = snmp_walk(ip, OIDS['peplinkSsidClients'])

    for i, (oid, name) in enumerate(ssid_names):
        ssid = str(name)
        if i < len(ssid_clients):
            try:
                snmp_wifi_clients.labels(device_name, ip, ssid).set(int(ssid_clients[i][1]))
            except (ValueError, TypeError):
                pass


def collect_snmp_metrics():
    """Collect SNMP metrics voor alle geconfigureerde targets"""
    if not SNMP_ENABLED or not SNMP_AVAILABLE:
        return

    if not SNMP_TARGETS:
        log.warning("SNMP enabled but no targets configured")
        return

    log.info("Collecting SNMP metrics for %d devices...", len(SNMP_TARGETS))

    for device_name, ip in SNMP_TARGETS.items():
        try:
            metrics = poll_device_snmp(device_name, ip)

            labels = [device_name, ip]

            snmp_device_reachable.labels(*labels).set(metrics['reachable'])
            snmp_response_time.labels(*labels).set(metrics['response_ms'])

            if metrics['uptime'] is not None:
                snmp_device_uptime.labels(*labels).set(metrics['uptime'])

            if metrics['cpu'] is not None:
                snmp_cpu_usage.labels(*labels).set(metrics['cpu'])

            if metrics['memory'] is not None:
                snmp_memory_usage.labels(*labels).set(metrics['memory'])

            for iface in metrics['interfaces']:
                if_labels = [device_name, ip, iface['name']]
                if iface['in_bytes'] is not None:
                    snmp_interface_in.labels(*if_labels).set(iface['in_bytes'])
                if iface['out_bytes'] is not None:
                    snmp_interface_out.labels(*if_labels).set(iface['out_bytes'])

            if metrics['reachable']:
                log.debug("SNMP OK: %s (%s) - %dms", device_name, ip, metrics['response_ms'])
                # Enterprise OIDs ophalen (WAN status, WiFi) — alleen op fysieke hardware
                poll_enterprise_snmp(device_name, ip)
            else:
                log.warning("SNMP UNREACHABLE: %s (%s)", device_name, ip)
                snmp_errors.labels(device_name).inc()

        except Exception as e:
            log.error("SNMP error for %s: %s", device_name, e)
            snmp_errors.labels(device_name).inc()


# =============================================================================
# LOCAL API POLLING (via Peplink web admin)
# =============================================================================

def poll_local_api(device_name, ip, password):
    """Poll een Peplink via de lokale REST API voor status.cpu en status.ap"""
    base = f"https://{ip}"
    try:
        session = requests.Session()
        login = session.post(
            f"{base}/cgi-bin/MANGA/api.cgi",
            json={"func": "login", "username": "admin", "password": password},
            verify=False, timeout=5
        )
        if login.json().get("stat") != "ok":
            log.warning("Local API login failed for %s", device_name)
            local_api_reachable.labels(device_name, ip).set(0)
            local_api_errors.labels(device_name).inc()
            return

        local_api_reachable.labels(device_name, ip).set(1)

        # CPU load
        r = session.post(f"{base}/cgi-bin/MANGA/api.cgi",
                         json={"func": "status.cpu"}, verify=False, timeout=5)
        data = r.json()
        if data.get("stat") == "ok":
            cpu_str = data.get("response", {}).get("cpu", {}).get("load", "0%")
            cpu_val = float(cpu_str.replace("%", ""))
            local_cpu_load.labels(device_name, ip).set(cpu_val)
            log.debug("Local API %s CPU: %s", device_name, cpu_str)

        # WiFi AP status
        r = session.post(f"{base}/cgi-bin/MANGA/api.cgi",
                         json={"func": "status.ap"}, verify=False, timeout=5)
        data = r.json()
        if data.get("stat") == "ok":
            ap_on = 1 if data.get("response", {}).get("status") == "on" else 0
            local_ap_status.labels(device_name, ip).set(ap_on)

    except Exception as e:
        log.warning("Local API error for %s: %s", device_name, e)
        local_api_reachable.labels(device_name, ip).set(0)
        local_api_errors.labels(device_name).inc()


def collect_local_api_metrics():
    """Collect metrics via lokale Peplink API voor alle geconfigureerde targets"""
    if not LOCAL_API_TARGETS:
        return

    log.info("Collecting local API metrics for %d devices...", len(LOCAL_API_TARGETS))
    for device_name, config in LOCAL_API_TARGETS.items():
        poll_local_api(device_name, config["ip"], config["password"])


def collect_metrics(client, org_id):
    start_time = time.time()
    success = True
    
    # InControl2 API metrics
    try:
        log.info("Collecting InControl2 API metrics...")
        devices = client.get_devices_with_status(org_id)
        
        for device in devices:
            labels = [
                str(device.get("id", "")),
                device.get("name", "unknown"),
                device.get("site_id", "unknown"),
                device.get("sn", "unknown")
            ]
            
            online = 1 if device.get("onlineStatus") == "ONLINE" else 0
            device_online.labels(*labels).set(online)
            
            if device.get("uptime"):
                device_uptime.labels(*labels).set(device["uptime"])
            
            device_clients.labels(*labels).set(device.get("client_count", 0))
            device_usage.labels(*labels).set(device.get("usage", 0) or 0)
            device_tx.labels(*labels).set(device.get("tx", 0) or 0)
            device_rx.labels(*labels).set(device.get("rx", 0) or 0)
        
        log.info("Collected API metrics for %d devices", len(devices))

        # Per-device: tunnel status + event log
        for device in devices:
            d_id = str(device.get("id", ""))
            d_name = device.get("name", "unknown")

            stat = client.get_tunnel_stat(org_id, IC_GROUP_ID, d_id)
            if stat is not None:
                tunnel_up.labels(d_id, d_name).set(1 if stat else 0)
                log.debug("Tunnel %s (%s): %s", d_name, d_id, "ok" if stat else "error")

            count = client.get_event_count(org_id, IC_GROUP_ID, d_id)
            if count is not None:
                recent_event_count.labels(d_id, d_name).set(count)

    except Exception as e:
        log.error("API collection failed: %s", e)
        success = False
    
    # SNMP metrics (sneller, directe polling)
    try:
        collect_snmp_metrics()
    except Exception as e:
        log.error("SNMP collection failed: %s", e)
        # SNMP failure is niet kritisch, API data is er nog

    # Local API metrics (CPU load, AP status via web admin)
    try:
        collect_local_api_metrics()
    except Exception as e:
        log.error("Local API collection failed: %s", e)

    scrape_duration.set(time.time() - start_time)
    scrape_success.set(1 if success else 0)


def main():
    if not IC_CLIENT_ID or not IC_CLIENT_SECRET:
        log.error("IC_CLIENT_ID and IC_CLIENT_SECRET env vars required")
        exit(1)
    
    log.info("=" * 50)
    log.info("InControl2 + SNMP + Local API Exporter")
    log.info("=" * 50)
    log.info("Org: %s | Interval: %ds | Port: %d", IC_ORG_ID, POLL_INTERVAL, EXPORTER_PORT)

    if SNMP_ENABLED and SNMP_AVAILABLE:
        log.info("SNMP: ENABLED (community: %s)", SNMP_COMMUNITY)
        log.info("SNMP targets: %s", SNMP_TARGETS)
    elif SNMP_ENABLED and not SNMP_AVAILABLE:
        log.warning("SNMP: DISABLED (pysnmp not installed)")
    else:
        log.info("SNMP: DISABLED")

    if LOCAL_API_TARGETS:
        log.info("Local API: ENABLED (%d targets: %s)", len(LOCAL_API_TARGETS), list(LOCAL_API_TARGETS.keys()))
    else:
        log.info("Local API: DISABLED (no LOCAL_API_TARGETS configured)")

    log.info("=" * 50)
    
    start_http_server(EXPORTER_PORT)
    log.info("Metrics at http://0.0.0.0:%d/metrics", EXPORTER_PORT)
    
    client = InControl2Client(IC_CLIENT_ID, IC_CLIENT_SECRET)
    
    while True:
        try:
            collect_metrics(client, IC_ORG_ID)
        except Exception as e:
            log.error("Error: %s", e)
            scrape_success.set(0)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
