#
sysname {hostname}
#
clock timezone bj add 08:00
#
ntp-service unicast-server 192.168.55.250
#
acl number 2707
 rule 10 permit source 192.168.0.0 0.0.0.255
 rule 20 permit source 172.16.0.0 0.15.255.255
 rule 30 permit source 10.0.0.0 0.255.255.255
 rule 40 permit source 114.112.238.8 0.0.0.7
 rule 50 permit source 192.168.55.250 0
 rule 60 permit source 113.105.190.147 0
 rule 70 permit source 202.104.174.178 0
 rule 80 permit source 120.76.31.146 0
 rule 90 permit source 59.37.126.140 0
 rule 100 permit source 183.61.239.168 0
#
acl number 3333
 rule 1 permit ip source {main_loop_ip} 0 destination {main_pe_docking} 0
acl number 3334
 rule 1 permit ip source {backup_loop_ip} 0 destination {backup_pe_docking} 0
#
ike proposal 10
 encryption-algorithm 3des
 dh group2
 authentication-algorithm sha1
 sa duration 28800
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
#
ipsec proposal ipsectran1
 esp authentication-algorithm sha1
 esp encryption-algorithm 3des
#
ike peer main
 version 1
 undo version 2
 pre-shared-key cipher {main_psk}
 ike-proposal 10
 dpd idle-time 10
 dpd type on-demand
 dpd retransmit-interval 2
 remote-address {main_dial_ip}
#
ike peer backup
 version 1
 undo version 2
 pre-shared-key cipher {backup_psk}
 ike-proposal 10
 dpd idle-time 10
 dpd type on-demand
 dpd retransmit-interval 2
 remote-address {backup_dial_ip}
#
ipsec policy S2S-IPSEC 10 isakmp
 security acl 3333
 pfs dh-group2
 ike-peer main
 proposal ipsectran1
ipsec policy S2S-IPSEC 20 isakmp
 security acl 3334
 pfs dh-group2
 ike-peer backup
 proposal ipsectran1
#
interface LoopBack1000
 description To IPSec main
 ip address {main_loop_ip} 255.255.255.255
#
interface LoopBack2000
 description To IPSec backup
 ip address {backup_loop_ip} 255.255.255.255
#
interface Tunnel0/0/1000
 description 'pri to {main_pe} {main_tunnel}'
 ip address {main_tunnel_local_ip} 255.255.255.252
 tunnel-protocol gre
 source LoopBack1000
 destination {main_pe_docking}
 mtu 1476
 tcp adjust-mss 1300
#
interface Tunnel0/0/2000
 description 'back to {backup_pe} {backup_tunnel}'
 ip address {backup_tunnel_local_ip} 255.255.255.252
 tunnel-protocol gre
 source LoopBack2000
 destination {backup_pe_docking}
 mtu 1476
 tcp adjust-mss 1300
#
{lan_if_block}
{wan_if_block}
#
nqa event 1 log
nqa test-instance admin ipsecmain
 test-type icmp
 destination-address ipv4 {main_tunnel_remote_ip}
 source-address ipv4 {main_tunnel_local_ip}
 frequency 15
 probe-count 2
 alarm 1 lost-packet-ratio absolute rising-threshold 100 1
 start now
nqa test-instance admin ipsecbackup
 test-type icmp
 destination-address ipv4 {backup_tunnel_remote_ip}
 source-address ipv4 {backup_tunnel_local_ip}
 frequency 15
 probe-count 2
 alarm 1 lost-packet-ratio absolute rising-threshold 100 1
 start now
#
{static_routes_block}
{return_routes_block}
#
{bgp_filter_prefix_block}
#
route-policy bgp-To--VPN-Redistribute-Static deny node 100
 description Deny Redistribution of Static Routes to MPLS VPN
 if-match tag 7777
#
route-policy bgp-To--VPN-Redistribute-Static permit node 200
 if-match tag 8888
 apply community {ce_as}:100
#
route-policy bgp-To--VPN-Redistribute-Static permit node 300
 description Redistribute All Other Static Routes Without Tag
#
route-policy bgp-route-policy-pri-import permit node 100
 apply local-preference 200
#
route-policy bgp-route-policy-back-import permit node 100
 apply local-preference 50
#
bgp {ce_as}
 router-id {bgp_router_id}
 timer keepalive 5 hold 15
 peer {peer_main_ip} as-number {peer_main_as}
 peer {peer_backup_ip} as-number {peer_backup_as}
 #
 ipv4-family unicast
  undo synchronization
  preference 70 200 200
  filter-policy ip-prefix bgp-filte-pre-export export
  import-route direct
  import-route static route-policy bgp-To--VPN-Redistribute-Static
  peer {peer_main_ip} enable
  peer {peer_main_ip} ip-prefix bgp-filte-pre-export export
  peer {peer_main_ip} route-policy bgp-route-policy-pri-import import
  peer {peer_main_ip} advertise-community
  peer {peer_backup_ip} enable
  peer {peer_backup_ip} ip-prefix bgp-filte-pre-export export
  peer {peer_backup_ip} route-policy bgp-route-policy-back-import import
  peer {peer_backup_ip} advertise-community
#
snmp-agent trap enable
snmp-agent sys-info version all
snmp-agent community read both-win
#
info-center filter-id bymodule-alias NTP PACKET_LENGTH_WRONG
info-center source default channel 2 log level warning
info-center loghost 192.168.237.78
info-center logbuffer size 256
info-center timestamp log date precision-time millisecond
info-center timestamp trap date precision-time millisecond
#
stelnet server enable
ssh server port 2707
ssh server permit interface all
#
user-interface vty 0 4
 acl 2707 inbound
 authentication-mode aaa
 user privilege level 15
#
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server source-ip {main_tunnel_local_ip}
 hwtacacs-server shared-key cipher both-win
#
aaa
 local-user bothwin password irreversible-cipher Tfe28@w%
 local-user bothwin privilege level 15
 local-user bothwin service-type terminal ssh http
 local-user admin service-type terminal ssh http
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 15 hwtacacs local
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
  accounting start-fail online
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 service-scheme fnet_tac
  admin-user privilege level 15
 domain fnet_tac
  authentication-scheme fnet_tac
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  hwtacacs-server fnetlink_tacacs
 domain fnet_tac admin
#
ftp 59.36.7.222
 cd mplstools
 get mplsmain.py
 get mplsbackup.py
 ops install file mplsmain.py
 ops install file mplsbackup.py
#
ops
 script-assistant python mplsmain.py
 script-assistant python mplsbackup.py
 environment mainip {main_dial_ip}
 environment backupip {backup_dial_ip}
#
return
