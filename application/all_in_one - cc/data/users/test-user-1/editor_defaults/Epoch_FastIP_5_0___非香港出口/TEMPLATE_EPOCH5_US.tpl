# ==========================================================
# Epoch 5.0 非香港出口配置  Hostname: {hostname}
# 主ACVPN GRE  {main_acvpn_gre_tun}  PE:{main_acvpn_gre_pe}
#   WANIP:{main_acvpn_gre_wanip}  PE侧:{main_acvpn_gre_pe_ip}  CE侧:{main_acvpn_gre_ce_ip}
#   GRE remote:{main_acvpn_gre_remote}
# 主ACVPN vtun  {main_acvpn_vtun_id}(port:{main_acvpn_vtun_port})  PE:{main_acvpn_vtun_pe}
#   local:{main_acvpn_vtun_local}  remote:{main_acvpn_vtun_remote}  docking:{main_acvpn_vtun_docking}
# 主非香港出口  {main_us_tun}  PE:{main_us_pe}
#   WANIP:{main_us_wanip}  PE侧:{main_us_pe_ip}  CE侧:{main_us_gre_ce_ip}
#   PE docking:{main_us_pe_docking}  NAT IP(FakeIP):{main_us_nat_ip_all}
#   BGP: {main_us_bgp1}, {main_us_bgp2}
# 备ACVPN GRE  {bk_acvpn_gre_tun}  PE:{bk_acvpn_gre_pe}
#   WANIP:{bk_acvpn_gre_wanip}  PE侧:{bk_acvpn_gre_pe_ip}  CE侧:{bk_acvpn_gre_ce_ip}
#   GRE remote:{bk_acvpn_gre_remote}
# 备ACVPN vtun  {bk_acvpn_vtun_id}(port:{bk_acvpn_vtun_port})  PE:{bk_acvpn_vtun_pe}
#   local:{bk_acvpn_vtun_local}  remote:{bk_acvpn_vtun_remote}  docking:{bk_acvpn_vtun_docking}
# 备非香港出口  {bk_us_tun}  PE:{bk_us_pe}
#   WANIP:{bk_us_wanip}  PE侧:{bk_us_pe_ip}  CE侧:{bk_us_gre_ce_ip}
#   PE docking:{bk_us_pe_docking}  NAT IP(FakeIP):{bk_us_nat_ip_all}
#   BGP: {bk_us_bgp1}, {bk_us_bgp2}
# ------------------------------------------------------------------
# BGP更新源(主): {main_us_nat_ip}  BGP更新源(备): {bk_us_nat_ip}
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

# 隧道 MSS 调整
{fw_options_block}

# 设备 hostname
set system host-name '{hostname}'

# SSH 端口
set service ssh disable-host-validation
set service ssh port '2707'

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

# Dummy 接口
set interfaces dummy dum0 address '{ce_docking}/32'
set interfaces dummy dum0 description 'CE Docking'
set interfaces dummy dum100 address '{main_us_nat_ip}/32'
set interfaces dummy dum100 description '{main_us_dum100_desc}'
{extra_dum_main_block}
set interfaces dummy dum200 address '{bk_us_nat_ip}/32'
set interfaces dummy dum200 description '{bk_us_dum200_desc}'
{extra_dum_bk_block}

# 隧道配置

# OpenVPN 共享密钥
{pki_block}

