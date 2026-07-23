# ==========================================================
# Epoch 5.0 HK 出口配置  Hostname: {hostname}
# 主线  PE:{main_pe}  TUNNEL:{main_tunnel}(port:{main_tunnel_port})
#       WANIP:{main_wanip}  PE侧:{main_wanip_remote}  CE侧:{main_wanip_local}
#       Docking:{main_docking}  HKIP:{hkip}  CELOIP:{ce_loip}
#       BGP: {main_bgp1}, {main_bgp2}
# 备线  PE:{bk_pe}  TUNNEL:{bk_tunnel}(port:{bk_tunnel_port})
#       WANIP:{bk_wanip}  PE侧:{bk_wanip_remote}  CE侧:{bk_wanip_local}
#       Docking:{bk_docking}  BGP: {bk_bgp1}, {bk_bgp2}
# ==========================================================

# 防火墙白名单网络组
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '100.64.0.0/10'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall group network-group GROUP-FNET-Whitelist network '127.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'

# 防火墙本机防护
set firewall ipv4 input filter default-action 'accept'
set firewall ipv4 input filter rule 100 action 'jump'
set firewall ipv4 input filter rule 100 jump-target 'WAN2LOCAL'
set firewall ipv4 name WAN2LOCAL default-action 'drop'
set firewall ipv4 name WAN2LOCAL rule 1000 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'established'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'related'
set firewall ipv4 name WAN2LOCAL rule 1010 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall ipv4 name WAN2LOCAL rule 1210 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1210 protocol 'gre'
set firewall ipv4 name WAN2LOCAL rule 1220 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1220 protocol 'ipip'
set firewall ipv4 name WAN2LOCAL rule 1230 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1230 protocol 'esp'

# 设备 hostname
set system host-name '{hostname}'

# SSH 端口
set service ssh disable-host-validation
set service ssh port '2707'
# SSH 限制源IP（固定规则 + WAN/LAN CIDR）
set service ssh acl permit '10.0.0.0/8'
set service ssh acl permit '100.64.0.0/10'
set service ssh acl permit '113.105.190.147/32'
set service ssh acl permit '114.112.238.8/29'
set service ssh acl permit '114.113.245.101/32'
set service ssh acl permit '120.76.31.146/32'
set service ssh acl permit '172.16.0.0/12'
set service ssh acl permit '183.61.239.168/32'
set service ssh acl permit '192.168.0.0/16'
set service ssh acl permit '192.168.55.250/32'
set service ssh acl permit '202.104.174.178/32'
set service ssh acl permit '59.37.126.140/32'
{ssh_acl_block}

# 登录账户
set system login user bothwin authentication plaintext-password 'Tfe28@w%'

# 基本配置
set service snmp community both-win authorization 'ro'

# NTP 配置
set service ntp server 192.168.55.250
set service ntp server 202.104.174.178
set system time-zone 'Asia/Hong_Kong'

# WAN 和 LAN 配置
set interfaces ethernet {wan_if} description WAN1
set interfaces ethernet {wan_if} address '{wan_cidr}'
{lan_if_block}

# BGP 更新源
set interfaces dummy dum0 address '{ce_loip}/32'
set interfaces dummy dum0 description 'bgp-update-source'

# NOC 路由下来的 HKIP 假 IP
set interfaces dummy dum1 address '{hkip}/32'
set interfaces dummy dum1 description 'HKIP'

# 隧道配置

# OpenVPN 共享密钥
{pki_block}

# 主 OpenVPN
set interfaces openvpn {main_tunnel} description '{main_pe_desc}'
set interfaces openvpn {main_tunnel} local-address {main_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_tunnel} mode 'site-to-site'
set interfaces openvpn {main_tunnel} openvpn-option 'nobind'
set interfaces openvpn {main_tunnel} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {main_tunnel} openvpn-option 'fragment 1300'
set interfaces openvpn {main_tunnel} openvpn-option 'providers legacy default'
set interfaces openvpn {main_tunnel} persistent-tunnel
set interfaces openvpn {main_tunnel} protocol 'udp'
set interfaces openvpn {main_tunnel} remote-address '{main_wanip_remote}'
set interfaces openvpn {main_tunnel} remote-host '{main_docking}'
set interfaces openvpn {main_tunnel} remote-port '{main_tunnel_port}'
set interfaces openvpn {main_tunnel} shared-secret-key 'openvpn_secret'
set interfaces openvpn {main_tunnel} ip adjust-mss 1300
set protocols static route {main_docking}/32 next-hop '{wan_gw}'

