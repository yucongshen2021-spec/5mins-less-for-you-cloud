# ==========================================================
# er_mpls_v1 可视化模板  {config_type}配置  Hostname: {hostname}
# 主线  line_type:{main_line_type}  GRE:{main_gre_tun}  VTUN:{main_vtun_id}
#       GRE PE:{main_gre_pe}  WANIP:{main_gre_wanip}  PE侧:{main_gre_pe_ip}  CE侧:{main_gre_ce_ip}
#       VTUN PE:{main_vtun_pe} local:{main_vtun_local} remote:{main_vtun_remote} docking:{main_vtun_docking}
# 备线  line_type:{bk_line_type}  GRE:{bk_gre_tun}  VTUN:{bk_vtun_id}
#       GRE PE:{bk_gre_pe}  WANIP:{bk_gre_wanip}  PE侧:{bk_gre_pe_ip}  CE侧:{bk_gre_ce_ip}
#       VTUN PE:{bk_vtun_pe} local:{bk_vtun_local} remote:{bk_vtun_remote} docking:{bk_vtun_docking}
# CE AS:{ce_as}  主PE AS:{main_pe_as}  备PE AS:{bk_pe_as}
# ==========================================================
set firewall all-ping 'enable'
set firewall broadcast-ping 'disable'
set firewall config-trap 'disable'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.250/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.10/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.11/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '100.68.250.0/24'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall ipv6-receive-redirects 'disable'
set firewall ipv6-src-route 'disable'
set firewall ip-src-route 'disable'
set firewall log-martians 'enable'
set firewall name WAN2LOCAL default-action 'drop'
set firewall name WAN2LOCAL rule 1005 action 'accept'
set firewall name WAN2LOCAL rule 1005 state established 'enable'
set firewall name WAN2LOCAL rule 1005 state related 'enable'
set firewall name WAN2LOCAL rule 1010 action 'accept'
set firewall name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall name WAN2LOCAL rule 1210 action 'accept'
set firewall name WAN2LOCAL rule 1210 protocol 'gre'
set firewall name WAN2LOCAL rule 1220 action 'accept'
set firewall name WAN2LOCAL rule 1220 protocol 'ipip'
{gre_fw_mss_block}
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces ethernet {wan_if} address '{wan_addr}'
set interfaces ethernet {wan_if} description 'TO-WAN'
{lan_if_block}
{main_vtun_section}
{bk_vtun_section}
{main_gre_section}
{bk_gre_section}
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
set policy route-map AS{ce_as}-OUT rule 10 action 'permit'
set policy route-map AS{ce_as}-OUT rule 10 match ip address prefix-list 'AS{ce_as}-OUT'
set policy route-map AS{ce_as}-OUT rule 20 action 'deny'
set policy route-map bgp-from--BACKUP rule 10 action 'permit'
set policy route-map bgp-from--BACKUP rule 10 set local-preference '50'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute connected route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute static route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} remote-as '{main_pe_as}'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} update-source '{main_bgp_update_source}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast route-map import 'bgp-from--BACKUP'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} remote-as '{bk_pe_as}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} update-source '{bk_bgp_update_source}'
set protocols bgp {ce_as} timers holdtime '15'
set protocols bgp {ce_as} timers keepalive '5'
{main_track_block}
{wan_route_block}
{mpls_static_routes_block}
{return_routes_block}
{prefix_list_block}
{dhcp_server_block}
set system host-name '{hostname}'
