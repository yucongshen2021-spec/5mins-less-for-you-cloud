interface Tunnel{USG_FL_MAIN_TUN_DEFAULT}
 description Main-{main_pe}-{main_line_id}
 ip address {main_wanip2} 255.255.255.252
 mtu 1300
 tunnel-protocol gre
 source LoopBack10
 destination {main_peer_ip}
 service-manage all permit

interface Tunnel{USG_FL_BK_TUN_DEFAULT}
 description BK-{backup_pe}-{backup_line_id}
 ip address {backup_wanip2} 255.255.255.252
 mtu 1300
 tunnel-protocol gre
 source LoopBack11
 destination {backup_peer_ip}
 service-manage all permit

nqa test-instance admin FLmain
 test-type icmp
 destination-address ipv4 {main_wanip1}
 source-address ipv4 {main_wanip2}
 send-trap probefailure
 send-trap testfailure
 test-failtimes 2
 probe-count 4
 frequency 30
 start now
q

firewall zone untrust
 add interface Tunnel{USG_FL_MAIN_TUN_DEFAULT}
 add interface Tunnel{USG_FL_BK_TUN_DEFAULT}

ip address-set flink type object
 address 0 {reserved1_net} mask {reserved1_mask}
 address 1 {reserved2_net} mask {reserved2_mask}
 address 2 {reserved3_net} mask {reserved3_mask}

ip route-static {reserved1_net} {reserved1_mask} {main_wanip1} track nqa admin FLmain
ip route-static {reserved2_net} {reserved2_mask} {main_wanip1} track nqa admin FLmain
ip route-static {reserved3_net} {reserved3_mask} {main_wanip1} track nqa admin FLmain

ip route-static {reserved1_net} {reserved1_mask} {backup_wanip1} preference 100
ip route-static {reserved2_net} {reserved2_mask} {backup_wanip1} preference 100
ip route-static {reserved3_net} {reserved3_mask} {backup_wanip1} preference 100