# 主 ACVPN OpenVPN
set interfaces openvpn {main_acvpn_vtun_id} description 'MAIN {main_acvpn_vtun_pe} {main_acvpn_vtun_id}'
set interfaces openvpn {main_acvpn_vtun_id} local-address {main_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'nobind'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'fragment 1300'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'providers legacy default'
set interfaces openvpn {main_acvpn_vtun_id} persistent-tunnel
set interfaces openvpn {main_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {main_acvpn_vtun_id} remote-address '{main_acvpn_vtun_remote}'
set interfaces openvpn {main_acvpn_vtun_id} remote-host '{main_acvpn_vtun_docking}'
set interfaces openvpn {main_acvpn_vtun_id} remote-port '{main_acvpn_vtun_port}'
set interfaces openvpn {main_acvpn_vtun_id} shared-secret-key 'openvpn_secret'

# 主 ACVPN GRE 隧道
set interfaces tunnel {main_acvpn_gre_tun} address '{main_acvpn_gre_ce_ip}/30'
set interfaces tunnel {main_acvpn_gre_tun} description 'MAIN {main_acvpn_gre_pe}'
set interfaces tunnel {main_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {main_acvpn_gre_tun} ip adjust-mss '1300'
set interfaces tunnel {main_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {main_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {main_acvpn_gre_tun} remote '{main_acvpn_gre_remote}'
set interfaces tunnel {main_acvpn_gre_tun} source-address '{main_acvpn_vtun_local}'

# 主 US 隧道
set interfaces tunnel {main_us_tun} address '{main_us_gre_ce_ip}/30'
set interfaces tunnel {main_us_tun} description 'MAIN {main_us_pe}'
set interfaces tunnel {main_us_tun} encapsulation 'gre'
set interfaces tunnel {main_us_tun} ip adjust-mss '1300'
set interfaces tunnel {main_us_tun} mtu '1452'
set interfaces tunnel {main_us_tun} parameters ip ttl '255'
set interfaces tunnel {main_us_tun} remote '{main_us_pe_docking}'
set interfaces tunnel {main_us_tun} source-address '{ce_docking}'

# 备 ACVPN OpenVPN
set interfaces openvpn {bk_acvpn_vtun_id} description 'BK {bk_acvpn_vtun_pe} {bk_acvpn_vtun_id}'
set interfaces openvpn {bk_acvpn_vtun_id} local-address {bk_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'nobind'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'fragment 1300'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'providers legacy default'
set interfaces openvpn {bk_acvpn_vtun_id} persistent-tunnel
set interfaces openvpn {bk_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {bk_acvpn_vtun_id} remote-address '{bk_acvpn_vtun_remote}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-host '{bk_acvpn_vtun_docking}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-port '{bk_acvpn_vtun_port}'
set interfaces openvpn {bk_acvpn_vtun_id} shared-secret-key 'openvpn_secret'

# 备 ACVPN GRE 隧道
set interfaces tunnel {bk_acvpn_gre_tun} address '{bk_acvpn_gre_ce_ip}/30'
set interfaces tunnel {bk_acvpn_gre_tun} description 'BK {bk_acvpn_gre_pe}'
set interfaces tunnel {bk_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {bk_acvpn_gre_tun} ip adjust-mss '1300'
set interfaces tunnel {bk_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {bk_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {bk_acvpn_gre_tun} remote '{bk_acvpn_gre_remote}'
set interfaces tunnel {bk_acvpn_gre_tun} source-address '{bk_acvpn_vtun_local}'

# 备 US 隧道
set interfaces tunnel {bk_us_tun} address '{bk_us_gre_ce_ip}/30'
set interfaces tunnel {bk_us_tun} description 'BK {bk_us_pe}'
set interfaces tunnel {bk_us_tun} encapsulation 'gre'
set interfaces tunnel {bk_us_tun} ip adjust-mss '1300'
set interfaces tunnel {bk_us_tun} mtu '1452'
set interfaces tunnel {bk_us_tun} parameters ip ttl '255'
set interfaces tunnel {bk_us_tun} remote '{bk_us_pe_docking}'
set interfaces tunnel {bk_us_tun} source-address '{ce_docking}'

# NAT 配置
{lan_net_block}
set nat source rule 50 outbound-interface name '{wan_if}'
set nat source rule 50 source group network-group 'LAN-NET'
set nat source rule 50 translation address 'masquerade'
{overseas_nat_block}

# DNS-NET 地址组（配合 DNS 进程使用）
set firewall group address-group DNS-NET address {dns_ip1}
set firewall group address-group DNS-NET address {dns_ip2}
set nat source rule 5000 destination group address-group DNS-NET
set nat source rule 5000 outbound-interface name '{main_us_tun}'
set nat source rule 5000 translation address '{main_us_nat_ip}'
set nat source rule 6000 destination group address-group DNS-NET
set nat source rule 6000 outbound-interface name '{bk_us_tun}'
set nat source rule 6000 translation address '{bk_us_nat_ip}'

# BGP Server 路由
{us_bgp_routes}

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

set policy route-map bgp-from--RSVR rule 100 action 'permit'
set policy route-map bgp-from--RSVR rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR rule 100 set ip-next-hop '{main_us_pe_ip}'
set policy route-map bgp-from--RSVR rule 100 set local-preference '200'
set policy route-map bgp-from--RSVR rule 200 action 'permit'
set policy route-map bgp-from--RSVR rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 200 set local-preference '200'
set policy route-map bgp-from--RSVR rule 300 action 'permit'
set policy route-map bgp-from--RSVR rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 300 set local-preference '200'
set policy route-map bgp-from--RSVR rule 400 action 'permit'
set policy route-map bgp-from--RSVR rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 400 set local-preference '200'
set policy route-map bgp-from--RSVR2 rule 100 action 'permit'
set policy route-map bgp-from--RSVR2 rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR2 rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR2 rule 100 set ip-next-hop '{bk_us_pe_ip}'
set policy route-map bgp-from--RSVR2 rule 100 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 200 action 'permit'
set policy route-map bgp-from--RSVR2 rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR2 rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR2 rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 200 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 300 action 'permit'
set policy route-map bgp-from--RSVR2 rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR2 rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR2 rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 300 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 400 action 'permit'
set policy route-map bgp-from--RSVR2 rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR2 rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR2 rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 400 set local-preference '50'

set policy route-map deny-any-out rule 1000 action 'deny'
set policy route-map deny-any-out rule 1000 description 'to_bgpserver'

set protocols bgp neighbor {main_us_bgp1} peer-group 'RSVR'
set protocols bgp neighbor {main_us_bgp2} peer-group 'RSVR'
set protocols bgp neighbor {bk_us_bgp1} peer-group 'RSVR2'
set protocols bgp neighbor {bk_us_bgp2} peer-group 'RSVR2'
set protocols bgp parameters router-id '{main_us_nat_ip}'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR remote-as '65000'
set protocols bgp peer-group RSVR update-source '{main_us_nat_ip}'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR2 remote-as '65000'
set protocols bgp peer-group RSVR2 update-source '{bk_us_nat_ip}'
set protocols bgp system-as '65000'
set protocols bgp timers holdtime '15'
set protocols bgp timers keepalive '5'

# 基本路由配置
{default_route_block}

# 主线监控
set protocols static route 114.113.245.99/32 next-hop {main_acvpn_gre_pe_ip}

# 备线监控
set protocols static route 114.113.245.100/32 next-hop {bk_acvpn_gre_pe_ip}

# 跳板机路由 & Track 配置（failover2 替代 track）
set protocols failover2 track tomain source-address '{main_acvpn_gre_ce_ip}'
set protocols failover2 track tomain target '{main_acvpn_gre_pe_ip}'
set protocols failover2 track tomain type 'icmp'
set protocols failover2 route 192.168.55.250/32 next-hop {main_acvpn_gre_pe_ip} track 'tomain'
set protocols static route 192.168.55.250/32 next-hop {bk_acvpn_gre_pe_ip} distance '10'

# 静态路由（隧道路由）
set protocols static route {main_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {bk_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {main_us_pe_docking}/32 next-hop {main_acvpn_gre_pe_ip}
set protocols static route {bk_us_pe_docking}/32 next-hop {bk_acvpn_gre_pe_ip}
set protocols static route {main_acvpn_gre_remote}/32 next-hop {main_acvpn_vtun_remote}
set protocols static route {bk_acvpn_gre_remote}/32 next-hop {bk_acvpn_vtun_remote}

# 本地策略路由（US 出口源地址分流）
set policy local-route rule 1001 set table '101'
set policy local-route rule 1001 source address '{main_us_gre_ce_ip}'
set protocols static table 101 route 0.0.0.0/0 next-hop {main_us_pe_ip}
set policy local-route rule 1002 set table '102'
set policy local-route rule 1002 source address '{bk_us_gre_ce_ip}'
set protocols static table 102 route 0.0.0.0/0 next-hop {bk_us_pe_ip}

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