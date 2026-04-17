# Grafana Dashboard — Handleiding & Secties

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Toegang

**URL:** http://192.168.137.10:3000
**Login:** admin / admin

---

## Dashboardstructuur

Het dashboard "Mediaventures — Observability Dashboard" heeft **11 secties** die van boven naar beneden de volledige infrastructuurstatus tonen.

---

### Sectie 1 — Site Status Overzicht

**Doel:** In één oogopslag de status van alle 5 locaties zien.

Per site (Bornem, Venue, Live1, Live2, **Balance 20X**) worden 3 waarden getoond:

| Waarde | Metric | Betekenis |
|--------|--------|-----------|
| Bereikbaarheid | `probe_success` | ICMP ping succesvol |
| PepVPN Tunnel / SNMP | `peplink_tunnel_up` of `peplink_snmp_reachable` | VPN-verbinding of SNMP bereikbaarheid |
| InControl2 / API | `peplink_device_online` of `peplink_local_api_reachable` | Cloud status of lokale API bereikbaar |

**Interpretatie:** Alle groen = locatie volledig operationeel. Rood = actie vereist.

---

### Sectie 2 — Connectiviteit & Netwerkkwaliteit (ICMP)

**Doel:** Kwantitatieve netwerkkwaliteitsmetingen voor live streaming.

**Panels:**
- **Huidige RTT (5x stat)** — actuele round-trip time per site in milliseconden
- **RTT Latency over tijd** — tijdreeks van RTT voor alle sites
- **Packet Loss %** — percentage mislukte pings over 5 minuten
- **Jitter per site** — mdev van 10 ICMP pings (nauwkeuriger dan stddev_over_time)
- **Jitter stats (5x stat)** — huidige jitter per site

**Drempelwaarden:**

| Metric | Groen | Geel | Rood |
|--------|-------|------|------|
| RTT | < 50ms | 50–150ms | > 150ms |
| Packet Loss | 0% | < 1% | > 5% |
| Jitter | < 5ms | 5–20ms | > 20ms |

---

### Sectie 3 — WAN Multi-Link Status (Enterprise SNMP)

**Doel:** Gedetailleerde WAN-status van fysieke Peplink hardware via enterprise SNMP OIDs.

> **Let op:** Deze sectie toont alleen data voor fysieke Peplink devices (bv. Balance 20X). FusionHub ondersteunt geen enterprise SNMP OIDs.

**Panels:**
- **WAN Interface Status (tabel)** — overzicht van alle WAN interfaces met status, link, signaal, health check
- **WAN Connected (stat)** — aantal actief verbonden WAN interfaces
- **WiFi Clients (stat)** — verbonden WiFi clients via SNMP
- **WAN Link Status geschiedenis** — tijdlijn van link up/down per WAN interface

**WAN status waarden:**

| Waarde | Betekenis |
|--------|-----------|
| 1 | Disabled |
| 2 | Disconnected |
| 3 | Connected |
| 4 | Connecting |
| 5 | Activating |
| 6 | Health-check-fail |

**Enterprise SNMP OID-structuur (Balance 20X):**
- WAN: `1.3.6.1.4.1.23695.2.1.2.1.x.{wan_index}` — status, link, signaal, health check
- WiFi: `1.3.6.1.4.1.23695.4.2.3.1.x.{ssid_index}` — SSID naam, client count
- LAN: `1.3.6.1.4.1.23695.4.2.2.1.x.{vlan}.{sub}` — VLAN traffic stats

Zie `poc/snmp_fysieke_peplink.md` voor de volledige OID-mapping.

---

### Sectie 4 — Device Health — Lokale API & CPU

**Doel:** Live CPU-gebruik en WiFi AP status via de lokale Peplink REST API.

**Panels:**
- **CPU Load gauge** — huidig CPU-gebruik van de Balance 20X (via `status.cpu`)
- **CPU Load over tijd** — tijdreeks van CPU-gebruik voor alle devices met lokale API
- **WiFi AP Status** — AP aan/uit per device (via `status.ap`)
- **Lokale API Bereikbaarheid** — welke devices bereikbaar zijn via de lokale REST API

**API-endpoint:** `POST https://<ip>/cgi-bin/MANGA/api.cgi`
**Auth:** Cookie-based login met `{"func": "login", "username": "admin", "password": "<wachtwoord>"}`

**CPU drempelwaarden:** Groen < 60%, Geel 60–85%, Rood > 85%

---

### Sectie 5 — PepVPN Tunnels

**Doel:** Status van de SpeedFusion VPN-tunnels bewaken.

