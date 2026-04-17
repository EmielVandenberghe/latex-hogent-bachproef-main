# Testscenario's — Validatie van het POC

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Overzicht

Het voorstel beschrijft drie validatiescenario's voor fase 6, aangevuld met twee extra scenario's voor de streaming- en fysieke hardwarelaag:

| Scenario | Beschrijving |
|----------|-------------|
| **1 — Baseline** | Normale werking zonder storingen |
| **2 — Netwerkstoringen** | Gesimuleerde packet loss en latency |
| **3 — Overbelasting** | Meerdere gelijktijdige datastromen |
| **4 — SRT Streamkwaliteit** | Packet loss en latency impact op SRT |
| **5 — Fysieke hardware (Balance 20X)** | Connectiviteitsverlies Live3 via WiFi-disconnect |

Elk scenario wordt uitgevoerd op de VyOS router via `tc netem` (Linux Traffic Control). De effecten zijn zichtbaar in het Grafana dashboard.

---

## Toegang tot VyOS voor simulaties

```bash
ssh vyos@192.168.137.10
```

Wachtwoord: `vyos` (of het wachtwoord dat tijdens setup is ingesteld)

---

## Scenario 1 — Baseline (normale werking)

**Doel:** Controleer dat alle metrics correct worden weergegeven zonder storingen.

**Checklist:**
- [ ] Alle 4 sites REACHABLE (ICMP probe_success = 1)
- [ ] Alle 4 devices ONLINE (InControl2)
- [ ] Alle tunnels UP (PepVPN)
- [ ] RTT < 10ms (lokale VM-naar-VM verbinding)
- [ ] Packet loss = 0%
- [ ] Jitter < 1ms
- [ ] Geen firing alerts in Grafana

**Screenshot maken:** Grafana dashboard → "Site Status Overzicht" sectie

---

## Scenario 2 — Netwerkstoringen simuleren

### 2a — Packet loss toevoegen op Live1

Op VyOS:
```bash
# SSH inloggen
ssh vyos@192.168.137.10

# Packet loss van 10% toevoegen op het interface naar Live1 (eth3)
sudo tc qdisc add dev eth3 root netem loss 10%

# Verify
sudo tc qdisc show dev eth3
```

**Verwacht resultaat in Grafana (na 1-2 minuten):**
- Packet Loss % voor Live1 stijgt naar ~10%
- Alert "Hoog packet loss" gaat naar Pending → Firing (na 5 min)
- RTT fluctueert (jitter stijgt)

**Herstellen:**
```bash
sudo tc qdisc del dev eth3 root
```

---

### 2b — Hoge latency toevoegen op Venue

```bash
# 200ms vertraging toevoegen op eth2 (Venue interface)
sudo tc qdisc add dev eth2 root netem delay 200ms

# Of met variatie (jitter simulatie):
sudo tc qdisc add dev eth2 root netem delay 200ms 50ms distribution normal
```

**Verwacht resultaat:**
- RTT voor Venue stijgt naar ~400ms (heen + terug = 2x de vertraging)
- Alert "Hoge VPN-latency" → Firing (na 5 min)
- Jitter grafiek toont variatie

**Herstellen:**
```bash
sudo tc qdisc del dev eth2 root
```

---

### 2c — Volledige verbindingsonderbreking

```bash
# Interface volledig uitschakelen (simuleert link failure)
sudo ip link set eth3 down   # Live1 offline

# Herstellen:
sudo ip link set eth3 up
```

**Verwacht resultaat:**
- probe_success = 0 voor Live1
- Alert "Site onbereikbaar" → Firing (na 2 min)
- peplink_device_online daalt na verloop van tijd (InControl2 timeout is langer)

---

## Scenario 3 — Overbelasting

### 3a — Bandbreedte beperken

```bash
# Maximale bandbreedte beperken tot 1 Mbit/s op Live1 (simuleert slechte 4G verbinding)
sudo tc qdisc add dev eth3 root tbf rate 1mbit burst 32kbit latency 400ms
```

**Herstellen:**
```bash
sudo tc qdisc del dev eth3 root
```

---

### 3b — Meerdere storingen tegelijk

