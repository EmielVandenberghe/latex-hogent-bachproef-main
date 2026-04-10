# SNMP Discovery — Fysieke Peplink Balance 20X

**Datum:** 2026-03-23
**Doel:** Valideren welke Peplink enterprise SNMP OIDs beschikbaar zijn op fysieke hardware (vs. FusionHub waar deze ontbraken)

---

## Configuratie

| Parameter | Waarde |
|-----------|--------|
| Model | Peplink Balance 20X |
| Firmware | 8.5.1 build 5531 |
| IP | `192.168.1.1` |
| SNMP versie | SNMPv2c |
| Community string | `public` |
| Allowed network | `192.168.1.0/24` |
| SNMP poort | 161 (UDP) |

**Belangrijk:** Het veld "Allowed Network" moet ingevuld zijn (bv. `192.168.1.0/24`), anders weigert de Peplink SNMP-queries (timeout).

---

## Standaard MIB-II OIDs (werken ook op FusionHub)

| OID | Naam | Waarde (Balance 20X) |
|-----|------|----------------------|
| `1.3.6.1.2.1.1.1.0` | sysDescr | `Peplink Balance 20X` |
| `1.3.6.1.2.1.1.3.0` | sysUpTime | `5083` (ticks) |
| `1.3.6.1.2.1.1.5.0` | sysName | `Balance_2622` |
| `1.3.6.1.2.1.1.4.0` | sysContact | `support@peplink.com` |
| `1.3.6.1.2.1.1.6.0` | sysLocation | `Peplink` |

---

## Peplink Enterprise OIDs — WAN Status (1.3.6.1.4.1.23695.2.1)

### WAN count

| OID | Beschrijving | Waarde |
|-----|-------------|--------|
| `.2.1.1.0` | Aantal WAN-interfaces | `6` |

### WAN interface tabel (.2.1.2.1.x.{wan_index})

De Balance 20X heeft 6 WAN-interfaces (index 0-5):

| Index | Naam | Type |
|-------|------|------|
| 0 | WAN | Ethernet |
| 1 | Cellular | SIM-kaart |
| 2 | Mobile Internet | USB tethering |
| 3 | Wi-Fi WAN on 2.4 GHz | WiFi als WAN |
| 4 | Wi-Fi WAN on 5 GHz | WiFi als WAN |
| 5 | VLAN WAN 1 | VLAN |

### WAN status OIDs per interface

| OID suffix | Beschrijving | Mogelijke waarden |
|------------|-------------|-------------------|
| `.2.1.2.1.2.{i}` | WAN naam | String (bv. "WAN", "Cellular") |
| `.2.1.2.1.3.{i}` | WAN status | 1=disabled, 2=disconnected, **3=connected**, 4=connecting, 5=activating, 6=health-check-fail |
| `.2.1.2.1.4.{i}` | Link up/down | **1=up**, 0=down |
| `.2.1.2.1.5.{i}` | Signaalsterkte (RSSI) | dBm waarde, `-9999` = niet van toepassing (Ethernet) |
| `.2.1.2.1.7.{i}` | Cellular type | 0=N/A, 4=LTE, etc. |
| `.2.1.2.1.8.{i}` | Health check status | positief getal = health check ID actief, `-1` = niet geconfigureerd |

**Testresultaten (2026-03-23):**

| Interface | Status | Link | Signaal |
|-----------|--------|------|---------|
| WAN (0) | 3 (connected) | 1 (up) | -9999 (N/A, Ethernet) |
| Cellular (1) | 2 (disconnected) | 0 (down) | -9999 (geen SIM) |
| Mobile Internet (2) | 2 (disconnected) | 0 (down) | -9999 |
| Wi-Fi WAN 2.4GHz (3) | 1 (disabled) | 0 (down) | 0 |
| Wi-Fi WAN 5GHz (4) | 1 (disabled) | 0 (down) | 0 |
| VLAN WAN 1 (5) | 1 (disabled) | 0 (down) | -9999 |

---

## Peplink Enterprise OIDs — Bandwidth/Traffic (1.3.6.1.4.1.23695.2.1.3 & .2.1.4)

### Bandwidth per interval (.2.1.4.1.x.{wan_index}.{interval})

| OID suffix | Beschrijving |
|------------|-------------|
| `.2.1.4.1.2.{wan}.{interval}` | TX bytes |
| `.2.1.4.1.3.{wan}.{interval}` | RX bytes |

