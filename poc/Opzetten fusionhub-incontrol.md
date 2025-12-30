# FusionHub Virtuele Testomgeving - Setup Handleiding

## Overzicht

Virtuele testomgeving met 4 Peplink FusionHub VMs die de Mediaventures infrastructuur simuleert: centrale site (Bornem), venue, en twee live-surgery locaties. Alle VMs worden beheerd via InControl2.

## Architectuur
```
[Internet via ICS]
        |
   [VyOS Router]
    eth0: 192.168.137.10 (Host-only, naar ICS)
    eth1: 10.1.1.1/24 (intnet-bornem)
    eth2: 10.1.2.1/24 (intnet-venue)
    eth3: 10.1.3.1/24 (intnet-surgery1)
    eth4: 10.1.4.1/24 (intnet-surgery2)
        |
   [Internal Networks]
        |
+-------+-------+-------+-------+
|       |       |       |       |
Bornem  Venue   Surg1   Surg2
10.1.1.2 10.1.2.2 10.1.3.2 10.1.4.2
```

**Waarom deze opzet?**
- FusionHub ondersteunt maar 1 netwerkadapter → elke FusionHub op eigen Internal Network
- VyOS router als centrale gateway met NAT en port forwarding
- Host-only adapter met Windows ICS voor internet → stabiel IP ongeacht locatie
- Waarom geen NAT adapter? → VirtualBox NAT ondersteunt geen inbound port forwarding
- Waarom geen Bridged? → IP verandert per netwerk (thuis/school), onbetrouwbaar voor VPN

## Netwerk Configuratie

| VM | Internal Network | IP | Gateway | Admin URL |
|----|------------------|-----|---------|-----------|
| VyOS | Host-only | 192.168.137.10 | 192.168.137.1 | - |
| Bornem | intnet-bornem | 10.1.1.2 | 10.1.1.1 | https://192.168.137.10:8441 |
| Venue | intnet-venue | 10.1.2.2 | 10.1.2.1 | https://192.168.137.10:8442 |
| Surgery1 | intnet-surgery1 | 10.1.3.2 | 10.1.3.1 | https://192.168.137.10:8443 |
| Surgery2 | intnet-surgery2 | 10.1.4.2 | 10.1.4.1 | https://192.168.137.10:8444 |

DNS voor alle FusionHubs: 8.8.8.8

## Benodigdheden

- VirtualBox 7.0+
- VyOS ISO: https://vyos.net/get/nightly-builds/
- FusionHub OVA: https://www.peplink.com/products/fusionhub/
- 4x FusionHub evaluation licenses (aanvragen via InControl2)

## Setup Stappen

### 1. ICS Instellen (Windows Internet Connection Sharing)

1. VirtualBox → File → Tools → Network Manager → maak Host-Only adapter aan
2. DHCP uitzetten voor deze adapter
3. Windows `ncpa.cpl` → rechtsklik je internet adapter → Properties → Sharing
4. Vink aan "Allow other network users..." → selecteer de Host-Only adapter → OK
5. Host-Only adapter krijgt automatisch IP 192.168.137.1

**Wat is ICS?**
*Windows ICS staat voor Internet Connection Sharing, een ingebouwde Windows-functie waarmee één computer met een internetverbinding deze kan delen met andere apparaten op een lokaal netwerk (LAN), zodat ze ook online kunnen gaan, vaak zonder dat een aparte router nodig is* --- Google Gemini

### 2. VyOS Router VM

**Download:** VyOS ISO van https://vyos.net/get/nightly-builds/

**VM aanmaken:** Linux/Debian 64-bit, 512MB RAM, 2GB disk

**Netwerk configureren** (5 adapters nodig, standaard toont VirtualBox er maar 4):
```cmd
VBoxManage modifyvm "VyOS-Router" --nic1 hostonly --hostonlyadapter1 "VirtualBox Host-Only Ethernet Adapter #6"
VBoxManage modifyvm "VyOS-Router" --nic2 intnet --intnet2 "intnet-bornem"
VBoxManage modifyvm "VyOS-Router" --nic3 intnet --intnet3 "intnet-venue"
VBoxManage modifyvm "VyOS-Router" --nic4 intnet --intnet4 "intnet-surgery1"
VBoxManage modifyvm "VyOS-Router" --nic5 intnet --intnet5 "intnet-surgery2"
```

**Installatie:** Boot ISO, login `vyos`/`vyos`, run `install image`, reboot, unmount ISO