Combineer scenario 2a, 2b en 2c tegelijk op verschillende interfaces:
```bash
sudo tc qdisc add dev eth2 root netem delay 150ms loss 2%   # Venue
sudo tc qdisc add dev eth3 root netem delay 100ms loss 5%   # Live1
sudo tc qdisc add dev eth4 root netem delay 80ms loss 3%    # Live2
```

**Verwacht resultaat:**
- Alle surgery-sites en venue tonen degradatie
- Meerdere alerts firen tegelijk
- Dashboard geeft duidelijk overzicht van welke sites het meest getroffen zijn

**Alles tegelijk herstellen:**
```bash
for iface in eth2 eth3 eth4; do sudo tc qdisc del dev $iface root 2>/dev/null; done
```

---

---

## Scenario 4 — SRT Streamkwaliteit

SRT-scenario's worden gesimuleerd op de **observability VM** (niet op VyOS), omdat de SRT-containers (`srt-test-stream` en `srt-exporter`) beide draaien met `network_mode: host` op die VM. Traffic tussen beide containers verloopt via de **loopback interface** (`lo`), niet via de Docker bridge.

> **Belangrijk:** `tc netem` op de Docker bridge (`br-xxxx`) heeft **geen effect** op host-networked containers. De filter op `lo` voor UDP poort 9000 is vereist.

**tc netem commando's op obs VM:**

```bash
# Gefilterde netem toevoegen op loopback (enkel UDP:9000)
sudo tc qdisc add dev lo root handle 1: prio priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
sudo tc qdisc add dev lo parent 1:3 handle 30: netem loss 30%   # voor scenario 4a
# OF
sudo tc qdisc add dev lo parent 1:3 handle 30: netem delay 100ms 20ms distribution normal  # voor scenario 4b
sudo tc filter add dev lo parent 1:0 protocol ip u32 match ip protocol 17 0xff match ip dport 9000 0xffff flowid 1:3

# Verwijderen
sudo tc qdisc del dev lo root

# Stats resetten (na verwijderen rule)
cd /opt/observability && docker compose restart srt-test-stream
```

---

### 4a — SRT Packet Loss (30% netem)

**Uitgevoerd op:** 14 april 2026

**Commando:**
```bash
sudo tc qdisc add dev lo parent 1:3 handle 30: netem loss 30%
```

**Gemeten resultaat (na ~90 seconden):**
- `srt_packet_loss_percent`: steeg van 0% → 4.1% → 6.6% → >10% over tijd
- `srt_retransmit_total`: >8000 pakketten herverstuurd
- `srt_stream_active`: bleef 1 (stream bleef in de lucht)

**Waarom 30% netem → slechts 4-10% gemeten loss?**

SRT heeft ingebouwde **ARQ (Automatic Repeat Request)**. Wanneer een pakket verloren gaat, detecteert SRT dit via sequentienummers en vraagt automatisch herversturing aan. De meeste verloren pakketten worden zo hersteld voor de deadline. Wat overblijft (4-10%) zijn pakketten die SRT niet meer op tijd kon herstellen binnen de latency buffer (~120ms).

**Waarom stijgt de loss over tijd (cascade-effect)?**

Bij aanhoudende 30% loss:
1. SRT stuurt een pakket opnieuw → die retransmit krijgt zelf ook 30% kans om gedropped te worden
2. Retransmits van retransmits stapelen zich op
3. Het retransmit-verkeer zelf neemt bandbreedte in → verhoogt de kans op verdere drops
4. SRT's latency buffer (120ms) is eindig: pakketten die na 120ms nog niet aangekomen zijn, tellen definitief als verloren

**Kernbevinding:** `srt_retransmit_rate` en `srt_retransmit_total` zijn de échte stress-indicatoren. Ze tonen de verborgen netwerkdruk ook wanneer `srt_packet_loss_percent` nog laag lijkt. De 5%-alert firt bij aanhoudende degradatie.

**Screenshots:**
- `scenario_4a_srt_packetloss_7pct.png` — eerste piek zichtbaar (7.72%)
- `scenario_4a_srt_packetloss_peak.png` — peak bij 11.2%, retransmit rate stijgend

---

### 4b — SRT Latency / RTT (100ms delay)

