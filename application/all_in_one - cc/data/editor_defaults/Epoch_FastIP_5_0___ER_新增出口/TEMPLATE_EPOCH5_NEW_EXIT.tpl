set interfaces dummy dum{ER_NE_MAIN_DUM_START} address '{main_dum_first_ip}/32'
set interfaces dummy dum{ER_NE_MAIN_DUM_START} description 'USIP-Main:{main_dum_first_ip}-{main_dum_first_remote}'
{ER_NE_MAIN_DUM_BLOCK}
set interfaces tunnel {main_tun} address '{main_tun_addr}'
set interfaces tunnel {main_tun} description 'main-{main_pe}-{main_tun_num}'
set interfaces tunnel {main_tun} encapsulation 'gre'
set interfaces tunnel {main_tun} ip adjust-mss '{main_mss}'
set interfaces tunnel {main_tun} mtu '{main_mtu}'
set interfaces tunnel {main_tun} remote '{main_pe_docking}'
set interfaces tunnel {main_tun} source-address '{main_ce_docking}'
{ER_NE_BK_BLOCK}
set protocols static route {main_pe_docking}/32 next-hop {ER_NE_MAIN_PE_NH_DEFAULT}
	{ER_NE_NAT_HEADER_BLOCK}
	{ER_NE_NAT_BLOCK}
	{ER_NE_FNET_BLOCK}