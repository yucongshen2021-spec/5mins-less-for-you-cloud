set interfaces tunnel {main_tun} address '{main_tun_addr}'
set interfaces tunnel {main_tun} description 'main-{main_pe}'
set interfaces tunnel {main_tun} encapsulation 'gre'
set interfaces tunnel {main_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_tun} mtu '1400'
set interfaces tunnel {main_tun} multicast 'disable'
set interfaces tunnel {main_tun} parameters ip ttl '255'
set interfaces tunnel {main_tun} remote '{main_pe_docking}'
set interfaces tunnel {main_tun} source-address '{main_ce_docking}'

set protocols static route {main_pe_docking}/32 next-hop {ER_NE_MAIN_PE_NH_DEFAULT}
{ER_NE_MAIN_DUM_BLOCK}
{ER_NE_BK_BLOCK}{ER_NE_NAT_HEADER_BLOCK}{ER_NE_NAT_BLOCK}{ER_NE_FNET_BLOCK}