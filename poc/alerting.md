# Grafana Alerting — Proactieve Notificaties

**Bachelorproef Mediaventures Observability POC — maart 2026**

---

## Overzicht

Grafana Alerting evalueert alert rules elke minuut op basis van Prometheus-queries. Wanneer een conditie voldaan is gedurende de ingestelde duur, gaat de alert naar "Firing" en wordt een notificatie gestuurd.

In het POC zijn **10 alert rules** geconfigureerd via `poc/stack/provisioning/alerting/alerts.yml`.

---

## Geconfigureerde alerts

| Alert | Prioriteit | Trigger | For |
|-------|-----------|---------|-----|
| Device Offline | CRITICAL | `(1 - peplink_device_online) > 0` | 1 min |
| PepVPN Tunnel Down | CRITICAL | `(1 - peplink_tunnel_up) > 0` | 1 min |
| PepVPN No Profiles Configured | WARNING | `peplink_tunnel_count == 0` | 5 min |
| Site onbereikbaar (ICMP) | WARNING | `(1 - probe_success{job="blackbox_icmp"}) > 0` | 2 min |
| Hoge VPN-latency | WARNING | RTT > 150ms | 5 min |
| Hoog packet loss | WARNING | Packet loss > 5% | 5 min |
| SRT Stream Packet Loss | WARNING | `srt_packet_loss_percent > 5` | 1 min |
| WAN Link Down | WARNING | `(1 - peplink_snmp_wan_link_up{wan_name="WAN"}) > 0` | 2 min |
| Hoge CPU Load | WARNING | `peplink_local_cpu_load_percent > 85` | 5 min |
| Exporter down | CRITICAL | `(1 - peplink_scrape_success) > 0` | 2 min |

> **Noot `PepVPN No Profiles Configured` (toegevoegd 2026-04-16):** deze regel is het antwoord op de monitoring blind-spot die beschreven is in [monitoring_blindspot.md](monitoring_blindspot.md). Voor de fix rapporteerde `peplink_tunnel_up` een waarde van 1 (of ontbrak het metric volledig) wanneer er geen profielen in InControl2 aanwezig waren, waardoor "PepVPN Tunnel Down" nooit kon firen. De exporter telt nu expliciet het aantal gescande profielen per device en publiceert `peplink_tunnel_count`. Als dit voor een device op 0 zakt, firet de nieuwe alert binnen 5 minuten en wordt het ontbreken van profielen zichtbaar.

> **Opmerking syntax:** Grafana Unified Alerting behandelt een waarde van `0` als "geen data aanwezig" in sommige contexten, waardoor `== 0` queries niet firen. Alle alerts gebruiken daarom `(1 - X) > 0` zodat een waarde van 0 wél als alarmerend wordt herkend.

---

## Alerts bekijken in Grafana

1. Ga naar http://192.168.137.10:3000
2. Klik in het linkermenu op **Alerting** (belicoon)
3. Klik op **Alert rules** — hier zie je alle regels met hun huidige status:
   - **Normal** — conditie niet actief
   - **Pending** — conditie actief maar nog niet lang genoeg
   - **Firing** — alert actief, notificatie verstuurd

---

## Contact point (notificaties)

Het POC is geconfigureerd met een email contact point naar `admin@mediaventures.be`. Omdat er geen SMTP-server is ingesteld, mislukken de email notificaties maar zijn de alerts wel zichtbaar in de Grafana UI.

**Voor productie:** SMTP instellen via `GF_SMTP_*` environment variabelen in docker-compose.yml:
```yaml
environment:
  - GF_SMTP_ENABLED=true
  - GF_SMTP_HOST=smtp.example.com:587
  - GF_SMTP_USER=alerts@mediaventures.be
  - GF_SMTP_PASSWORD=<wachtwoord>
  - GF_SMTP_FROM_ADDRESS=alerts@mediaventures.be
```

**Alternatief voor productie:** Webhook naar Teams/Slack/PagerDuty — veel eenvoudiger dan email:
```yaml
receivers:
  - uid: teams-webhook
    type: teams
    settings:
      url: https://mediaventures.webhook.office.com/...
```

---

## Alert rules aanpassen

Drempelwaarden aanpassen in `poc/stack/provisioning/alerting/alerts.yml` en dan:
```bash
KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"
scp -i "$KEY" -P 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  poc/stack/provisioning/alerting/alerts.yml \
  vagrant@127.0.0.1:/opt/observability/provisioning/alerting/
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  vagrant@127.0.0.1 "docker restart grafana"
```

---

## Testen van alerts

### Alert manueel triggeren: site onbereikbaar maken

Op VyOS (SSH naar 192.168.137.10), blokkeer ICMP naar Live1:
```
configure
set firewall name BLOCK-LIVE1 rule 1 action drop
set firewall name BLOCK-LIVE1 rule 1 protocol icmp
set firewall name BLOCK-LIVE1 rule 1 destination address 10.1.3.2
set interfaces ethernet eth3 firewall in name BLOCK-LIVE1
commit
```

