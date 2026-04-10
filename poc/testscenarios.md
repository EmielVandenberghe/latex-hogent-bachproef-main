# Testscenario's — Validatie van het POC

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Overzicht

Het voorstel beschrijft drie validatiescenario's voor fase 6:

| Scenario | Beschrijving |
|----------|-------------|
| **1 — Baseline** | Normale werking zonder storingen |
| **2 — Netwerkstoringen** | Gesimuleerde packet loss en latency |
| **3 — Overbelasting** | Meerdere gelijktijdige datastromen |

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

### 2c — Combinatie: packet loss + latency

```bash
# Realistische WAN-simulatie op Live2: 5% loss + 100ms delay + 20ms jitter
sudo tc qdisc add dev eth4 root netem delay 100ms 20ms distribution normal loss 5%
```

**Herstellen:**
```bash
sudo tc qdisc del dev eth4 root
```

---

### 2d — Volledige verbindingsonderbreking

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
