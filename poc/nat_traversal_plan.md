# NAT-traversal validatie (scenario 7)

Laatste update: 2026-04-20

## Doel

De bachproef-tekst (methodologie §Fase 5) benoemt drie connectiviteits­scenarios
als productcontext voor PepVPN:

1. beide sites op publiek IP,
2. één site achter NAT,
3. beide sites achter NAT.

De basis-PoC test geen van die drie empirisch: alle 4 FusionHubs + Balance 20X
zitten achter dezelfde VyOS, die enkel routet (zonder NAT tussen de subnets).
Arne (co-promotor) heeft hier op gewezen: de bachproef gaat óók over routing,
niet enkel observability.

Dit scenario voegt één expliciet **asymmetrisch NAT**-geval toe aan de PoC,
net genoeg om de kernclaim van de observability-laag te valideren zonder in
volledige hole-punching / CGNAT-simulatie te verzanden. De claim die we
bewijzen:

> Zolang `peplink_tunnel_up=1` blijft de observability-stack routing-agnostisch,
> omdat alle exporters monitoringverkeer over tunneladressen (10.1.x.x) sturen,
> ongeacht of een spoke publiek IP, één NAT-laag of (gesimuleerde) dubbele
> NAT gebruikt.

Wat we expliciet **niet** valideren (buiten scope):
- PepVPN's eigen NAT-T / hole-punching onder CGNAT-condities.
- Keepalive-timing en port-rebind-frequentie onder flappende NAT-bindings.
- Full hole-punching met beide eindpunten achter NAT.

Dat is commerciële productfunctionaliteit van Peplink.

## Setup

**Voor:** FH-Live1 (10.1.3.2) communiceert rechtstreeks met FH-Bornem
(10.1.1.2) via VyOS-routing. FH-Bornem ziet PepVPN-peer = 10.1.3.2.

**Na:** één extra SNAT-regel op VyOS masquereert verkeer van 10.1.3.0/24
richting 10.1.1.0/24. FH-Bornem ziet PepVPN-peer dan als 10.1.1.1 (VyOS-IP
in het Bornem-subnet). Dat simuleert "Live1 zit achter NAT vanuit het
perspectief van Bornem". Live1 blijft tunnel outbound-initiëren; VyOS
connection-tracking zorgt voor correcte teruggerouteerde replies.

De andere tunnel van Live1 (P2P naar Venue, via eth2) blijft onaangeraakt.

```
          ┌──────────┐                      ┌───────────┐
          │ FH-Live1 │ 10.1.3.2             │ FH-Bornem │ 10.1.1.2
          └────┬─────┘                      └─────▲─────┘
               │                                  │
        eth3 (10.1.3.1)              eth1 (10.1.1.1)
               │                                  │
               └──────────► VyOS ─────────────────┘
                      SNAT rule 310: masq
                      (10.1.3.0/24 → 10.1.1.0/24)

Voor SNAT: Bornem ziet peer 10.1.3.2
Na  SNAT: Bornem ziet peer 10.1.1.1   ← asymmetrische NAT
```

## Procedure

### A. Snapshot vooraf

```bash
# Obs VM via Vagrant
KEY="poc/stack/.vagrant/machines/default/virtualbox/private_key"
ssh -i "$KEY" -p 2222 -o StrictHostKeyChecking=no \
  -o PubkeyAcceptedKeyTypes=+ssh-rsa vagrant@127.0.0.1

# Op obs VM
curl -s 'http://localhost:9090/api/v1/query?query=peplink_tunnel_up' | jq .
```

Screenshot Grafana sectie 5 (PepVPN Tunnels) als baseline:
`scenario_7_pre_nat.png`.

### B. SNAT-regel activeren

```bash
# Op obs VM
sshpass -p vyos ssh -o StrictHostKeyChecking=no vyos@192.168.137.10
```

In VyOS configure-mode:

```
configure
set nat source rule 310 description "Scenario 7: asymmetric NAT FH-Live1"
set nat source rule 310 source address 10.1.3.0/24
set nat source rule 310 destination address 10.1.1.0/24
set nat source rule 310 outbound-interface name eth1
set nat source rule 310 translation address masquerade
commit
save
exit
```

Verificatie:

```bash
show nat source rules
show nat source translations
```

### C. Gedrag observeren

Verwacht verloop:

1. **t+0 s**: regel actief. Bestaande tunnel ziet plots src-IP wijzigen
   (10.1.3.2 → 10.1.1.1 na masquerade). PepVPN detecteert dit als een
   NAT-rebind.
2. **t+0–60 s**: korte flap mogelijk. `peplink_tunnel_up{tunnel=~".*Live1.*"}`
   kan 1 → 0 → 1 gaan. Alert "PepVPN Tunnel Down" kan pending → firing
   triggeren als de flap >1 min duurt.
3. **t+60–120 s**: tunnel re-established, Bornem ziet peer 10.1.1.1.
   Monitoring herstelt volledig: ICMP, SNMP, API via 10.1.3.2 blijven
   werken (obs VM → Live1 verkeer loopt via eth3, niet via NAT rule 310).