**VyOS configuratie:**
```bash
configure

# WAN
set interfaces ethernet eth0 address 192.168.137.10/24
set interfaces ethernet eth0 description 'WAN'
set protocols static route 0.0.0.0/0 next-hop 192.168.137.1
set system name-server 8.8.8.8

# LANs
set interfaces ethernet eth1 address 10.1.1.1/24
set interfaces ethernet eth1 description 'Bornem'
set interfaces ethernet eth2 address 10.1.2.1/24
set interfaces ethernet eth2 description 'Venue'
set interfaces ethernet eth3 address 10.1.3.1/24
set interfaces ethernet eth3 description 'Surgery1'
set interfaces ethernet eth4 address 10.1.4.1/24
set interfaces ethernet eth4 description 'Surgery2'

# NAT voor internet
set nat source rule 100 outbound-interface name 'eth0'
set nat source rule 100 source address '10.1.0.0/16'
set nat source rule 100 translation address masquerade

# Port forwards voor admin panels
set nat destination rule 10 destination port '8441'
set nat destination rule 10 inbound-interface name 'eth0'
set nat destination rule 10 protocol 'tcp'
set nat destination rule 10 translation address '10.1.1.2'
set nat destination rule 10 translation port '443'

set nat destination rule 20 destination port '8442'
set nat destination rule 20 inbound-interface name 'eth0'
set nat destination rule 20 protocol 'tcp'
set nat destination rule 20 translation address '10.1.2.2'
set nat destination rule 20 translation port '443'

set nat destination rule 30 destination port '8443'
set nat destination rule 30 inbound-interface name 'eth0'
set nat destination rule 30 protocol 'tcp'
set nat destination rule 30 translation address '10.1.3.2'
set nat destination rule 30 translation port '443'

set nat destination rule 40 destination port '8444'
set nat destination rule 40 inbound-interface name 'eth0'
set nat destination rule 40 protocol 'tcp'
set nat destination rule 40 translation address '10.1.4.2'
set nat destination rule 40 translation port '443'

commit
save
```

### 3. FusionHub VMs

**Download:** FusionHub OVA van https://www.peplink.com/products/fusionhub/

**Stappen:**
1. Importeer OVA in VirtualBox → dit wordt je "clean" base VM
2. Full clone deze VM 4x en hernoem naar: Bornem, Venue, Surgery1, Surgery2
3. Configureer netwerk per VM:
```cmd
VBoxManage modifyvm "Bornem" --nic1 intnet --intnet1 "intnet-bornem"
VBoxManage modifyvm "Venue" --nic1 intnet --intnet1 "intnet-venue"
VBoxManage modifyvm "Surgery1" --nic1 intnet --intnet1 "intnet-surgery1"
VBoxManage modifyvm "Surgery2" --nic1 intnet --intnet1 "intnet-surgery2"
```

4. Start elke VM, typ `setup` op console, configureer netwerk:
   - Bornem: IP 10.1.1.2, Subnetmask 255.255.255.0, Gateway 10.1.1.1, DNS 8.8.8.8
   - Venue: IP 10.1.2.2, Subnetmask 255.255.255.0 Gateway 10.1.2.1, DNS 8.8.8.8
   - Surgery1: IP 10.1.3.2, Subnetmask 255.255.255.0 Gateway 10.1.3.1, DNS 8.8.8.8
   - Surgery2: IP 10.1.4.2, Subnetmask 255.255.255.0 Gateway 10.1.4.1, DNS 8.8.8.8

### 4. Admin Panel en Licensing

**Toegang:** Via browser naar de admin URLs (zie tabel hierboven), bijv. https://192.168.137.10:8441 voor Bornem. Accepteer het self-signed certificaat.

**Licensing:** 
- Het admin panel toont enkel de License pagina totdat een geldige license is ingevoerd
- Vraag evaluation licenses aan via InControl2 (https://incontrol2.peplink.com), je kan er zo 10 aanvragen die telkens een maand geldig zijn, dit is ruim voldoende voor de test setup
- Na license activatie zijn alle menu-opties beschikbaar

### 5. InControl2

- Login op https://incontrol2.peplink.com
- Maak Organization en Group aan
- Voeg devices toe via serial number (te vinden op admin panel)
- **Device namen in InControl2:** Bornem, Venue, Surgery1, Surgery2

## Troubleshooting

**License toont "Expired 1970-01-01" maar device is online in InControl2:**
→ NTP tijd sync mislukt. Reboot het device via InControl2 tools, tijd synchroniseert daarna automatisch.

**Geen internet na locatiewissel of PC reboot:**
→ Windows ICS reset zichzelf. Opnieuw instellen via ncpa.cpl (sharing uitzetten en weer aanzetten).

**Werkt niet via eduroam (schoolnetwerk):**
→ Eduroam blokkeert bepaalde poorten. Gebruik thuisnetwerk of mobiele hotspot (4G/5G).