Intervals gevonden: 0, 1, 3 (vermoedelijk 5min, 1uur, 24uur)

**Testresultaten WAN 0:**

| Interval | TX bytes | RX bytes |
|----------|----------|----------|
| 0 | 44 | 141 |
| 1 | 44 | 141 |
| 3 | 45 | 141 |

---

## Peplink Enterprise OIDs — LAN & WiFi AP (1.3.6.1.4.1.23695.4)

### WiFi AP tabel (.4.2.3.1.x.{ssid_index})

| OID suffix | Beschrijving | Waarde |
|------------|-------------|--------|
| `.4.2.3.1.2.{i}` | SSID naam | `PEPLINK_2622` |
| `.4.2.3.1.4.{i}` | Aantal clients | `0` |

### LAN VLAN tabel (.4.2.2.1.x.{vlan}.{sub})

| OID suffix | Beschrijving | Voorbeeld |
|------------|-------------|-----------|
| `.4.2.2.1.1.{v}.{s}` | VLAN naam | `Default` |
| `.4.2.2.1.3.{v}.{s}` | TX packets | `2403` |
| `.4.2.2.1.4.{v}.{s}` | TX bytes | `3279360` |
| `.4.2.2.1.5.{v}.{s}` | RX packets | `581` |
| `.4.2.2.1.6.{v}.{s}` | RX bytes | `181012` |

---

## Vergelijking: FusionHub vs. Fysieke Balance 20X

| SNMP Feature | FusionHub (virtueel) | Balance 20X (fysiek) |
|-------------|---------------------|---------------------|
| MIB-II (sysDescr, uptime, interfaces) | Ja | Ja |
| Enterprise WAN status tabel | **Nee** | **Ja — 6 interfaces met status, link, signaal** |
| Enterprise WAN bandwidth | **Nee** | **Ja — TX/RX bytes per interval** |
| Enterprise WiFi AP info (SSID, clients) | **Nee** | **Ja** |
| Enterprise LAN/VLAN traffic | **Nee** | **Ja — packets + bytes per VLAN** |
| Enterprise CPU/geheugen (.200.x) | **Nee** | **Nee — OIDs bestaan niet op dit model** |
| Enterprise device info (.1.x) | **Nee** | **Nee — OIDs bestaan niet op dit model** |
| Totaal enterprise OIDs | 0 | **200+** |

### Belangrijke bevinding: CPU/geheugen OIDs

De veelgenoemde OIDs voor CPU en geheugen (`1.3.6.1.4.1.23695.200.1.1.1.3.1` voor CPU, `.4.1` en `.5.1` voor geheugen) en device info (`1.3.6.1.4.1.23695.1.x`) zijn **ook op de fysieke Balance 20X niet beschikbaar**. Deze OIDs bestaan vermoedelijk alleen op enterprise-modellen (Balance 380X, 580X, etc.) of oudere firmware.

De Balance 20X gebruikt een **andere OID-structuur** onder `.23695.2.x` (WAN/traffic) en `.23695.4.x` (LAN/WiFi) in plaats van de gedocumenteerde `.23695.1.x` en `.23695.200.x` structuur.

---

## Conclusie

De fysieke Peplink Balance 20X biedt **significant meer SNMP-data** dan FusionHub:

1. **WAN monitoring:** status, link up/down, signaalsterkte per interface — ideaal voor multi-WAN failover detectie
2. **Bandbreedte:** TX/RX bytes per WAN en per VLAN — voor traffic monitoring
3. **WiFi AP:** SSID info en client count — voor site awareness
4. **Health checks:** status per WAN interface — voor proactieve alerting

Deze data kan rechtstreeks in de bestaande Prometheus/Grafana stack geïntegreerd worden via de `incontrol2_exporter` (SNMP-component) of een dedicated `snmp_exporter`.

---

## Lokale REST API — vergelijking FusionHub vs. Balance 20X

**Endpoint:** `POST https://<ip>/cgi-bin/MANGA/api.cgi`
**Auth:** Cookie-based login met `{"func": "login", "username": "admin", "password": "<wachtwoord>"}`

### config.* functies (configuratie uitlezen)

