ip vpn-instance underlay_internetB

ipv4-family

quit

ip vpn-instance underlay_ipsecB

ipv4-family

quit

ip vpn-instance underlay_backup

ipv4-family

quit

interface {dj_wan2_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetB

ip address {dj_wan2_ip_addr} {dj_wan2_mask}

tcp adjust-mss 1200

interface {dj_zihuan2_port}

undo portswitch

interface {dj_zihuan2_port}.99

interface {dj_zihuan2_port}.200

interface {dj_ipsec2_port}

undo portswitch

interface {dj_ipsec2_port}.99

interface Tunnel0/0/1001

ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {dj_wan2_gw}

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

ftp 59.36.7.222  vpn-instance underlay_internetB

ops install file {lineid_fn}backup.py

ops install file ipsecbackup.py

system-view

ops

 script-assistant python {lineid_fn}backup.py

 script-assistant python ipsecbackup.py

ip route-static vpn-instance underlay_internetB {south_backup} 255.255.255.255 {dj_wan2_gw} tag 4400 description agile-controller

agile controller host {south_backup} port 10020 vpn-instance underlay_internetB
quit

set factory-configuration from current-configuration

y

save

Y