# 备 OpenVPN
set interfaces openvpn {bk_tunnel} description '{bk_pe_desc}'
set interfaces openvpn {bk_tunnel} local-address {bk_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_tunnel} mode 'site-to-site'
set interfaces openvpn {bk_tunnel} openvpn-option 'nobind'
set interfaces openvpn {bk_tunnel} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {bk_tunnel} openvpn-option 'fragment 1300'
set interfaces openvpn {bk_tunnel} openvpn-option 'providers legacy default'
set interfaces openvpn {bk_tunnel} persistent-tunnel
set interfaces openvpn {bk_tunnel} protocol 'udp'
set interfaces openvpn {bk_tunnel} remote-address '{bk_wanip_remote}'
set interfaces openvpn {bk_tunnel} remote-host '{bk_docking}'
set interfaces openvpn {bk_tunnel} remote-port '{bk_tunnel_port}'
set interfaces openvpn {bk_tunnel} shared-secret-key 'openvpn_secret'
set interfaces openvpn {bk_tunnel} ip adjust-mss 1300
{static_route_bk_docking}

# DNS 劫持配置
set nat destination rule 50 destination port '53'
set nat destination rule 50 inbound-interface name '{dns_hijack_if}'
set nat destination rule 50 protocol 'tcp_udp'
set nat destination rule 50 translation address '{lan_ip}'

# NAT 配置
{lan_net_block}
set nat source rule 50 outbound-interface name '{wan_if}'
set nat source rule 50 source group network-group 'LAN-NET'
set nat source rule 50 translation address 'masquerade'
set nat source rule 1000 outbound-interface name '{main_tunnel}'
set nat source rule 1000 source group network-group 'LAN-NET'
set nat source rule 1000 translation address '{hkip}'
set nat source rule 2000 outbound-interface name '{bk_tunnel}'
set nat source rule 2000 source group network-group 'LAN-NET'
set nat source rule 2000 translation address '{hkip}'

# DNS-NET 地址组（配合 DNS 进程使用）
set firewall group address-group DNS-NET address {dns_ip1}
set firewall group address-group DNS-NET address {dns_ip2}
set nat source rule 5000 destination group address-group DNS-NET
set nat source rule 5000 outbound-interface name '{main_tunnel}'
set nat source rule 5000 translation address '{hkip}'
set nat source rule 6000 destination group address-group DNS-NET
set nat source rule 6000 outbound-interface name '{bk_tunnel}'
set nat source rule 6000 translation address '{hkip}'

# BGP Server 路由
{bgp_server_routes_block}

# BGP 配置
set policy community-list 80 rule 10 action 'permit'
set policy community-list 80 rule 10 description 'to_hk'
set policy community-list 80 rule 10 regex '65000:9939'
set policy community-list 81 rule 10 action 'permit'
set policy community-list 81 rule 10 description 'to_ct'
set policy community-list 81 rule 10 regex '65000:4134'
set policy community-list 82 rule 10 action 'permit'
set policy community-list 82 rule 10 description 'to_cnc'
set policy community-list 82 rule 10 regex '65000:4837'
set policy community-list 83 rule 10 action 'permit'
set policy community-list 83 rule 10 description 'to_cn_other'
set policy community-list 83 rule 10 regex '65000:9808'
set policy community-list 85 rule 10 action 'permit'
set policy community-list 85 rule 10 description 'to_deny'
set policy community-list 85 rule 10 regex '65000:9807'
set policy community-list 88 rule 10 action 'permit'
set policy community-list 88 rule 10 description 'to_google'
set policy community-list 88 rule 10 regex '65000:9008'
set policy community-list 91 rule 10 action 'permit'
set policy community-list 91 rule 10 description 'to_Microsoft'
set policy community-list 91 rule 10 regex '65000:9009'

