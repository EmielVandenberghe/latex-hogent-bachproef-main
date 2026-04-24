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

## Scenario 8 — Cross-Layer Correlatie (SRT via VyOS)

**Uitgevoerd op:** 21 april 2026

**Doel:** Toon dat één netwerkdegradatie op VyOS (tc netem op eth1/Bornem-interface) **gelijktijdig zichtbaar is op twee lagen**: de netwerklaag (ICMP RTT, jitter) én de applicatielaag (SRT RTT, packet loss, retransmits). Dit is de kern van observability vs. monitoring: één oorzaak, twee lagen bewijs, één tijdslijn.

**Productiewaarde:** Een NOC-medewerker ziet op het Grafana dashboard niet enkel dát er iets mis is, maar wáár (netwerklaag, niet de encoder) en hoeveel impact (SRT-kwaliteitsmetrics). Diagnose in secondes, niet minuten.

---

### Architectuurwijziging: SRT via VyOS hairpin

De standaard SRT-setup stuurt stream-verkeer via de **loopback** (`127.0.0.1`) van de obs VM. tc netem op VyOS raakt loopback-verkeer nooit. Om cross-layer correlatie mogelijk te maken, wordt de SRT-stream via een **VyOS hairpin-NAT** geleid:

```
srt-test-stream (10.1.1.100) → 10.1.1.1:9000 (VyOS eth1)
  → DNAT: dst 10.1.1.100:9000 + SNAT masquerade: src 10.1.1.1
    → srt-exporter (10.1.1.100:9000)
```

Het SRT-verkeer traverseert nu VyOS eth1 (Bornem-interface) in beide richtingen. tc netem op die interface treft zowel de SRT-stroom als de ICMP-probes naar FH-Bornem (10.1.1.2).

**Vereiste eenmalige setup op VyOS (zie §Setup hieronder):** DNAT rule 50 + SNAT hairpin rule 50.

**Aanpassing docker-compose.yml (al doorgevoerd):** `srt://127.0.0.1:9000` → `srt://10.1.1.1:9000`.

---

### Setup — VyOS NAT (eenmalig uitvoeren)

Via obs VM → VyOS SSH:

```bash
ssh vyos@192.168.137.10   # of via sshpass vanuit obs VM
```

In VyOS configure-modus:

```
configure

# DNAT: redirect UDP:9000 gericht aan VyOS (10.1.1.1) naar obs VM srt-exporter
set nat destination rule 50 description 'SRT hairpin: 10.1.1.1:9000 -> srt-exporter'
set nat destination rule 50 destination address 10.1.1.1
set nat destination rule 50 destination port 9000
set nat destination rule 50 protocol udp
set nat destination rule 50 translation address 10.1.1.100
set nat destination rule 50 translation port 9000

# SNAT hairpin: masqueer src van DNAT'd pakketten zodat de reply via VyOS terugkomt
# (zonder masquerade: srt-exporter stuurt reply rechtstreeks naar srt-test-stream,
#  VyOS ziet de reply niet en conntrack kan de DNAT niet ongedaan maken)
set nat source rule 50 description 'SRT hairpin masquerade obs-VM -> srt-exporter'
set nat source rule 50 source address 10.1.1.100
set nat source rule 50 destination address 10.1.1.100
set nat source rule 50 destination port 9000
set nat source rule 50 outbound-interface name eth1
set nat source rule 50 protocol udp
set nat source rule 50 translation address masquerade

commit
save
```

**Verificatie (na commit):**

```bash
# DNAT rule aanwezig:
show nat destination rules

# SNAT rule aanwezig:
show nat source rules

# Herstart srt-test-stream op obs VM zodat hij verbindt met nieuwe endpoint:
# (via SSH op obs VM)
cd /opt/observability && docker compose --profile demo up -d --force-recreate srt-test-stream
```

**Verwachte status na setup:**
- `srt_stream_active=1`, `srt_bitrate_kbps` ~1695, `srt_rtt_ms` ~1–3 ms (iets hoger dan loopback door echte IP-stack traversal)
- Prometheus target `srt_exporter` blijft UP

---

### 8a — Netemdegradatie op VyOS eth1 (Bornem-interface)

**Commando op VyOS:**

```bash
sudo tc qdisc add dev eth1 root netem delay 50ms 15ms distribution normal loss 5%
```

**Verwacht resultaat in Grafana (na ~30–60 seconden):**

| Metric | Baseline | Na netem |
|--------|---------|---------|
| `probe_icmp_duration_seconds{site="Bornem"}` | ~1 ms | ~100 ms (heen + terug via eth1) |
| `ping_jitter_ms{site="Bornem"}` | < 1 ms | 10–20 ms |
| `ping_packet_loss_percent{site="Bornem"}` | 0% | ~5% |
| `srt_rtt_ms` | ~1–3 ms | ~100 ms |
| `srt_packet_loss_percent` | ~0% | 2–8% (ARQ compenseert deels) |
| `srt_retransmit_total` | stabiel | stijgt continu |
| `srt_bitrate_kbps` | ~1695 | fluctueert (ARQ-overhead) |

