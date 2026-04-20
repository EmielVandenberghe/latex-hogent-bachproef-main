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
| **6 — NDI Stream Onderbreking** | Sender gestopt → stream_active=0, alert firet, recovery |

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

## Scenario 6 — NDI Stream Onderbreking

**Uitgevoerd op:** 20 april 2026

**Doel:** Valideer dat de observability-stack een plotse onderbreking van een NDI-bron binnen seconden detecteert, en dat de kritieke alert (`ndi_stream_active == 0`) effectief firet. Analoog aan scenario 4 voor SRT, maar op de NDI-laag (frame-level, mDNS discovery).

**Context:** NDI-monitoring draait volledig via de `ndi-exporter` (ctypes-binding op NDI SDK v6) met als bron de synthetische `ndi-test-stream` (Python-sender, SMPTE-kleurbalken 1280×720 @ 25 fps). Discovery verloopt via Avahi/mDNS (`_ndi._tcp.local.`).

### 6a — Stream offline (sender gestopt)

**Commando op de observability VM:**
```bash
cd /opt/observability
docker compose --profile demo stop ndi-test-stream
```

**Verwacht resultaat (binnen ~15 s):**
- `ndi_stream_active` → 0 (stat-panel "Stream Active" wordt **OFFLINE** rood)
- `ndi_sources_detected` → 0 (mDNS-advertisement verdwijnt binnen enkele seconden)
- `ndi_video_fps`, `ndi_queue_depth_frames`, `ndi_frame_drop_rate` → 0 (gauges expliciet gereset door exporter-fix 20 april, anders behoudt Prometheus de laatste waarde tot de scrape stale wordt)
- `rate(ndi_frames_received_total[1m])` → 0 (zichtbaar als flatline in timeseries "Frames ontvangen vs. gedropt")
- Alert **[CRITICAL] NDI Stream Inactief** gaat naar Pending → Firing (1 min `for`-duur)

**Screenshot:** `scenario_6a_ndi_outage.png` — sectie 12 volledig rood, alle timeseries op 0.

### 6b — Stream recovery

**Commando:**
```bash
docker compose --profile demo start ndi-test-stream
```

**Verwacht resultaat (binnen ~15–30 s):**
- Stream Active → **LIVE** (groen)
- Frame Rate → 25 fps
- Bronnen gedetecteerd → 2 (Finder ziet de NDI-advertisement + de sender-zelfreferentie)
- Frame Drop Rate stabiliseert op de ~10–15% baseline van de synthetische Python-sender
- Alert zakt terug naar Normal
- Timeseries tonen een duidelijke **stapfunctie** van 0 → normale werking — visueel bewijs van recovery

**Screenshot:** `scenario_6b_ndi_recovery.png` — duidelijke spike van 0 naar 25 fps in "Framerate over tijd".

### Bevindingen

1. **Detectietijd stream_active:** ~15 s (één Prometheus scrape-interval). `ndi_sources_detected` volgt enkele seconden later wanneer het mDNS-record effectief verdwijnt.
2. **Gauge staleness bug (gevonden tijdens uitvoering):** initieel bleef `ndi_video_fps` op 25 staan na stop, omdat de exporter die gauge niet resette in de "geen bron"-branch. Fix in `ndi_exporter.py`: `video_fps`, `queue_depth`, `video_width/height` en `frame_drop_rate` expliciet op 0 zetten wanneer target verdwijnt. Dit is een algemeen Prometheus-gauge-patroon en wordt in de .tex als technische bevinding meegenomen.
3. **Alert voor NDI toegevoegd:** `(1 - ndi_stream_active) > 0`, label `{source}` (niet `stream_name` zoals bij SRT), severity **critical**, `for: 1m`. Sluit de 11e regel van de provisioned alerts-set.

---

## Scenario 7 — Asymmetrische NAT (NAT-traversal validatie)

Uitgevoerd: 2026-04-20. Volledig plan: [nat_traversal_plan.md](nat_traversal_plan.md).

### Doel

De methodologie (§Fase 5) benoemt drie connectiviteitsscenarios als productcontext voor PepVPN (publiek IP, één NAT, dubbele NAT). De PoC-basisomgeving test geen van die drie empirisch: alle spokes delen dezelfde VyOS-router en communiceren direct. Dit scenario voegt één expliciet asymmetrisch NAT-geval toe om de kernclaim van de observability-laag te valideren:

> Zolang `peplink_tunnel_up=1` blijft de stack routing-agnostisch — alle exporters werken op tunneladressen (10.1.x.x), ongeacht hoeveel NAT-lagen onder de tunnel zitten.

Wat dit scenario **niet** bewijst: PepVPN's eigen NAT-T onder CGNAT, hole-punching, of keepalive-tuning. Dat is commerciële productfunctionaliteit van Peplink en valt buiten de observability-scope.

### Opstelling