set policy route-map bgp-from--RSVR rule 80 action 'permit'
set policy route-map bgp-from--RSVR rule 80 match community community-list '80'
set policy route-map bgp-from--RSVR rule 80 set ip-next-hop '{main_wanip_remote}'
set policy route-map bgp-from--RSVR rule 80 set local-preference '200'
set policy route-map bgp-from--RSVR rule 81 action 'permit'
set policy route-map bgp-from--RSVR rule 81 match community community-list '81'
set policy route-map bgp-from--RSVR rule 81 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 81 set local-preference '200'
set policy route-map bgp-from--RSVR rule 82 action 'permit'
set policy route-map bgp-from--RSVR rule 82 match community community-list '82'
set policy route-map bgp-from--RSVR rule 82 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 82 set local-preference '200'
set policy route-map bgp-from--RSVR rule 83 action 'permit'
set policy route-map bgp-from--RSVR rule 83 match community community-list '83'
set policy route-map bgp-from--RSVR rule 83 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 83 set local-preference '200'
set policy route-map bgp-from--RSVR2 rule 80 action 'permit'
set policy route-map bgp-from--RSVR2 rule 80 match community community-list '80'
set policy route-map bgp-from--RSVR2 rule 80 set ip-next-hop '{bk_wanip_remote}'
set policy route-map bgp-from--RSVR2 rule 80 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 81 action 'permit'
set policy route-map bgp-from--RSVR2 rule 81 match community community-list '81'
set policy route-map bgp-from--RSVR2 rule 81 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 81 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 82 action 'permit'
set policy route-map bgp-from--RSVR2 rule 82 match community community-list '82'
set policy route-map bgp-from--RSVR2 rule 82 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 82 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 83 action 'permit'
set policy route-map bgp-from--RSVR2 rule 83 match community community-list '83'
set policy route-map bgp-from--RSVR2 rule 83 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 83 set local-preference '50'

set policy route-map deny-any-out rule 1000 action 'deny'
set policy route-map deny-any-out rule 1000 description 'to_bgpserver'

set protocols bgp neighbor {main_bgp1} peer-group 'RSVR'
set protocols bgp neighbor {main_bgp2} peer-group 'RSVR'
set protocols bgp neighbor {bk_bgp1} peer-group 'RSVR2'
set protocols bgp neighbor {bk_bgp2} peer-group 'RSVR2'
set protocols bgp parameters router-id '{ce_loip}'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR remote-as '65000'
set protocols bgp peer-group RSVR update-source '{ce_loip}'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR2 remote-as '65000'
set protocols bgp peer-group RSVR2 update-source '{ce_loip}'
set protocols bgp system-as '65000'
set protocols bgp timers holdtime '15'
set protocols bgp timers keepalive '5'

# 基本路由配置
{default_route_block}

# 主线监控
set protocols static route 114.113.245.99/32 next-hop {main_wanip_remote}

# 备线监控
set protocols static route 114.113.245.100/32 next-hop {bk_wanip_remote}

# 跳板机路由 & Track 配置
{track_block}

# 回程路由
{return_routes_block}

# DNS 配置
set service file-sync task 1 local '/config/user-data/cn.txt'
set service file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'
set service file-sync task 2 local '/config/user-data/oversea.txt'
set service file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'

set service dns forwarding allow-from '0.0.0.0/0'
set service dns forwarding cache-size '10000'
set service dns forwarding dnssec 'off'
set service dns forwarding domain-list CN file '/config/user-data/cn.txt'
set service dns forwarding domain-list CN name-server 223.5.5.5
set service dns forwarding domain-list CN name-server 223.6.6.6
set service dns forwarding domain-list CN recursion-desired
set service dns forwarding domain-list HK file '/config/user-data/oversea.txt'
set service dns forwarding domain-list HK name-server 8.8.4.4
set service dns forwarding domain-list HK name-server 8.8.8.8
set service dns forwarding domain-list HK recursion-desired
set service dns forwarding listen-address '0.0.0.0'
set service dns forwarding name-server 8.8.4.4
set service dns forwarding name-server 8.8.8.8

# DHCP 服务
{dhcp_block}