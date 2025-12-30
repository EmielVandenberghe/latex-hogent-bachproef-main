# Scope Checklist - Wat Moeten We Weten?

## Doel
Een overzicht van de minimale informatie die we nodig hebben per apparaattype om een monitoringoplossing te kunnen bouwen.

---

## 1. Peplink Routers (20X, 380X, Bornem)

### Basisinfo
- [ ] Welke modellen precies? (20X, 380X, ...)
- [ ] Hoeveel stuks van elk model?
- [ ] Waar staan ze? (welke locaties)

### Monitoring - Wat kunnen we eruit halen?
- [ ] Heeft het een API? (InControl2 API)
- [ ] Kunnen we daar real-time data uit krijgen?
- [ ] Welke metrics zijn beschikbaar?
  - Bandbreedte per WAN-link (5G, Starlink, fiber)?
  - Latency (vertraging)?
  - Packet loss (pakketverlies)?
  - VPN tunnel status?
  - Welke link is actief/inactief?

### Wat willen we detecteren?
- [ ] Wanneer een link uitvalt
- [ ] Wanneer een link traag wordt
- [ ] Hoeveel data er over elke link gaat
- [ ] VPN tunnel problemen

---

## 2. NDI Apparatuur

### Basisinfo
- [ ] Welke NDI-apparaten zijn er, hoeveel data simuleren we zodat het vergelijkbaar is?
  - Camera's?
  - Converters?
  - Software mixers?
  - **Birddog apparaten?**
- [ ] Hoeveel NDI-streams tegelijk? (typisch)
- [ ] Waar worden NDI-streams gemixed? (welke software/hardware)

### Monitoring - Wat kunnen we eruit halen?
- [ ] Hoe kunnen we NDI-streams zien? (NDI Monitor tool?)
- [ ] Kunnen we per stream zien:
  - Hoeveel bandbreedte het gebruikt?
  - Of er frames worden gedropped?
  - Stream kwaliteit?
- [ ] **Birddog Connect**: Heeft dit een API? Wat kan je ermee monitoren?

### Wat willen we detecteren?
- [ ] Wanneer een NDI-stream wegvalt
- [ ] Wanneer er frame drops zijn
- [ ] Te hoge bandbreedte usage (netwerk overbelast)
- [ ] Welke NDI-bronnen zijn beschikbaar op het netwerk

---

## 3. SRT Encoders & Decoders

### Basisinfo
- [ ] Welke software/hardware wordt gebruikt?
  - Voor encoding (NDI → SRT)?
  - Voor decoding (SRT → terug NDI/lokaal)?
- [ ] Op welke machines draait dit?

### Monitoring - Wat kunnen we eruit halen?
- [ ] Heeft SRT software statistieken?
  - RTT (Round Trip Time - hoe lang data heen en terug doet)?
  - Packet loss?
  - Retransmissions (hoeveel pakketten moesten opnieuw verzonden)?
  - Bitrate?
- [ ] Waar kunnen we die stats zien? (logs, API, web interface?)

### Wat willen we detecteren?
- [ ] Slechte verbindingskwaliteit (veel packet loss)
- [ ] Hoge latency
- [ ] Veel retransmissions (teken van netwerkproblemen)
- [ ] Encoding/decoding problemen

---

## 4. Switches (Netgear M4250)

### Basisinfo
- [ ] Welke modellen?
- [ ] Hoeveel stuks?
- [ ] Waar staan ze in het netwerk?

### Monitoring - Wat kunnen we eruit halen?
- [ ] SNMP support? (standaard protocol voor switch monitoring)
- [ ] Kunnen we zien:
  - Hoeveel traffic per poort?
  - Multicast groepen?
  - Errors op poorten?
  - VLAN traffic?

### Wat willen we detecteren?
- [ ] Overbelaste poorten
- [ ] Multicast problemen (belangrijk voor NDI!)
- [ ] Switch errors
- [ ] Welke devices zitten op welke poort?

---

## 5. WAN Connecties

### Basisinfo
- [ ] Welke soorten connecties?
  - 5G modems (welke provider?)
  - Starlink
  - Glasvezel
- [ ] Hoeveel per locatie?

### Monitoring - Wat kunnen we eruit halen?
- [ ] Komt dit via Peplink API?
- [ ] Per link:
  - Up/down status?
  - Bandbreedte (max en current)?
  - Latency?
  - Packet loss?

### Wat willen we detecteren?
- [ ] Link failures
- [ ] Degradatie (link wordt slechter maar valt niet helemaal uit)
- [ ] Welke link is primary/backup?

---

## Samenvatting: Kernvragen

### Voor elk apparaat type moeten we weten:

1. **Wat is het?**
   - Merk, model, aantal, locatie

2. **Hoe krijgen we data eruit?**
   - API (REST, SNMP, ...)?
   - Logs?
   - Web interface scraping?
   - Speciale tools?

3. **Welke metrics zijn beschikbaar?**
   - Lijst van alle mogelijke metingen

4. **Wat zijn de kritieke metrics?**
   - Welke metingen zijn het belangrijkst om problemen te detecteren?

5. **Hoe vaak kunnen we data ophalen?**
   - Real-time?
   - Per seconde?
   - Per minuut?

---

## Volgende Stappen

1. Voor elk apparaat type:
   - Documentatie opzoeken (API docs, user manuals)
   - Test setup maken (als mogelijk)
   - Kijken wat er echt uitkomt

2. Prioriteit: Start met wat al beschikbaar is
   - InControl2 (Peplink) - lijkt het meest documented
   - Daarna NDI (veel community info)
   - Dan SRT
   - Dan switches

3. Vraag aan Arne:
   - Welke exacte modellen/software?
   - Access tot test apparatuur?
   - Kan je InControl2 demo account krijgen?
   - Voorbeelddata van een live event?

---

**Let op:** We hoeven niet ALLES te monitoren in de eerste versie (MVP).
Focus eerst op de hoofdflow: **Peplink → SRT → NDI** zoals in het voorstel staat.
Later uitbreiden naar switches, individual devices, etc.
