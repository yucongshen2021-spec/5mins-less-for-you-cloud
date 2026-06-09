#
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server source-ip {main_wan_ip_plain}
 hwtacacs-server shared-key cipher both-win
#
acl number 2707
{acl_inner_rules_block}
#
{ipsec_acl_main_block}
{ipsec_acl_backup_block}
#
ipsec proposal ipsectran1
 esp authentication-algorithm sha1
 esp encryption-algorithm 3des
#
ike proposal default
 encryption-algorithm aes-256 aes-192 aes-128 aes-gcm-256 aes-gcm-192 aes-gcm-128
 dh group14
 authentication-algorithm sha2-512 sha2-384 sha2-256
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
ike proposal 10
 encryption-algorithm aes-128
 dh group2
 authentication-algorithm sha1
 sa duration 28800
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
#
{ike_peer_main_block}
{ike_peer_backup_block}
#
{ipsec_policy_block}
#
aaa
 authentication-scheme default
  authentication-mode local
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authentication-scheme radius
  authentication-mode radius
 authorization-scheme default
  authorization-mode local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 15 hwtacacs local
 accounting-scheme default
  accounting-mode none
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
  accounting start-fail online
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
 service-scheme fnet_tac
  admin-user privilege level 15
 domain default
  authentication-scheme default
  accounting-scheme default
  radius-server default
 domain default_admin
  authentication-scheme default
  accounting-scheme default
 domain fnet_tac
  authentication-scheme fnet_tac
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  radius-server default
  hwtacacs-server fnetlink_tacacs
 local-user admin password irreversible-cipher Tfe28@w%
 local-user admin privilege level 15
 local-user admin service-type terminal ssh http
 local-user bothwin password irreversible-cipher Tfe28@w%
 local-user bothwin privilege level 15
 local-user bothwin service-type terminal ssh http
#
{lan_if_block}
{wan_if_block}
#
interface GigabitEthernet0/0/10
 description VirtualPort
#
interface Cellular0/0/0
#
interface NULL0
#
{loopback_main_block}
{loopback_backup_block}
#
{tunnel_main_block}
{tunnel_backup_block}
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
{bgp_networks_block}
  import-route direct
  import-route static route-policy bgp-To--VPN-Redistribute-Static
  peer {peer_main_ip} enable
  peer {peer_main_ip} route-policy bgp-route-policy-back-import import
  peer {peer_main_ip} route-policy bgp-route-policy-pri-export export
  peer {peer_main_ip} advertise-community
  peer {peer_main_ip} route-update-interval 10
  peer {peer_backup_ip} enable
  peer {peer_backup_ip} route-policy bgp-route-policy-pri-import import
  peer {peer_backup_ip} route-policy bgp-route-policy-back-export export
  peer {peer_backup_ip} advertise-community
  peer {peer_backup_ip} route-update-interval 10
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
route-policy bgp-route-policy-pri-export permit node 100
 if-match ip-prefix bgp-filte-pre-export
#
route-policy bgp-route-policy-pri-export deny node 999
#
route-policy bgp-route-policy-back-export permit node 100
 if-match ip-prefix bgp-filte-pre-export
#
route-policy bgp-route-policy-back-export deny node 999
#
 stelnet server enable
 ssh server port 2707
 ssh server permit interface all
#
 http secure-server ssl-policy default_policy
 http secure-server enable
 http server permit interface GigabitEthernet0/0/0
#
nqa event 1 log
#
{bgp_filter_prefix_block}
ip ip-prefix deny index 10 deny 0.0.0.0 0
ip ip-prefix BGP-permit-ex index 10 permit 173.15.50.0 24 greater-equal 24 less-equal 24
#
{static_routes_block}
{return_routes_block}