**Panels:**
- **Tunnel status (4x stat)** — UP/DOWN per device
- **Tunnel status geschiedenis** — tijdlijn met drops naar 0 bij onderbrekingen

> Tunnels zijn geconfigureerd in een gedeeltelijke mesh: Bornem ↔ Venue, Live1 ↔ Bornem, Live1 ↔ Venue, Live2 ↔ Bornem, Live2 ↔ Venue.

---

### Sectie 6 — Device Health (InControl2 API)

**Doel:** Cloud-gebaseerde apparaatstatus via InControl2 API.

**Panels:**
- **Online/Offline (4x stat)** — device status via API (polling elke 15s)
- **Uptime** — tijdreeks van uptime in uren
- **Verbonden clients** — aantal clients per device
- **Bandbreedte (TX/RX)** — cumulatieve bytes verzonden/ontvangen

> **Let op:** InControl2 uptime en tx/rx bytes zijn cumulatieve waarden die gereset worden bij reboot.

---

### Sectie 7 — SNMP Direct Monitoring

**Doel:** Directe SNMP-polling van alle devices (MIB-II), sneller dan de InControl2 cloud API.

**Panels:**
- **SNMP Reachability (5x stat)** — is het device bereikbaar via SNMP?
- **SNMP Response Tijd** — hoe snel reageert het device op SNMP queries
- **Interface Verkeer** — bytes in/out per interface via SNMP MIB-II

---

### Sectie 8 — Systeemlogboek (Loki)

**Doel:** Real-time logberichten van apparaten en de observability stack zelf.

**Panels:**
- **FusionHub & Peplink Syslog** — logberichten van alle devices (na syslog configuratie)
- **Docker Container Logs** — logs van Prometheus, Grafana, exporters

> Vereist syslog configuratie op elke FusionHub/Peplink (zie `loki_logging.md`).

---

### Sectie 9 — Events (InControl2)

**Doel:** Teller van recente events per device via InControl2 API.

**Panel:**
- **Events per device** — bar chart die pieken toont wanneer een device veel events genereert

---

### Sectie 10 — Observability Stack Status

**Doel:** Gezondheid van de monitoring stack zelf bewaken.

**Panels:**
- **Scrape Duur** — hoe lang de exporter nodig heeft per scrape-cyclus
- **Exporter Status** — OK/FOUT indicator
- **API/SNMP Fouten** — teller van fouten bij API-calls of SNMP-polls
- **Local API Fouten** — teller van fouten bij lokale API-polls

---

## Alert Rules (10 regels)

| Alert | Severity | For | Trigger |
|-------|----------|-----|---------|
| Device Offline | CRITICAL | 1min | `peplink_device_online == 0` |
| PepVPN Tunnel Down | CRITICAL | 1min | `peplink_tunnel_up == 0` |
| PepVPN No Profiles Configured | WARNING | 5min | `max(peplink_tunnel_count) < 1` |
| Site onbereikbaar ICMP | WARNING | 2min | `probe_success == 0` |
| Hoge latency > 150ms | WARNING | 5min | `probe_icmp_duration_seconds * 1000 > 150` |
| Hoog packet loss > 5% | WARNING | 5min | Packet loss > 5% over 5 min |
| WAN Link Down | WARNING | 2min | `peplink_snmp_wan_link_up{wan_name="WAN"} == 0` |
| Hoge CPU Load > 85% | WARNING | 5min | `peplink_local_cpu_load_percent > 85` |
| Exporter Down | CRITICAL | 2min | `peplink_scrape_success == 0` |
| SRT Stream Packet Loss > 5% | WARNING | 1min | `srt_packet_loss_percent > 5` |

---

## Dashboard bijwerken

Na aanpassen van `peplink.json` lokaal:
```bash
KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"
scp -i "$KEY" -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  poc/stack/provisioning/dashboards/peplink.json \
  vagrant@127.0.0.1:/opt/observability/provisioning/dashboards/
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "docker restart grafana"
```

> **Let op:** Het dashboard is provisioned via JSON en wordt bij elke Grafana-restart opnieuw geladen. Wijzigingen rechtstreeks in de Grafana UI worden niet opgeslagen. Pas altijd het JSON-bestand aan.

---

## Nuttige Grafana shortcuts

| Actie | Shortcut |
|-------|---------|
| Refresh dashboard | `Shift + R` |
| Tijdvenster uitbreiden | Gebruik de tijdpicker rechtsboven |
| Panel fullscreen | Klik op panelnaam → View |
| Explore (ad-hoc queries) | Linkermenu → Explore |
| Alert rules bekijken | Linkermenu → Alerting → Alert rules |
