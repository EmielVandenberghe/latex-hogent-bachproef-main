# Monitoring blind-spot: `peplink_tunnel_up` rapporteerde groen zonder profielen

**Datum ontdekking:** 15 april 2026 (tijdens Live3 topologie-uitbreiding)  
**Impact:** sectie 5 "PepVPN Tunnels" van het Grafana dashboard toonde alle tunnels als UP gedurende de periode 7-15 april, terwijl er in die periode aantoonbaar geen PepVPN profielen bestonden in InControl2.  
**Ernst:** hoog — een observability-stack die onjuiste tunnel-status rapporteert ondergraaft de volledige claim van de PoC. Moet expliciet opgelost en gedocumenteerd worden.

---

## Samenvatting

Na de FusionHub re-claim op 7 april zijn de PepVPN-profielen in InControl2 niet opnieuw aangemaakt (tot 15 april). Toch bleef de metric `peplink_tunnel_up{device_name=~".*"}` in Prometheus op `1` staan voor elk FusionHub-device. De oorzaak is een logische fout in `incontrol2_exporter.py` die "geen profielen geconfigureerd" interpreteert als "alle tunnels gezond", gecombineerd met het default-gedrag van `prometheus_client.Gauge` dat oude waardes onveranderd laat als er tijdens een scrape geen update komt.

## Root cause — exporter logica

