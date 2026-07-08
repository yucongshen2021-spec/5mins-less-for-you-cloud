ip vpn-instance underlay_internet

ipv4-family

quit

ip vpn-instance underlay_ipsec

ipv4-family

quit

ip vpn-instance underlay_main

ipv4-family

quit

ip vpn-instance underlay_backup

ipv4-family

quit

interface {wan1_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internet

ip address {wan1_ip_addr} {wan1_mask}

tcp adjust-mss 1200

interface {zihuan_port}

undo portswitch

interface {zihuan_port}.98

interface {zihuan_port}.100

interface {zihuan_port}.200

interface {ipsec_port}

undo portswitch

interface {ipsec_port}.98

interface Tunnel0/0/1000

interface Tunnel0/0/1001

ip route-static vpn-instance underlay_internet 0.0.0.0 0.0.0.0 {wan1_gw}

aaa

 local-user admin service-type terminal ssh http
y

 quit

ssh server permit interface all

stelnet server enable

user-interface vty 0

 protocol inbound ssh

user-interface vty 1 4

 authentication-mode aaa

ftp 59.36.7.222  vpn-instance underlay_internet

ops install file {lineid_fn}.py

ops install file ipsecmain.py

ops install file ipsecbackup.py

system-view

ops

 script-assistant python {lineid_fn}.py

 script-assistant python ipsecmain.py

 script-assistant python ipsecbackup.py

ip route-static vpn-instance underlay_internet {south_primary} 255.255.255.255 {wan1_gw} tag 4400 description agile-controller

agile controller host {south_primary} port 10020 vpn-instance underlay_internet
quit

ip route-static vpn-instance underlay_internet {south_backup} 255.255.255.255 {wan1_gw} tag 4400 description agile-controller

agile controller host {south_backup} port 10020 vpn-instance underlay_internet
quit

set factory-configuration from current-configuration

y

save

Y