**Cross-layer correlatie zichtbaar in sectie 2 (ICMP) én sectie 11 (SRT) — gelijktijdig op dezelfde tijdas.**

> **Kernboodschap voor het bap:** Op het moment dat de ICMP-RTT voor Bornem stijgt van 1 ms naar 100 ms, stijgt de SRT-RTT mee — en beginnen retransmits te toenemen. Eén blik op het dashboard vertelt het verhaal: het is een netwerkprobleem (ICMP bevestigt), niet de encoder (SRT bevestigt de propagatieroute). Diagnose in < 30 s, zonder in te loggen op apparaten.

**Screenshots te maken:**
- `scenario_8_baseline_crosslayer.png` — sectie 2 + sectie 11, baseline (alles groen/laag)
- `scenario_8_netem_active.png` — sectie 2 + sectie 11 samen, netem actief: ICMP RTT ~100ms én SRT RTT ~100ms zichtbaar op dezelfde tijdlijn
- `scenario_8_retransmits.png` — sectie 11 close-up: retransmit-rate stijgend
- `scenario_8_alert_pending.png` — alert "Hoge latency >150ms" of "Hoog packet loss >5%" → Pending/Firing

**Alerts die kunnen firen:**
- "Hoge latency >150ms" (WARNING, 5 min for-duur) — Bornem ICMP
- "Hoog packet loss >5%" (WARNING, 5 min for-duur) — Bornem + SRT
- "SRT Stream Packet Loss >5%" (WARNING, 1 min for-duur)

---

### 8b — Herstel

```bash
sudo tc qdisc del dev eth1 root
```

**Verwacht herstel (< 30 s):**
- ICMP RTT terug < 5 ms
- SRT RTT terug < 5 ms
- Retransmit-rate stabiliseert

**Screenshot:** `scenario_8_recovery.png` — beide lagen terugkeer naar baseline op dezelfde tijdas.

---

### Bevindingen Scenario 8

1. **Eén ingreep, twee lagen:** tc netem op VyOS eth1 treft zowel ICMP-probes als SRT-stream. De tijdslijn toont de correlatie zonder enige post-processing: de stijging begint op hetzelfde moment.
2. **Routing-agnostische SRT-metrics:** Ondanks de VyOS hairpin-NAT (DNAT + SNAT masquerade) rapporteert `srt-live-transmit` correct de end-to-end RTT en loss — de NAT-lagen zijn transparant voor de SRT-statistieken.
3. **ARQ-compensatie zichtbaar:** Bij 5% netem-loss blijft de gemeten `srt_packet_loss_percent` initieel lager (ARQ herstelt), maar `srt_retransmit_total` onthult de verborgen netwerkdruk. Dit bevestigt de bevinding uit scenario 4a.
4. **Detectielaag onderscheid:** ICMP detecteert de netwerkoorzaak. SRT bevestigt de impact op de applicatielaag. Beide zijn nodig: ICMP alleen zegt niet hoe erg de stream lijdt; SRT alleen zegt niet of het netwerk of de encoder de oorzaak is.
5. **Hairpin-NAT transparantie:** VyOS DNAT rule 50 + SNAT masquerade rule 50 zijn eenmalig geconfigureerd. In productie zijn die NAT-lagen er niet — het échte netwerk (meerdere hops, carrier-grade NAT op 4G/5G) vervult die rol. Scenario 8 bewijst dat de observability-stack ook dan correct coreleert.

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

## Scenario 9 — BirdDog Device & Mode Monitoring

**Uitgevoerd op:** 23 april 2026

**Doel:** Valideer dat sectie 13 van het dashboard correct per operatie-modus (encode vs. decode) onderscheidt, dat de twee mode-specifieke alerts firen, en dat de polling-exporter (BirdDog REST API 2.0) binnen één scrape-interval toestandsveranderingen oppikt.

**Context:** `birddog-mock` (Flask, poort 8090) simuleert twee BirdDog-devices: `mock-01` in **decode**-modus (verbindt met een NDI-bron, rapporteert `decode_fps` + `decode_connected`) en `mock-02` in **encode**-modus (rapporteert `encode_bitrate_kbps` + `encode_clients_connected`). De `birddog-exporter` (Python, poort 9119) scrapet de mock API elke 15 s en publiceert Prometheus-gauges. Het dashboard filtert alle mode-specifieke panels via `and on(device) birddog_operation_mode_{encode,decode} == 1`, waardoor een encoder nooit rood oplicht in een decode-paneel en omgekeerd.

### 9a — Baseline verificatie