**Uitgevoerd op:** 14 april 2026

**Commando:**
```bash
sudo tc qdisc add dev lo parent 1:3 handle 30: netem delay 100ms 20ms distribution normal
```

**Gemeten resultaat (na ~90 seconden):**
- `srt_rtt_ms`: steeg naar ~91-94ms (was 0.2-0.5ms)
- `srt_packet_loss_percent`: steeg naar ~35-37% (onverwacht hoog)
- `srt_bitrate_kbps`: steeg naar ~2700-2900 kbps (was ~1695) — SRT stuurt agressief retransmits

**Waarom zorgt enkel delay voor zoveel packet loss?**

SRT's **latency buffer** is standaard ~120ms. Wanneer een pakket te laat aankomt (na de deadline), beschouwt SRT het als verloren — ook al is het niet technisch gedropped. Met 100ms delay (±20ms) kunnen pakketten de 120ms deadline overschrijden. Resultaat: pakketten die gewoon vertraagd zijn, worden als verloren geteld en herverstuurd.

**Kernbevinding:** Bij SRT kan hoge netwerklatency **hetzelfde effect hebben als packet loss** als de delay de geconfigureerde latency buffer benadert. Dit toont het belang van RTT-monitoring naast packet loss.

**Screenshots:**
- `scenario_4b_srt_latency_overview.png` — brede tijdlijn, overgang scenario A→B zichtbaar, RTT 94.6ms
- `scenario_4b_srt_latency_detail.png` — narrow 5-minute view, RTT 84.8ms + loss 37.4%
- `scenario_4b_srt_recovery.png` — herstel na verwijderen rule, loss terug naar 0%

---

---

## Scenario 5 — Fysieke hardware: Balance 20X connectiviteitsverlies

**Doel:** Valideren dat de observability-stack een uitval van de **fysieke Balance 20X (Live3)** detecteert via drie onafhankelijke kanalen: ICMP, SNMP enterprise en lokale API. Bewijst dat de multi-source monitoring ook werkt op echte Peplink-hardware (niet enkel VMs).

**Uitgevoerd op:** 16 april 2026

**Architectuurcontext:** Live3 is bereikbaar via WiFi-direct (192.168.1.1), niet via PepVPN. Bij WiFi-disconnect valt de volledige route weg → alle drie monitoringkanalen (ICMP/SNMP/API) worden tegelijk onbereikbaar.

**Voor-situatie (baseline):**
- Sectie 1: Live3 → ICMP UP / SNMP UP / API UP (alles groen)
- Sectie 2: RTT Live3 ~3ms, packet loss 0%, jitter ~0.55ms
- Sectie 3: WAN Interface Status → WAN Connected, Health Check tno
- Sectie 4: CPU Load Balance 20X ~3%, API Bereikbaar OK

**Screenshots voor (al genomen):**
- `5-baseline-sitestatus.png` — Sectie 1 alle 5 sites groen
- `5-baseline-3-4-wanendevicehealth.png` — Secties 3+4 Live3 gezond

---

### 5a — WiFi AP uitschakelen (uitvoer)

**Uitgevoerd op:** 16 april 2026

**Methode:** WiFi AP op de Balance 20X volledig uitgeschakeld via webadmin → obs VM verliest route naar 192.168.1.1 → alle drie monitoringkanalen (ICMP/SNMP/API) vallen tegelijk weg.

> **Observatie:** Wisselen van WiFi-netwerk (zonder volledig uit te zetten) volstond niet — packet loss ging pas naar 100% bij volledig uitschakelen van de WiFi AP. Dit is logisch: de ICMP/SNMP/API probes zijn van de obs VM naar 192.168.1.1, en de route blijft bestaan zolang de obs VM verbonden is met een WiFi-netwerk dat routeert naar de Balance 20X.

**Gemeten resultaat:**
| Metric | Voor | Na AP-disconnect |
|--------|------|-----------------|
| probe_success (Live3) | 1 | 0 |
| ping_packet_loss (Live3) | 0% | 100% |
| ping_jitter_ms (Live3) | 0.55ms | 0 ms (geen data) |
| peplink_snmp_reachable (Live3) | 1 | 0 |
| peplink_api_reachable (Live3) | 1 | 0 |