Na 2 minuten → alert "Site onbereikbaar (ICMP)" gaat naar Firing.

Terugzetten:
```
delete interfaces ethernet eth3 firewall
delete firewall name BLOCK-LIVE1
commit
save
```

### Alert manueel triggeren: hoge latency

Op VyOS, voeg kunstmatige vertraging toe via `tc netem` (zie `testscenarios.md` voor volledige handleiding).

---

## Relatie met thesis

Het voorstel vermeldt expliciet:
> "Een alerting-mechanisme integreren dat techniekers proactief waarschuwt bij kritieke afwijkingen"

Dit is bereikt via Grafana's ingebouwde alerting met:
- Provisioned alert rules (reproduceerbaar, versiebeheerbaar)
- 10 regels gericht op de kritieke parameters voor live AV-productie (netwerk, tunnels, WAN, CPU, SRT stream)
- Koppeling aan een contact point (extensible naar productie notificaties)

---

## Verantwoording `noDataState: OK`

Alle provisioned alert rules in de PoC gebruiken `noDataState: OK`. Dat betekent: als Grafana tijdens een evaluatie-interval geen enkel sample ontvangt voor de query, wordt de alert NIET in Firing of Alerting gezet, maar in OK. Dit is een bewuste keuze en verdient expliciete verantwoording, want de default (`noDataState: Alerting`) zou in veel observability-teksten de veiligere optie lijken.

### Waarom `OK` hier veiliger is dan `Alerting`

1. **Transient scrape-gaps worden niet gepromoot tot incidenten.** Prometheus `scrape_interval=15s` met `evaluation_interval=15s` betekent dat één gemiste scrape (netwerk-hikup, exporter GC-pauze, container-restart) al een leeg evaluatievenster kan opleveren. Met `noDataState: Alerting` zou elke incidentele gap alle 9 regels gelijktijdig laten vuren, resulterend in alert-fatigue en false positives. Dat erodeert het signaalvermogen sneller dan een echte outage mist.

2. **Multi-laag veiligheidsnet dekt het risico af.** Het risico van `noDataState: OK` — dat een echte exporter-down niet opgemerkt wordt — is afgedekt door een aparte alert die specifiek op scrape-gezondheid kijkt:

   ```
   Exporter Down (CRITICAL, 2m):  peplink_scrape_success == 0
   ```

   Als `incontrol2-exporter` crasht of geen data meer levert, firet deze regel binnen 2 minuten. De andere 8 regels hoeven dus niet individueel de "afwezigheid van data" te detecteren — dat is al een gedeelde, centrale verantwoordelijkheid.

3. **Gelaagdheid per faaldomein.** De logica is: **elke regel monitort één specifiek faaldomein**. ICMP-regels monitoren netwerk-bereikbaarheid, SNMP-regels monitoren device-interne toestand, SRT-regels monitoren stream-kwaliteit. Elk met hun eigen "gezondheids-regel" verwarren zou leiden tot dubbele triggers op dezelfde root cause. De `Exporter Down`-regel neemt de scrape-laag voor zijn rekening; de andere regels nemen hun eigen signal-laag.

4. **False-positive kost > false-negative kost voor deze PoC.** In een live AV-productie zijn valse alarmen (techniekers worden 's nachts gewekt voor niks) duurder dan een 2-minuten vertraagde detectie bij scrape-failure, omdat de exporter-down regel dat vertragingsvenster hard begrenst. De time-to-detect-berekening in `srt_monitoring.md` (~2 minuten) houdt al rekening met deze architectuur.

### Wanneer deze keuze wél heroverwogen moet worden

- Als in productie meerdere onafhankelijke exporters naast elkaar draaien en één specifieke metric kritisch is voor safety (bv. een hardware-temperatuur die bij absentie alarmmoet geven), dan kan die specifieke regel op `noDataState: Alerting` gezet worden, zonder de rest aan te passen.
- Als het scrape-interval veel korter wordt (<5s) waardoor gaps onwaarschijnlijk zijn, vervalt argument 1.
- Als de `Exporter Down`-regel zelf onbetrouwbaar blijkt (bv. omdat `peplink_scrape_success` niet meer gescraped wordt — meta-probleem), dan is er een fundamenteel observability-gat dat niet door `noDataState` wordt opgelost en een tweede-laag heartbeat vereist (bv. Grafana's eigen Datasource-health check).

Deze keuze is consistent met het 4-lagen aanpak uit `monitoring_blindspot.md`: **onderscheid "geen data" van "alles is goed"**. `noDataState: OK` is veilig zolang één aparte regel expliciet op "geen data" monitort; zonder die regel zou de keuze onverdedigbaar zijn.