**Doel:** Visuele regressie-check dat de mode-filters werken.

**Acties:**
1. Open sectie 13 in Grafana (http://192.168.137.10:3000).
2. Controleer dat:
   - **Device Online** en **Operation Mode** beide devices tonen (mock-01 = DECODE, mock-02 = ENCODE).
   - **Decode Connected** enkel `mock-01` toont (groen, VERBONDEN).
   - **Encode Clients** en **Encode Bitrate** enkel `mock-02` tonen (respectievelijk 2 clients, 50 Mb/s).
   - **Decode Framerate** enkel één lijn heeft (mock-01 @ 25 fps).
   - **Encode Framerate** enkel één lijn heeft (mock-02 @ 25 fps).
   - **BirdDog Status Overzicht** (tabel) toont één rij per device, zonder dubbele `Time/instance/job/__name__` kolommen.

**Screenshot:** `scenario_9a_birddog_baseline.png` — sectie 13 volledig groen, geen misleidende rode indicatoren voor de verkeerde modus.

### 9b — Decode-bron wegvalt

**Commando op observability VM:**
```bash
curl -X POST http://localhost:8090/control/disconnect
```

De mock API zet `decode_connected` naar `false`, `decode_fps` naar 0 en leegt de `sourceName`.

**Verwacht resultaat (binnen ~30 s, 2 scrape-intervallen):**
- **Decode Connected** stat-panel voor `mock-01` → **GEEN BRON** (rood).
- **Decode Framerate** timeseries → stapfunctie van 25 fps naar 0.
- Alert **[WARNING] BirdDog Decode Geen Bron** → Pending → Firing (`for: 2m`).
- `mock-02` blijft onaangetast (encode-panels onveranderd).

**Screenshot:** `scenario_9b_birddog_decode_outage.png`.

### 9c — Device volledig offline

**Commando:**
```bash
curl -X POST http://localhost:8091/control/offline
```
(Port 8091 = mock-02, de encoder. Dit zet alle endpoints op 503 → `birddog-exporter` kan geen state ophalen.)

**Verwacht resultaat (binnen ~60 s):**
- **Device Online** toont `mock-02` → **OFFLINE** (rood).
- Alle encode-specifieke panels (Clients, Bitrate, Framerate) tonen voor `mock-02` een plotse val naar 0 / geen data.
- Alert **[CRITICAL] BirdDog Device Offline** → Firing (`for: 1m`).
- `mock-01` (decoder) blijft groen en operationeel — bevestigt dat de twee apparaten onafhankelijk gemonitord worden.

**Screenshot:** `scenario_9c_birddog_device_offline.png`.

### 9d — Herstel

**Commando's:**
```bash
curl -X POST http://localhost:8090/control/connect   # mock-01 decoder opnieuw verbinden
curl -X POST http://localhost:8091/control/online    # mock-02 encoder weer beschikbaar
```

**Verwacht:** beide alerts zakken naar Normal binnen 1–2 min, alle panels groen, framerate- en bitrate-timeseries tonen duidelijke recovery-stap.

### Bevindingen

1. **Mode-filter via `and on(device)`-join werkt correct.** Zonder filter toonde het dashboard voor elke encoder een rood "GEEN BRON"-paneel (vals-positief); na filter verdwijnt een device uit mode-specifieke panels wanneer het de "verkeerde" modus heeft, in plaats van misleidend rood te blijven. Zie technische bevinding: PromQL-patroon `metric{...} and on(device) birddog_operation_mode_decode == 1` als canonieke filter voor multi-mode devices.
2. **Detectietijd decode_connected-flip: instant na eerste scrape** (~15 s). De `decode_connected`-waarde flipped bij de eerstvolgende scrape zichtbaar in het stat-paneel. Alert-latency = scrape + `for: 2m` ≈ 2 min 15 s end-to-end.
3. **Device offline detectie via `birddog_device_online`** is sneller dan via afwezige scrape-data omdat de exporter zelf de state cached: binnen één scrape-cyclus ziet Prometheus de waarde 0 verschijnen, geen `up == 0`-afhankelijkheid nodig.
4. **Tabel-transforms identiek aan scenario 7-leerles:** `labelsToFields(columns)` → `joinByField(device, outer)` → `organize(excludeByName: Time/instance/job/__name__ per refId + renameByName: Value #A..G)`. Zonder de `excludeByName` zou Grafana 14 extra kolommen tonen (7 queries × {Time, instance, job, __name__}).
5. **Mock `before_request` bug — controleroutes moesten uitgesloten worden van offline-check.** De Flask `@app.before_request`-hook retourneerde 503 op *alle* routes wanneer `STATE['offline'] = True`, inclusief `/control/online`. Hierdoor kon een offline device nooit via de API hersteld worden. Fix: `if fail_mode() and not request.path.startswith("/control/"):`. Lesje voor productie: herstelcommando's mogen nooit geblokkeerd worden door dezelfde fout-state die ze moeten oplossen.

---

## Scenario 10 — Teams Alerting via Power Automate

**Uitgevoerd op:** 23 april 2026

**Doel:** Valideer end-to-end dat Grafana Unified Alerting een Teams-notificatie verstuurt via de Power Automate Webhook-integratie. Bewijs dat het NOC een melding ontvangt zonder manueel in te loggen op het dashboard.

**Vereiste voorbereiding:** Power Automate flow aangemaakt (zie `poc/alerting_teams.md` stap 2.2), `TEAMS_WEBHOOK_URL` ingesteld in `.env`, Grafana herstart via `docker compose up -d --force-recreate grafana`.

### 10a — Handmatige contact point test

**Actie in Grafana UI:**
1. Ga naar **Alerting → Contact points → teams-webhook → Test**.
2. Grafana verstuurt een synthetisch testbericht naar de Power Automate URL.

**Verwacht:** Teams-kanaal "Observability-PoC" toont een bericht van Power Automate met `"status": "firing"` en alertname `"TestAlert"`.

**Verificatie Power Automate:** flow.microsoft.com → jouw flow → **Run history** → meest recente run succesvol (groene vinkje).

**Screenshot:** `scenario_10a_teams_test_message.png` — Teams-kanaal met het Grafana testbericht.

### 10b — Echte alert triggert Teams-notificatie

**Commando op observability VM:**
```bash
docker stop srt-test-stream
```

De SRT-stream stopt → `srt_stream_active` wordt 0 → geen loss-metric meer → let op: de **Exporter down**-alert (`peplink_scrape_success`) kan ook firen als de exporter problemen heeft. Veiliger alternatief: stop de NDI-stream.

```bash
docker stop ndi-test-stream
```

`ndi_stream_active` → 0 → alert **[CRITICAL] NDI Stream Inactief** → `for: 1m` → Firing na ~75 s.

**Verwacht resultaat (binnen ~2 min):**
1. Grafana Alerting → **NDI Stream Inactief** → status: **Firing**.
2. Teams-kanaal ontvangt een POST van Power Automate met alert-details.
3. Alert bevat labels `severity=critical`, `source=<NDI-bronnaam>`.
4. `continue: true` in de routing policy zorgt dat ook `mediaventures-default` de alert ziet (Grafana UI-notificatie).

**Screenshot:** `scenario_10b_teams_alert_ndi.png` — Teams-kanaal met de echte NDI-alert.

### 10c — Herstel en resolve-notificatie

**Commando:**
```bash
docker start ndi-test-stream
```

Na ~2 scrape-cycli (30 s) keert `ndi_stream_active` terug naar 1 → Grafana verstuurt een **resolve**-bericht.

**Verwacht:** Teams-kanaal ontvangt een tweede bericht met `"status": "resolved"`. `disableResolveMessage: false` is ingesteld in de contact point provisioning.

**Screenshot:** `scenario_10c_teams_resolve.png`.

### Bevindingen

1. **Power Automate vervangt verouderde O365-connector.** De native Grafana "Microsoft Teams"-integratie gebruikt `outlook.office.com/webhook/...`-URLs die deprecated zijn sinds 2024-10-01. Power Automate Workflow met HTTP-trigger is de enige ondersteunde aanpak in 2025/2026 voor nieuwe tenants.
2. **Routing via `continue: true` — beide kanalen ontvangen de alert.** Zonder `continue: true` zou een gematchte sub-route de default receiver overslaan. Met `continue: true` ontvangt zowel `mediaventures-default` (Grafana UI) als `teams-webhook` de notificatie — belangrijk voor een NOC dat beide kanalen bewaakt.
3. **Env-var substitutie in Grafana provisioning.** Grafana 11 ondersteunt `${ENV_VAR}` in alle provisioning-YAML-bestanden. De Teams-URL staat in `.env` (in `.gitignore`) en wordt via `TEAMS_WEBHOOK_URL=${TEAMS_WEBHOOK_URL}` doorgegeven aan de Grafana-container. Wijzigen van de URL vereist alleen een `docker compose up -d --force-recreate grafana` — geen rebuild.
4. **Time-to-notify ≈ 2 min.** Scrape-interval 15 s + `for: 1m` (NDI-alert) + Power Automate verwerkingstijd (~5-10 s) = ~1 min 30 s tot Teams-notificatie na het stoppen van de stream.

---

## Resultaten documenteren

Maak screenshots van het Grafana dashboard bij elk scenario:
1. **Voor** de simulatie (baseline)
2. **Tijdens** de simulatie (storingen zichtbaar)
3. **Na herstel** (normalisatie zichtbaar in grafieken)

Bewaar screenshots in `poc/screenshots/scenario_X_*.png`.
