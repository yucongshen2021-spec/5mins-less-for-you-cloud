interface Tunnel{USG_NE_MAIN_TUN_DEFAULT}
 description Main-{main_pe}-{main_line_id}
 ip address {main_wanip2} 255.255.255.252
 mtu 1300
 tunnel-protocol gre
 source LoopBack10
 destination {main_peer_ip}
 service-manage all permit

interface Tunnel{USG_NE_BK_TUN_DEFAULT}
 description Backup-{backup_pe}-{backup_line_id}
 ip address {backup_wanip2} 255.255.255.252
 mtu 1300
 tunnel-protocol gre
 source LoopBack11
 destination {backup_peer_ip}
 service-manage all permit

firewall zone untrust
 add interface Tunnel{USG_NE_MAIN_TUN_DEFAULT}
 add interface Tunnel{USG_NE_BK_TUN_DEFAULT}

{USG_NE_MAIN_LOOPBACK_BLOCK}
{USG_NE_BK_LOOPBACK_BLOCK}

{USG_NE_MAIN_NAT_GROUP_BLOCK}
{USG_NE_BK_NAT_GROUP_BLOCK}

{USG_NE_MAIN_SNAT_BLOCK}
{USG_NE_BK_SNAT_BLOCK}

nqa test-instance fastip {USG_NE_MAIN_NQA_DEFAULT}
 test-type icmp
 destination-address ipv4 {main_wanip1}
 probe-count 1
 frequency 5
 start now

nqa test-instance fastip {USG_NE_BK_NQA_DEFAULT}
 test-type icmp
 destination-address ipv4 {backup_wanip1}
 probe-count 1
 frequency 5
 start now