4. **Steady-state**: tunnel up, asymmetrische NAT actief, alle exporters
   groen.

### D. Validatie

Op obs VM:

```bash
# Tunnel status
curl -s 'http://localhost:9090/api/v1/query?query=peplink_tunnel_up{device_name="Live1"}' | jq .

# Monitoring over tunneladres werkt
curl -s 'http://localhost:9090/api/v1/query?query=probe_success{site="Live1"}' | jq .
curl -s 'http://localhost:9090/api/v1/query?query=peplink_snmp_reachable{site="Live1"}' | jq .
curl -s 'http://localhost:9090/api/v1/query?query=peplink_api_reachable{site="Live1"}' | jq .
```

Alles moet 1 zijn. Als één van deze 0 is, is de routing-agnostische claim
niet bewezen voor die laag — onderzoek eerst vóór je verder gaat.

Op FH-Bornem webadmin (https://192.168.137.10:8441, admin/Bornem12345)
onder **SpeedFusion > Status**: peer-IP voor de Live1-tunnel moet nu
10.1.1.1 zijn in plaats van 10.1.3.2. Screenshot:
`scenario_7_bornem_peer_natted.png`.

Op VyOS:

```
show nat source translations | grep 10.1.3
```

moet actieve masquerade-bindings tonen.

### E. Screenshots

- `scenario_7_pre_nat.png` — Grafana sectie 5 baseline (peer-IP origineel)
- `scenario_7_flap.png` — kortstondige flap van `peplink_tunnel_up` (optioneel)
- `scenario_7_post_nat_steady.png` — tunnel up, alle monitoring groen
- `scenario_7_bornem_peer_natted.png` — FH-Bornem webadmin toont peer als 10.1.1.1
- `scenario_7_vyos_nat_translations.png` — VyOS toont actieve masquerade-binding
- `scenario_7_prometheus_queries.png` — curl output van alle bovenstaande queries

### F. Opruimen (na validatie + screenshots)

De SNAT-regel mag blijven staan als permanent onderdeel van de PoC —
dan is scenario 7 het "default gedrag" voor Live1 en is de bachproef
aantoonbaar robuuster. Alternatief: terugdraaien om originele symmetrische
routing te herstellen.

Terugdraaien:

```
configure
delete nat source rule 310
commit
save
exit
```

## Verwachte .tex-invoegingen

De PoC-scope-paragraaf (poc.tex §sec:poc-scope) is al herschreven en
verwijst naar dit scenario. De feitelijke scenario-beschrijving moet nog
toegevoegd worden in poc.tex §sec:poc-tests na scenario 6. Structuur
analoog aan scenario 4/5/6:

- Inleidende paragraaf: wat wordt gesimuleerd en waarom.
- Uitvoeringsstappen: de `set nat source rule 310 ...` commando's als
  `lstlisting` of `verbatim`.
- Resultaat: bullet-list van waarnemingen (flap-duur, peer-IP verschuiving,
  alle 3 monitoring-lagen blijven groen).
- Eén of twee `\begin{figure}` blokken met de screenshots hierboven.
- Label `fig:scenario-7` + `sec:scenario-7`.

Voorstel kernzin voor conclusie-paragraaf van het scenario:

> "Scenario~7 bevestigt dat de observability-laag routing-agnostisch is:
> ondanks dat FH-Bornem zijn PepVPN-peer na de NAT-ingreep onder een ander
> IP-adres ziet, blijft \texttt{peplink\_tunnel\_up=1} en blijven de drie
> onafhankelijke monitoringsbronnen (ICMP, SNMP, lokale API) correct
> rapporteren. De stack werkt dus niet bij toeval op de directe routing
> van de virtuele testomgeving."

## Risico's en rollback

- **Risico:** tunnel komt niet terug op na NAT-ingreep. → Rollback via
  `delete nat source rule 310; commit`. Tunnel herstelt binnen 30–60 s.
- **Risico:** InControl2 toont device_online=0 voor Live1 door NAT-conflict
  met andere devices op 10.1.1.1 masquerade-pool. Hoogst onwaarschijnlijk
  omdat conntrack dit opvangt, maar zo ja: rollback.
- **Risico:** FH-Bornem's PepVPN weigert de nieuwe peer-IP (bv. omdat het
  profiel IP-locked is). → PepVPN gebruikt serial-based identificatie dus
  dit zou niet mogen; indien toch: rollback en documenteer als bijkomende
  scope-beperking.

## Why

Arne's feedback (16 april): "de bachproef gaat niet enkel over observability,
ook over routing". Zonder minstens één NAT-scenario lopen de .tex-tekst (die
drie scenarios benoemt) en de feitelijke PoC-opzet uit elkaar. Dit scenario
dekt het gat zonder volledige Niveau 3-simulatie (hole-punching + publiek
IP-segment), die te veel tijd zou vreten voor de deadline 4 mei 2026.
