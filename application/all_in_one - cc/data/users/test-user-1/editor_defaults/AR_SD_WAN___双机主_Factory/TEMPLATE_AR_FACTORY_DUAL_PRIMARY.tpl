ip vpn-instance underlay_internetA

ipv4-family

quit

ip vpn-instance underlay_ipsecA

ipv4-family

quit

ip vpn-instance underlay_main

ipv4-family

quit

interface {dj_wan1_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetA

ip address {dj_wan1_ip_addr} {dj_wan1_mask}

tcp adjust-mss 1200

interface {dj_zihuan1_port}

undo portswitch

interface {dj_zihuan1_port}.98

interface {dj_zihuan1_port}.100

interface {dj_ipsec1_port}

undo portswitch

interface {dj_ipsec1_port}.98

interface Tunnel0/0/1000

ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {dj_wan1_gw}

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

ftp 59.36.7.222  vpn-instance underlay_internetA

ops install file {lineid_fn}main.py

ops install file ipsecmain.py

system-view

ops

 script-assistant python {lineid_fn}main.py

 script-assistant python ipsecmain.py

ip route-static vpn-instance underlay_internetA {south_primary} 255.255.255.255 {dj_wan1_gw} tag 4400 description agile-controller

agile controller host {south_primary} port 10020 vpn-instance underlay_internetA
quit

set factory-configuration from current-configuration

y

save

Y