In [incontrol2_exporter.py:156-175](stack/incontrol2_exporter.py#L156-L175):

```python
def get_tunnel_stat(self, org_id, group_id, device_id):
    """Returns True=all ok, False=error, None=pending/unknown."""
    endpoint = f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/pepvpn/tunnel_stat"
    try:
        result = self.get(endpoint)
        code = result.get("resp_code")
        if code == "SUCCESS":
            data = result.get("data", {})
            if isinstance(data, list):
                if not data:
                    return True   # <- BUG
                return all(t.get("stat") == "ok" for t in data if isinstance(t, dict))
            elif isinstance(data, dict):
                return data.get("stat") == "ok"
        return None
    except Exception:
        return False
```

De comment in de broncode zegt expliciet `# no tunnels configured = no errors`. Die aanname is fout. "Geen tunnels geconfigureerd" is een fundamenteel andere toestand dan "alle N geconfigureerde tunnels zijn gezond" en moet als zodanig meetbaar zijn. Door beide op `True` te mappen verliest de metric zijn informatiewaarde.

In [incontrol2_exporter.py:550-557](stack/incontrol2_exporter.py#L550-L557) wordt de return-waarde gebruikt:

```python
stat = client.get_tunnel_stat(org_id, IC_GROUP_ID, d_id)
if stat is not None:
    tunnel_up.labels(d_id, d_name).set(1 if stat else 0)
```

Resultaat: voor elk device wordt `peplink_tunnel_up=1` gezet zolang IC2 een lege lijst teruggeeft — onafhankelijk van of er ooit een profiel heeft bestaan.

## Secundaire oorzaak — Gauge-staleness

`Gauge.set(value)` in `prometheus_client` behoudt de laatste waarde totdat hij opnieuw gezet of verwijderd wordt. De scrape-loop in `collect_metrics` roept nergens `gauge.clear()` of `gauge.remove(*labels)` aan bij start van een cycle. Twee gevolgen:

1. Als een device uit de IC2 `get_devices_with_status` response valt (bv. offline, ge-unenrolled, verwijderd), blijft zijn laatst bekende `peplink_tunnel_up` waarde voor altijd in de registry staan.
2. Prometheus ziet deze waardes elke 15s opnieuw — ze worden niet stale, dus `absent()` en staleness-markers detecteren niets.

## Hoe het zichtbaar werd

Tijdens de Live3 sessie op 15 april werd de IC2 SpeedFusion VPN page geopend en bleek leeg. Uit gesprek met de gebruiker: profielen waren sinds de re-claim op 7 april niet aangemaakt. Bij het controleren van Grafana sectie 5 "PepVPN Tunnels" stonden alle 4 FusionHub-devices echter groen. Dit mismatcht de werkelijkheid en leidde tot het onderzoek.

## Fix — voorstel (twee lagen)

### Laag 1: exporter semantiek corrigeren

Onderscheid "geen profielen" van "alle profielen gezond" via een extra metric + scherpere set-logica.

Patch-voorstel voor `incontrol2_exporter.py`:

```python
# Nieuwe metric naast peplink_tunnel_up
tunnel_count = Gauge(
    'peplink_tunnel_count',
    'Number of PepVPN tunnels configured on device',
    ['device_id', 'device_name']
)

def get_tunnel_stat(self, org_id, group_id, device_id):
    """Returns (count, all_ok) tuple. count=0 means no profiles, all_ok only valid when count>0."""
    endpoint = f"/rest/o/{org_id}/g/{group_id}/d/{device_id}/pepvpn/tunnel_stat"
    try:
        result = self.get(endpoint)
        if result.get("resp_code") != "SUCCESS":
            return (None, None)
        data = result.get("data", {})
        if isinstance(data, list):
            count = len(data)
            if count == 0:
                return (0, None)            # geen profielen -- onbepaald
            return (count, all(t.get("stat") == "ok" for t in data if isinstance(t, dict)))
        if isinstance(data, dict):
            return (1, data.get("stat") == "ok")
        return (None, None)
    except Exception as e:
        log.warning("tunnel_stat failed for device %s: %s", device_id, e)
        return (None, None)
```

En in `collect_metrics`:

```python
count, stat = client.get_tunnel_stat(org_id, IC_GROUP_ID, d_id)
if count is not None:
    tunnel_count.labels(d_id, d_name).set(count)
    if count == 0:
        # Geen profielen configureerbaar -- tunnel_up expliciet 0 (of .remove)
        tunnel_up.labels(d_id, d_name).set(0)
    elif stat is not None:
        tunnel_up.labels(d_id, d_name).set(1 if stat else 0)
```

Met dit patroon:
- `peplink_tunnel_count == 0` -- geen profielen -- `peplink_tunnel_up = 0` (correct: "geen healthy tunnel")
- `peplink_tunnel_count > 0 and peplink_tunnel_up == 1` -- alle profielen gezond
- `peplink_tunnel_count > 0 and peplink_tunnel_up == 0` -- minstens één profiel in error

### Laag 2: stale-label opruiming

Voeg aan het begin van elke `collect_metrics` cycle een `.clear()` toe op de device-gerelateerde gauges, zodat devices die uit de IC2 response verdwijnen ook uit Prometheus verdwijnen:

```python
def collect_metrics(client, org_id):
    # Stale labels opruimen voor nieuwe scrape (voorkomt oude waardes bij verdwenen devices)
    tunnel_up.clear()
    tunnel_count.clear()
    device_online.clear()
    device_uptime.clear()
    device_clients.clear()
    device_usage.clear()
    device_tx.clear()
    device_rx.clear()
    recent_event_count.clear()
    ...
```

Nadelen: Grafana heeft nu korte "no data" gaps per scrape-cyclus mogelijk. Alternatief: alleen `.remove(*labels)` aanroepen voor device_ids die in de huidige response ontbreken. Dit is veiliger maar vereist state-tracking. Voor een PoC is `.clear()` acceptabel — scrape-interval is 15s, Grafana rendert doorgaans niet per-sample.

### Laag 3: dashboard verdediging

In sectie 5 panels expliciet `peplink_tunnel_count` naast `peplink_tunnel_up` tonen. Als een panel 0 profielen toont maar "up" rapporteert, is dat visueel meteen herkenbaar als een anomalie. Extra: een stat-panel "PepVPN Profielen geconfigureerd" met `sum(peplink_tunnel_count)` als snelle sanity-check bovenaan de sectie.

### Laag 4: alerting-regel

Nieuwe regel (buiten scope van huidige 9 rules, maar aan te bevelen):

```yaml
- alert: PepVPN No Profiles Configured
  expr: max(peplink_tunnel_count) == 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Geen PepVPN profielen geconfigureerd op enig device"
    description: "Monitoring kan tunnel-gezondheid niet valideren omdat er geen profielen zijn."
```

Deze regel had de blind-spot op 7 april binnen 5 minuten gedetecteerd.

## Hoe te verwerken in de bap (verdedigbaarheid)

Deze bevinding is geen zwakte maar een sterkte van het werk — mits eerlijk gerapporteerd. Aanbevolen plaatsing:

1. **`poc.tex` observability-validatie sectie:** expliciete subsectie "Zelf-validatie van de stack" waarin dit voorbeeld staat. Drie observable momenten:
   - Symptoom gedetecteerd (sectie 5 groen terwijl profielen ontbraken)
   - Root cause geïdentificeerd (exporter returnt `True` bij lege lijst)
   - Patch + verdediging in meerdere lagen (semantiek, staleness, dashboard, alert)

2. **`methodologie.tex`:** opnemen als case-study voor iteratief PoC-werk. Monitoring van een monitoring-systeem is recursief — je moet elke metric valideren tegen de grond-waarheid, niet alleen tegen wat het dashboard toont.

3. **`conclusie.tex` aanbevelingen:** algemene les voor productie-observability: **onderscheid "geen data" van "alles is goed"**. Default-to-healthy is een klassieke observability-antipattern (zie o.a. Google SRE boek, "The Myth of Unknown Unknowns"). Elke aggregator/exporter die deze aanname maakt is een latent risico.

4. **Eerlijkheid over de periode:** de screenshots van voor 15 april die tunnel-status tonen zijn retroactief ongeldig als bewijs voor PepVPN-gezondheid. Ze blijven wel geldig voor andere secties (ICMP, SNMP, lokale API, CPU, SRT). In de bap expliciet vermelden welke baseline screenshots opnieuw gemaakt moeten worden na de fix.

## Checklist na toepassing fix

- [ ] Patch toegepast in `incontrol2_exporter.py` (laag 1)
- [ ] `.clear()` calls toegevoegd (laag 2)
- [ ] Nieuwe metric `peplink_tunnel_count` gescraped door Prometheus
- [ ] Dashboard sectie 5 uitgebreid met `peplink_tunnel_count` panel (laag 3)
- [ ] Nieuwe alert-regel geprovisioneerd (laag 4)
- [ ] End-to-end test: profiel verwijderen -- binnen 1 minuut tunnel_up=0 in Grafana
- [ ] End-to-end test: profiel opnieuw aanmaken -- binnen 1 minuut tunnel_up=1
- [ ] Nieuwe baseline screenshot sectie 5 met zichtbare profiel-count
