#!/usr/bin/env python3
"""InControl2 + SNMP Prometheus Exporter - Mediaventures PoC"""

import os
import time
import logging
import requests
from prometheus_client import start_http_server, Gauge, Counter

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
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "15"))
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "8080"))

# SNMP Config
SNMP_COMMUNITY = os.getenv("SNMP_COMMUNITY", "public")
SNMP_TIMEOUT = int(os.getenv("SNMP_TIMEOUT", "2"))
SNMP_ENABLED = os.getenv("SNMP_ENABLED", "true").lower() == "true"

# Device IPs voor directe SNMP polling (configureerbaar via env)
# Format: "device_name:ip,device_name:ip"
SNMP_TARGETS_RAW = os.getenv("SNMP_TARGETS", "Bornem:10.1.1.1,Venue:10.1.2.1,Live-Surgery1:10.1.3.1,Live-Surgery2:10.1.4.1")
SNMP_TARGETS = {}
if SNMP_TARGETS_RAW:
    for target in SNMP_TARGETS_RAW.split(","):
        if ":" in target:
            name, ip = target.split(":", 1)
            SNMP_TARGETS[name.strip()] = ip.strip()

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

# Exporter metrics
scrape_success = Gauge('peplink_scrape_success', 'Last scrape successful (1) or failed (0)')
scrape_duration = Gauge('peplink_scrape_duration_seconds', 'Scrape duration')
api_errors = Counter('peplink_api_errors_total', 'API errors', ['endpoint'])
snmp_errors = Counter('peplink_snmp_errors_total', 'SNMP errors', ['device_name'])


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
    # Peplink specific (enterprise OIDs)
    'peplinkCpuLoad': '1.3.6.1.4.1.23695.200.1.1.1.2.1',
    'peplinkMemoryUsage': '1.3.6.1.4.1.23695.200.1.1.1.3.1',
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
            else:
                log.warning("SNMP UNREACHABLE: %s (%s)", device_name, ip)
                snmp_errors.labels(device_name).inc()
                
        except Exception as e:
            log.error("SNMP error for %s: %s", device_name, e)
            snmp_errors.labels(device_name).inc()


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
        
    except Exception as e:
        log.error("API collection failed: %s", e)
        success = False
    
    # SNMP metrics (sneller, directe polling)
    try:
        collect_snmp_metrics()
    except Exception as e:
        log.error("SNMP collection failed: %s", e)
        # SNMP failure is niet kritisch, API data is er nog
    
    scrape_duration.set(time.time() - start_time)
    scrape_success.set(1 if success else 0)


def main():
    if not IC_CLIENT_ID or not IC_CLIENT_SECRET:
        log.error("IC_CLIENT_ID and IC_CLIENT_SECRET env vars required")
        exit(1)
    
    log.info("=" * 50)
    log.info("InControl2 + SNMP Exporter")
    log.info("=" * 50)
    log.info("Org: %s | Interval: %ds | Port: %d", IC_ORG_ID, POLL_INTERVAL, EXPORTER_PORT)
    
    if SNMP_ENABLED and SNMP_AVAILABLE:
        log.info("SNMP: ENABLED (community: %s)", SNMP_COMMUNITY)
        log.info("SNMP targets: %s", SNMP_TARGETS)
    elif SNMP_ENABLED and not SNMP_AVAILABLE:
        log.warning("SNMP: DISABLED (pysnmp not installed)")
    else:
        log.info("SNMP: DISABLED")
    
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