| Functie | FusionHub | Balance 20X |
|---------|-----------|-------------|
| `config.wan` | **OK** (1 WAN) | **OK** (6 WANs) |
| `config.lan` | **OK** | **OK** |
| `config.firewall` | **OK** | **OK** |
| `config.pepvpn` | **OK** | **OK** |
| `config.dns` | **OK** | **OK** |
| `config.admin` | **OK** | **OK** |
| `config.ntp` | **OK** | **OK** |
| `config.dhcp` | FAIL | **OK** |
| `config.snmp` | FAIL | n.v.t. |
| `config.system` | FAIL | n.v.t. |

### status/cmd/info functies (real-time & device info)

Na exhaustieve brute-force test van alle mogelijke functienamen (9 prefixes × 80+ subjects):

| Functie | FusionHub | Balance 20X | Data |
|---------|-----------|-------------|------|
| `status.cpu` | **OK** | **OK** | `{"cpu": {"load": "1.00%"}}` — **live CPU load** |
| `status.log` | **OK** | **OK** | Event log entries (zelfde als syslog) |
| `status.ap` | FAIL | **OK** | SSID, security, BSSID, frequentie, kanaal |
| `status.ap.neighbor` | n.v.t. | **OK** | Naburige WiFi-netwerken + timestamp |
| `status.ap.ssid` | n.v.t. | **OK** | SSID details met BSSID per band |
| `status.openvpn` | **OK** | **OK** | `{"support": true}` |
| `status.ospf` | **OK** | **OK** | OSPF area's en interfaces |
| `cmd.ap` | OK (not supported) | **OK** | AP enable/disable status |
| `cmd.gps` | OK (not supported) | **OK** | GPS enable status |
| `info.cellular` | **OK** (leeg) | **OK** (leeg) | Geen SIM aanwezig |
| `info.location` | n.v.t. | **OK** | GPS status |
| `status.wan.*` | **FAIL** | **FAIL** | Alle WAN status endpoints falen |
| `status.pepvpn` | **FAIL** | **FAIL** | VPN tunnel status niet beschikbaar |
| `status.client` | **FAIL** | **FAIL** | Client lijst niet via API |
| `status.system` | **FAIL** | **FAIL** | Systeem-info niet via API |
| `status.memory` | **FAIL** | **FAIL** | Geheugen niet via API |
| `status.throughput` | **FAIL** | **FAIL** | Doorvoer niet via API |

**Totaal werkende functies:** FusionHub 7, Balance 20X 9 (van ~720 geteste combinaties).

### Conclusie lokale API

De lokale API biedt **beperkte maar bruikbare real-time data**:
- **`status.cpu`** geeft live CPU-load — dit is een waardevolle metric die ook via SNMP enterprise OIDs niet beschikbaar was op de Balance 20X
- **`status.log`** geeft event logs — alternatief voor syslog
- **`status.ap`** geeft WiFi AP details — kanaal, frequentie, BSSID

De meerderheid van de `status.*` functies (WAN, VPN, clients, throughput, memory) zijn **niet beschikbaar** via de lokale API op beide platformen. Dit is een bewuste beperking van Peplink — live monitoring data is primair bedoeld via InControl2 cloud-API en SNMP.

### Monitoring-bronnen samenvatting

| Databron | Beschikbaar op | Unieke data |
|----------|---------------|-------------|
| **SNMP enterprise OIDs** | Fysieke hardware | WAN status, link, signaal, bandwidth, WiFi clients |
| **SNMP MIB-II** | Beide | sysDescr, uptime, interface bytes |
| **InControl2 API** | Beide (mits geclaimed) | Device online, uptime, client count, tx/rx, tunnel status, events |
| **Lokale API** | Beide | **CPU load**, event log, AP info |
| **ICMP probes** | Beide | Latency, packet loss, jitter |
| **Syslog** | Beide | Event logging naar Loki |

---

## Test commando (herhaalbaar)

```bash
# Vereist: pip install pysnmp-lextudio
python -c "
import warnings; warnings.filterwarnings('ignore')
from pysnmp.hlapi.asyncio import *
import asyncio

async def test():
    engine = SnmpEngine()
    async for (err, _, _, vbs) in walkCmd(
        engine, CommunityData('public'),
        UdpTransportTarget(('192.168.1.1', 161), timeout=5, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity('1.3.6.1.4.1.23695'))
    ):
        if err: print(f'ERROR: {err}'); break
        for vb in vbs: print(f'{vb[0]} = {vb[1]}')

asyncio.run(test())
"
```

---

*Documentatie aangemaakt — 23 maart 2026*