**Cascade-effect — exporter DNS:** Doordat de WiFi-verbinding ook de internettoegang van de obs VM verzorgde, verloor de incontrol2-exporter tijdelijk zijn DNS-resolutie naar de InControl2 API. Dit triggerde de "PepVPN Tunnel Down" alert als cascade: de exporter kon de tunnel_up metrics niet meer ophalen. Dit is een **realistisch productie-inzicht**: als de monitoringhost zijn connectiviteit verliest, kunnen alerts misfiren over andere sites. Opgelost na herstel WiFi.

**Screenshots tijdens storing:**
- `scenario_5a_live3_offline_status.png` — Sectie 1: Live3 ICMP/SNMP/API DOWN (rood), sites 1-4 groen
- `scenario_5a_live3_offline_connectiviteit.png` — Sectie 2: RTT Live3 = 0ms, packet loss 100%, jitter 0ms
- `scenario_5a_live3_offline_alerts-pending.png` — "Site onbereikbaar ICMP" + "Hoog packet loss" → Pending
- `scenario_5a_live3_offline_alerts.png` — "Hoog packet loss" + "PepVPN Tunnel Down" → Firing

---

### 5b — Herstel

WiFi AP terug ingeschakeld → obs VM herverbindt → route naar 192.168.1.1 hersteld.

**Gemeten herstel:** ~1-2 minuten → alle drie panels Live3 terug UP, alerts resolved.

**Screenshot herstel:**
- `scenario_5b_live3_herstel.png` — Sectie 1 volledig groen (alle 5 sites)

---

### Bevindingen Scenario 5

**Gedetecteerde storingen:** ICMP / SNMP enterprise / lokale API — alle drie onafhankelijk bevestigen uitval in Sectie 1.

**Meerwaarde t.o.v. FusionHub-scenario's:** De Balance 20X levert metrics die FusionHub niet biedt:
- Enterprise SNMP WAN-status (sectie 3): WAN-interface details (link type, signaal dBm, health check)
- Lokale REST API: CPU-load per device (sectie 4)
- WiFi AP-status (SNMP) beschikbaar enkel op fysieke hardware

**Detectietijd:** ~2 minuten (conform "Site onbereikbaar ICMP" pending=2min + "Hoog packet loss" pending=5min).

**Cascade-inzicht (productiewaarde):** Verlies van monitoringconnectiviteit kan secundaire alerts triggeren (PepVPN Tunnel Down door IC2 DNS-fout). In productie: monitoringhost op aparte redundante verbinding plaatsen.

**Screenshots:**
- `5-baseline-sitestatus.png` — voor (baseline)
- `scenario_5a_live3_offline_status.png` — tijdens (Live3 rood)
- `scenario_5a_live3_offline_connectiviteit.png` — packet loss 100% Live3
- `scenario_5a_live3_offline_alerts-pending.png` — alerts pending
- `scenario_5a_live3_offline_alerts.png` — alerts firing (incl. cascade PepVPN)
- `scenario_5b_live3_herstel.png` — na herstel volledig groen

---

## Vergelijking met huidige werkwijze

| Aspect | Zonder monitoring (huidig) | Met observability POC |
|--------|--------------------------|----------------------|
| Detectietijd | Techniekers loggen manueel in op elk apparaat | Visueel zichtbaar op dashboard binnen 15s |
| Packet loss zichtbaarheid | Niet zichtbaar zonder actief testen | Continu gemeten, grafiek over tijd |
| Alert bij probleem | Geen — techniekers merken het aan klachten | Automatische alert binnen 2-5 minuten |
| Historiek | Geen — apparaten slaan beperkte logs op | 30 dagen in Prometheus/Loki |
| Multi-site overzicht | Vereist 4 logins + handmatige vergelijking | 1 dashboard met alle sites |

---

## Resultaten documenteren

Maak screenshots van het Grafana dashboard bij elk scenario:
1. **Voor** de simulatie (baseline)
2. **Tijdens** de simulatie (storingen zichtbaar)
3. **Na herstel** (normalisatie zichtbaar in grafieken)

Bewaar screenshots in `poc/screenshots/scenario_X_*.png`.