Eén extra `source NAT`-regel op VyOS masquereert verkeer van FH-Live1 (10.1.3.0/24) richting Bornem-subnet (10.1.1.0/24). Vanuit FH-Bornem lijkt Live1 plots afkomstig van 10.1.1.1 (VyOS-eth1) in plaats van 10.1.3.2 — asymmetrische NAT vanuit Bornem's perspectief. De P2P-tunnel Live1↔Venue blijft ongewijzigd.

### Uitvoering

Via obs VM → sshpass → VyOS:

```
configure
set nat source rule 310 description "Scenario 7 asymmetric NAT FH-Live1"
set nat source rule 310 source address 10.1.3.0/24
set nat source rule 310 destination address 10.1.1.0/24
set nat source rule 310 outbound-interface name eth1
set nat source rule 310 translation address masquerade
commit
save
```

Verificatie in kernel:

```
sudo nft list chain ip vyos_nat POSTROUTING | grep 310
# oifname "eth1" ip saddr 10.1.3.0/24 ip daddr 10.1.1.0/24 counter packets N masquerade comment "SRC-NAT-310"
```

**Belangrijke nuance:** omdat de bestaande Bornem↔Live1 tunnel al door Bornem was geïnitieerd, zat er een conntrack-entry in de originele richting (Bornem→Live1). De SNAT-regel werd daardoor initieel niet geraakt door het tunnelverkeer. Pas na het flushen van die entry (`sudo conntrack -D -p udp --sport 4500 --dport 4500 ...`) initieerde Live1 een verse outbound flow die wél onder rule 310 valt. In productie doet de initiatie-kant zich vanzelf voor omdat de spoke-router (Live1) outbound initieert naar een hub met publiek IP. Dit is een artefact van de lab-setup, niet van het scenario zelf.

### Bevindingen

Gemeten in Prometheus na commit van rule 310 en conntrack-flush:

| Metric | Voor | Tijdens | Na 60 s |
|--------|------|---------|---------|
| `peplink_tunnel_up{device_name="Live1"}` | 1 | 1 | 1 |
| `peplink_tunnel_up{device_name="Bornem"}` | 1 | 1 | 1 |
| `probe_success{site="Live1"}` | 1 | 1 | 1 |
| `peplink_device_online{device_name="Live1"}` | 1 | 1 | 1 |
| Firing alerts | 0 | 0 | 0 |
| Rule 310 counter | 0 pkt | 2 pkt | >3 pkt (groeit) |

De tunnel vertoonde **geen zichtbare flap** op scrape-resolutie (15 s) — consistent met PepVPN's ontwerp dat NAT-rebinding transparant opvangt via serial-based peer-identificatie in plaats van IP-based. Indien een flap wél optreedt, is hij korter dan de alert-drempel van 1 minuut.

**Aanvullende bevinding (bevestigd via FH-Bornem webadmin Status → SpeedFusion VPN):** FH-Bornem toont als peer-IP nog steeds **10.1.3.2** voor conn_to_Live1, niet 10.1.1.1. Dit is correct gedrag: PepVPN registreert de *inner* tunnel-endpoint die tijdens de IC2-handshake is onderhandeld (10.1.3.2/32), niet het *transport*-laag bron-IP dat door VyOS SNAT gemasqueerd wordt (UDP 4500 outer header). PepVPN identificeert peers via serial-number, waardoor de transport-laag masquerade transparant is voor de applicatielaag. Het bewijs van de actieve masquerade zit in VyOS nft/conntrack-output (counter rule 310 groeit, masquerade-entry voor UDP 4500 aanwezig), niet in de PepVPN-UI.

### Conclusie

Scenario 7 bevestigt dat de observability-laag routing-agnostisch is: ondanks de SNAT-masquerade op de transport-laag (UDP 4500) blijven alle drie monitoringsbronnen — ICMP probes (blackbox-exporter), InControl2-API en PepVPN-tunnelstatus — correct rapporteren dat Live1 gezond is, en vertoont de tunnel geen flap. PepVPN's serial-based peer-identificatie maakt het ontwerp inherent NAT-tolerant. De observability-stack is daarmee niet afhankelijk van een specifiek transport-IP maar van de tunneladressering (10.1.x.x), wat de routing-agnostische claim valideert.

### Screenshots (nog te maken door gebruiker)

- `scenario_7_post_nat_steady.png` — Grafana sectie 5 (alle tunnels groen, live na NAT-ingreep)
- `scenario_7_vyos_nat_rule.png` — terminal: `sudo nft list chain ip vyos_nat POSTROUTING` (counter rule 310 zichtbaar)
- `scenario_7_vyos_conntrack.png` — terminal: `sudo conntrack -L | grep -E "10\.1\.3\.2.*4500|4500.*10\.1\.1\.1"` (masquerade-bindings)

Plaatsing: `poc/screenshots/` én (na selectie) ook in `bachproef/`.

### Rollback (optioneel)

```
configure
delete nat source rule 310
commit
save
```

Alternatief: rule 310 blijft staan als permanente uitbreiding van de PoC; scenario 7 wordt dan de "default-state" voor Live1 en de bachproef is aantoonbaar robuuster.

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
