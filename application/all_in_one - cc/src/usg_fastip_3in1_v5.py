#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USG FastIP 3合1 配置生成工具 v5
新增功能：
  1. WAN口 DHCP 选项 —— 开启后WAN口使用 ip address dhcp-alloc，
     路由只生成 ip route-static 1.1.1.1 32 GE 0/0/9 dhcp，不生成默认路由
  2. 额外内网段输入 —— 判断是否与 LAN IP 同网段，
     异网段时提示用户是否添加回程路由并生成对应静态路由
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import ipaddress
import sys

try:
    import field_coverage
except ImportError:
    field_coverage = None  # type: ignore

try:
    from field_coverage import inject_usg_template_init_aliases
except ImportError:
    def inject_usg_template_init_aliases(_fmt: dict, _net: dict) -> None:  # type: ignore[misc]
        pass

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):  # type: ignore[misc]
        pass

_USG_NONHK_COVER_SKIP = frozenset({
    "wan_mode_desc", "wan_if_block", "wan_default_routes", "dns_dnat_block",
    "extra_return_routes", "dhcp_block", "wan_eth", "lan_eth",
    "main_lo_block", "backup_lo_block", "main_nat_block", "backup_nat_block",
    "main_snat_block", "backup_snat_block",
    "bgp_main_lo", "bgp_backup_lo",
})
_USG_HK_COVER_SKIP = frozenset({
    "wan_if_block", "wan_default_routes", "dns_dnat_block", "dhcp_block",
    "wan_eth", "lan_eth",
    "main_lo_block", "main_nat_block", "main_snat_block", "backup_snat_block",
    "extra_return_routes",
})

# ── 默认值 ────────────────────────────────────────────────────────────────────
DEFAULT_WAN_IP   = '192.168.9.190/24'
DEFAULT_WAN_MASK = '255.255.255.0'
DEFAULT_WAN_GW   = '192.168.9.1'
DEFAULT_WAN_ETH  = 'GE0/0/9'
DEFAULT_LAN_IP   = '192.168.8.1/24'
DEFAULT_LAN_GW   = '192.168.8.1/24'
DEFAULT_LAN_MASK = '255.255.255.0'
DEFAULT_LAN_ETH  = 'GE0/0/8'
DEFAULT_DNS1     = '10.255.108.7'
DEFAULT_DNS2     = '10.255.108.58'
HK_DEFAULT_DNS1  = '10.255.108.5'
HK_DEFAULT_DNS2  = '10.255.108.6'
DEFAULT_INNER_NETS = '192.168.0.0/16'

HK_DEFAULT_WAN_IP   = '192.168.9.190/24'
HK_DEFAULT_WAN_GW   = '192.168.9.1'
HK_DEFAULT_WAN_ETH  = 'GE0/0/9'
HK_DEFAULT_LAN_IP   = '192.168.8.1/24'
HK_DEFAULT_LAN_GW   = '192.168.8.1/24'
HK_DEFAULT_LAN_ETH  = 'GE0/0/8'
HK_DEFAULT_INNER_NETS = '192.168.0.0/16'
# 与 build_net_panel(wan_dhcp_default=False, lan_dhcp_default=True) 一致，可视化可改
DEFAULT_WAN_DHCP   = False
DEFAULT_LAN_DHCP   = True
DEFAULT_GEN_RETURN_ROUTE = False
HK_DEFAULT_WAN_DHCP = False
HK_DEFAULT_LAN_DHCP = True
HK_DEFAULT_GEN_RETURN_ROUTE = False

# ── BGP Server 版本 ──
DEFAULT_BGP_VERSION = "new"  # init 默认值："old" = 旧版 BGP, "new" = 新版 BGP

# 旧版 BGP server（现有）
_OLD_BGP_MAIN_1 = "103.252.19.25"
_OLD_BGP_MAIN_2 = "43.229.117.226"
_OLD_BGP_BACKUP_1 = "43.229.119.251"
_OLD_BGP_BACKUP_2 = "103.252.19.99"

# 新版 BGP server（hkg1-bgpserver5/6, szd-bgpserver5/6）
_NEW_BGP_MAIN_1 = "103.252.18.206"   # hkg1-bgpserver5
_NEW_BGP_MAIN_2 = "103.252.19.206"   # hkg1-bgpserver6
_NEW_BGP_BACKUP_1 = "43.229.117.207" # szd-bgpserver5
_NEW_BGP_BACKUP_2 = "43.229.119.206" # szd-bgpserver6

def _get_bgp_servers(version="old"):
    """返回 (main_1, main_2, backup_1, backup_2) 根据版本选择 BGP server 组。"""
    if version == "new":
        return (_NEW_BGP_MAIN_1, _NEW_BGP_MAIN_2, _NEW_BGP_BACKUP_1, _NEW_BGP_BACKUP_2)
    return (_OLD_BGP_MAIN_1, _OLD_BGP_MAIN_2, _OLD_BGP_BACKUP_1, _OLD_BGP_BACKUP_2)

def _get_bgp_server_names(version="old"):
    """返回 (main_name_1, main_name_2, backup_name_1, backup_name_2)。"""
    if version == "new":
        return ("hkg1-bgpserver5", "hkg1-bgpserver6", "szd-bgpserver5", "szd-bgpserver6")
    return ("BGPserver1", "BGPserver2", "BGPserver3", "BGPserver4")
DEFAULT_WAN_IP_PLAIN = DEFAULT_WAN_IP.split("/", 1)[0].strip() if DEFAULT_WAN_IP else ""
DEFAULT_LAN_IP_PLAIN = DEFAULT_LAN_IP.split("/", 1)[0].strip() if DEFAULT_LAN_IP else ""
HK_DEFAULT_WAN_IP_PLAIN = (
    HK_DEFAULT_WAN_IP.split("/", 1)[0].strip() if HK_DEFAULT_WAN_IP else ""
)
HK_DEFAULT_LAN_IP_PLAIN = (
    HK_DEFAULT_LAN_IP.split("/", 1)[0].strip() if HK_DEFAULT_LAN_IP else ""
)
USG_FL_MAIN_TUN_DEFAULT = "3000"
USG_FL_BK_TUN_DEFAULT = "4000"
USG_FL_EXAMPLE = (
    "LineID:609526A3\n"
    "PE:szd-upe3\n"
    "Tunnel:Tunnel0/0/2017\n"
    "wanip:10.40.99.44/30\n"
    "PE 对接:10.255.110.13\n"
    "CE 对接:10.18.16.58\n\n"
    "LineID:609526A4\n"
    "PE:szc-upe2\n"
    "Tunnel:Tunnel0/0/1601\n"
    "wanip:10.40.194.24/30\n"
    "PE 对接:10.255.111.139\n"
    "CE 对接:10.18.14.165\n\n"
    "账号：60952601@fnetlink.com  密码：BLEIOYxT\n"
    "账号：60952602@fnetlink.com  密码：uYC3zALF\n"
    "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.11.144/29\n"
    "PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.11.144/29\n"
    "PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.11.144/29"
)
USG_NE_MAIN_TUN_DEFAULT = "1001"
USG_NE_BK_TUN_DEFAULT = "1002"
USG_NE_MAIN_LOOP_START_DEFAULT = "111"
USG_NE_BK_LOOP_START_DEFAULT = "211"
USG_NE_MAIN_NQA_DEFAULT = "main2"
USG_NE_BK_NQA_DEFAULT = "backup2"
TEMPLATE_USG_FLINK_VISUAL = """\
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
"""
TEMPLATE_USG_NEW_EXIT_VISUAL = """\
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
"""
USG_NEW_EXIT_EXAMPLE = (
    "LineID:609424A1\n"
    "PE： lax1-fgpe1\n"
    "WANIP: 10.22.110.24/30\n"
    "TUNNEL: tun1248\n"
    "PE对接：10.255.110.6\n"
    "CE对接：10.18.16.20\n"
    "出口ip：\n"
    "10.61.10.78-64.81.20.174\n"
    "10.61.10.106-64.81.20.178\n"
    "LineID:609424A2\n"
    "PE： sjc1-fgpe2\n"
    "WANIP: 10.22.106.20/30\n"
    "TUNNEL: tun1229\n"
    "PE对接：10.255.111.158\n"
    "CE对接：10.18.14.127\n"
    "出口ip：\n"
    "10.60.76.6-172.16.23.8\n"
    "10.60.76.78-172.16.23.80\n"
)

# ── 非香港出口模板 ──────────────────────────────────────────────────────────────
TEMPLATE_USG_NONHK = """\

主 IPSEC_PE: {main_dial_pe}
拨号IP：{main_dial_ip}
loIP：{main_loopback}
感兴趣流：{main_loopback}/32 ～ 10.255.108.0/22
认证ID：{main_auth_id}
预共享密钥：both-win

LineID:{main_auth_id}
PE: {main_pe}
WANIP: {main_wanip}
TUNNEL: {main_tunnel}
隧道IP(PE侧): {main_wanip1}
隧道IP(CE侧): {main_wanip2}
PE对接：{main_peer_ip}
CE对接：{main_loopback}
出口ip：
{main_export_summary}

备 IPSEC_PE: {backup_dial_pe}
拨号IP：{backup_dial_ip}
loIP：{backup_loopback}
感兴趣流：{main_loopback}/32 ～ 10.255.108.0/22
感兴趣流：{backup_loopback}/32 ～ 10.255.111.128/25
认证ID：{backup_auth_id}
预共享密钥：both-win

LineID:{main_auth_id}
PE: {backup_pe}
WANIP: {backup_wanip}
TUNNEL: {backup_tunnel}
隧道IP(PE侧): {backup_wanip1}
隧道IP(CE侧): {backup_wanip2}
PE对接：{backup_peer_ip}
CE对接：{backup_loopback}
出口ip：
{backup_export_summary}

模版是非香港出口，WAN口{wan_mode_desc}，LAN口DHCP下发地址
一、初始化配置
1.1、SD卡格式化
system
diagnose
#查看当前SD-Card的状态，未格式化时是"未注册"状态，格式化后是注册状态
display device disk
#格式化SD-Card，失败就再格式化一次
format disk partition nlog
Y
return
disk offline
Y
disk online
Y
system
diagnose 
display device disk
#查看log日志盘大小是否与SD-Card一致
display disk partition nlog  
quit

1.2、NTP配置
clock timezone Beijing add 08:00:00
ntp unicast-server 192.168.55.250
ntp unicast-server 203.107.6.88

1.3、Log流量、策略日志开启
log type policy enable
log type traffic enable
log type traffic-report enable

1.4、威胁防护&资产扫描
asset threat-insight enable
asset monitor-host ip 10.0.0.0 mask 8
asset monitor-host ip 172.16.0.0 mask 12
asset monitor-host ip 192.168.0.0 mask 16

1.5、特征库更新升级
update schedule ips-sdb daily 02:44
update schedule av-sdb daily 03:34
update schedule sa-sdb daily 04:20

1.6、创建bothwin账号以及3A认证
#配置tacacs认证登录
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server shared-key cipher bothwin
y
#
aaa
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 3 hwtacacs local
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 service-scheme fnet_tac
  admin-user privilege level 3
 domain fnet_tac
  authentication-scheme fnet_tac  
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  hwtacacs-server fnetlink_tacacs
domain fnet_tac admin
#
aaa
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
  quit
 local-user bothwin password irreversible-cipher .x12Tfe192Ti.2024
 local-user bothwin password-force-change disable
 local-user bothwin privilege level 3
y
 local-user bothwin service-type terminal telnet http ssh
y
local-user bothwin@default password irreversible-cipher .x12Tfe192Ti.2024
local-user bothwin@default password-force-change disable
local-user bothwin@default privilege level 3
y
local-user bothwin@default service-type terminal telnet http ssh
y

1.7、开启web登录权限
web-manager enable port 8443
web-manager http forward enable
web-manager server-source -i GE0/0/0
y
web-manager server-source all-interface
y


1.8、开启ssh登录权限
stelnet server enable
ssh ipv4 server port 2707
Y
ssh server rsa-key min-length 1024
ssh user bothwin
ssh user bothwin authentication-type password
ssh user bothwin service-type all
ssh user bothwin sftp-directory flash:
ssh user bothwin@default 
ssh user bothwin@default authentication-type password
ssh user bothwin@default service-type all
ssh user bothwin@default sftp-directory flash:
ssh server-source all-interface
Y
#
ssh server cipher aes256_gcm aes128_gcm aes256_ctr aes192_ctr aes128_ctr
ssh server hmac sha2_256_96 sha2_256 sha1 sha1_96 md5 md5_96
ssh server key-exchange dh_group_exchange_sha256 dh_group16_sha512 curve25519_sha256
ssh server publickey ecc x509v3-ssh-rsa rsa_sha2_256 rsa_sha2_512
#               
ssh server dh-exchange min-len 1024
#
ssh client first-time enable
#
ssh client publickey x509v3-ssh-rsa rsa_sha2_256 rsa_sha2_512
#
1.9、设置acl白名单登录设备
acl number 3999
 rule 5 permit ip source 202.104.174.178 0
 rule 10 permit ip source 100.64.0.0 0.63.255.255
 rule 15 permit ip source 113.105.190.147 0
 rule 20 permit ip source 114.112.238.8 0.0.0.7
 rule 25 permit ip source 114.113.245.101 0
 rule 30 permit ip source 120.76.31.146 0
 rule 35 permit ip source 127.0.0.1 0
 rule 40 permit ip source 172.16.0.0 0.15.255.255
 rule 45 permit ip source 183.61.239.168 0
 rule 50 permit ip source 192.168.0.0 0.0.255.255
 rule 55 permit ip source 192.168.55.250 0
 rule 65 permit ip source 59.37.126.140 0
 rule 70 permit ip source 10.0.0.0 0.255.255.255
 rule 71 permit ip source 119.145.21.125 0
 rule 72 permit ip source 43.229.117.21 0
 rule 73 permit ip source 119.145.21.126 0
 rule 74 permit ip source 43.229.119.246 0
#
 web-manager acl 3999
 y

user-interface vty 0 15
 acl 3999 inbound
 authentication-mode aaa
 protocol inbound ssh
#串口
user-interface console 0    
 authentication-mode aaa

#
1.10、设置全局接口tcp-mss
firewall tcp-mss 1200

1.11、中控配置解锁
undo configuration exclusive by-user-name huawei

1.12、关闭状态检测
undo firewall session link-state check

二、接口配置
2.1、新建IPSec的VRF
ip vpn-instance ipsecnat1
 ipv4-family
{wan_if_block}

2.3、LAN口配置
{dhcp_block}


---------------------------------------------------------
2.4、LoopBack接口
2.4.1、ipsec主-LoopBack
interface LoopBack10
 description FastIP-Main-lo 
 ip address {main_loopback} 255.255.255.255

2.4.2、ipsec备-LoopBack
interface LoopBack11
 description FastIP-Back-lo
 ip address {backup_loopback} 255.255.255.255

2.4.3、海外出口假IP接口
{main_lo_block}
{backup_lo_block}



2.5、自环接口
interface GE0/0/7.100
 description Main_Table_WAN_Customer
 ip address 100.66.1.1 255.255.255.252
 dot1q termination vid 100
 service-manage all permit

interface GE0/0/6.100
 description IPsec_to_ Main_Table_WAN
 ip binding vpn-instance ipsecnat1
 ip address 100.66.1.2 255.255.255.252
 dot1q termination vid 100
 service-manage all permit

2.6、自环感兴趣流路由
#全局添加感兴趣流路由指向自环的VRF，VRF添加本地感兴趣流IP回程路由指回全局
ip route-static 10.255.108.0 255.255.252.0 100.66.1.2
ip route-static 10.255.111.128 25 100.66.1.2
ip route-static vpn-instance ipsecnat1 {main_loopback} 32 100.66.1.1
ip route-static vpn-instance ipsecnat1 {backup_loopback} 32 100.66.1.1
三、IPSec配置
3.1、IPSec兴趣流
#主IPSEC感兴趣流
acl number 3004
 rule 5 permit ip vpn-instance ipsecnat1 source {main_loopback} 0 destination 10.255.108.0 0.0.3.255

#备IPSEC感兴趣流
acl number 3005
 rule 5 permit ip vpn-instance ipsecnat1 source {main_loopback} 0 destination 10.255.108.0 0.0.3.255
 rule 10 permit ip vpn-instance ipsecnat1 source {backup_loopback} 0 destination 10.255.111.128 0.0.0.127

3.2、IPSec策略
ipsec remote traffic-identical accept
 ike proposal 1
 encryption-algorithm aes-256
 dh group14
 authentication-algorithm sha2-256
 authentication-method pre-share
 integrity-algorithm hmac-sha2-384
 prf hmac-sha2-384
#
ipsec proposal 1
 encapsulation-mode auto
 undo esp authentication-algorithm
 esp encryption-algorithm aes-128-gcm-128

3.3、主线IKE配置
ike peer fastip1
 pre-shared-key both-win
 ike-proposal 1
 local-id-type fqdn
 remote-id-type none
 local-id {main_auth_id}
 dpd type periodic
 sa binding vpn-instance ipsecnat1
 remote-address vpn-instance ipsecnat1 {main_dial_ip}
 negotiate route inject enable
 y

3.4、备线IKE配置
ike peer fastip2
 pre-shared-key both-win
 ike-proposal 1
 local-id-type fqdn
 remote-id-type none
 local-id {backup_auth_id}
 dpd type periodic
 sa binding vpn-instance ipsecnat1
 remote-address vpn-instance ipsecnat1 {backup_dial_ip}
 negotiate route inject enable
 y

3.5、主线IPSec配置
ipsec policy S2S-Fastip1 10 isakmp
 security acl 3004
 ike-peer fastip1
 proposal 1
 tunnel local 100.66.1.2
 alias FastIP-Main
 sa trigger-mode auto
 sa duration traffic-based 0
 sa duration time-based 3600
 route inject dynamic preference 10

3.6、备线IPSec配置
ipsec policy S2S-Fastip2 10 isakmp
 security acl 3005
 ike-peer fastip2
 proposal 1
 tunnel local 100.66.1.2
 alias FastIP-Back
 sa trigger-mode auto
 sa duration traffic-based 0
 sa duration time-based 3600
 route inject dynamic preference 20

3.7、主IPSec虚拟接口
interface tunnel1
 description FastIP-Main-Tunnnel1
 ip binding vpn-instance ipsecnat1
 ip address unnumbered interface GE0/0/6.100
 tunnel-protocol ipsec
 service-manage all permit
 ipsec policy S2S-Fastip1

3.8、备IPSec虚拟接口
interface tunnel2
 description FastIP-Back-Tunnnel2
 ip binding vpn-instance ipsecnat1
 ip address unnumbered interface GE0/0/6.100
 tunnel-protocol ipsec
 service-manage all permit
 ipsec policy S2S-Fastip2

四、GRE Tunnel 配置
4.1、主出口GRE
interface Tunnel1000
 description Main-{main_pe}-{main_tunnel}
 mtu 1300
 ip address {main_wanip2} 255.255.255.252
 tunnel-protocol gre
 source LoopBack10
 destination {main_peer_ip}
 service-manage all permit

4.2、备出口GRE
interface Tunnel2000
 description BK-{backup_pe}-{backup_tunnel}
 mtu 1300
 ip address {backup_wanip2} 255.255.255.252
 tunnel-protocol gre
 source LoopBack11
 destination {backup_peer_ip}
 service-manage all permit


-----------------------------------------------------------------------------
五、安全区域配置
5.1、untrust区域
firewall zone untrust
add interface {wan_eth}

add interface tunnel1
add interface tunnel2
add interface Tunnel1000
add interface Tunnel2000



5.2、trust区域
firewall zone trust
add interface GE0/0/5
add interface {lan_eth}
5.3、ipsecZone区域
firewall zone name ipsecZone
add interface GE0/0/6.100
add interface GE0/0/7.100

六、静态路由配置
6.1、默认路由
{wan_default_routes}
6.2、IPSec对接路由
ip route-static {backup_dial_ip} 255.255.255.255 1.1.1.1
ip route-static {main_dial_ip} 255.255.255.255 1.1.1.1

6.3、IPSec自环路由
ip route-static vpn-instance ipsecnat1 0.0.0.0 0.0.0.0 100.66.1.1

6.4、乾坤云路由
ip route-static 119.145.21.126 255.255.255.255 1.1.1.1 description qiankunyun
ip route-static 119.145.21.124 255.255.255.255 1.1.1.1 description qiankunyun

6.5、GRE监控路由
ip route-static 114.113.245.99 255.255.255.255 {main_wanip1} description to-mian-zabbix
ip route-static 192.168.55.11 255.255.255.255 {backup_wanip1} description to-backup-zabbix

6.6、公网BGP路由
ip route-static {bgp_main_server1} 255.255.255.255 {main_wanip1} description {bgp_main_name1}
ip route-static {bgp_main_server2} 255.255.255.255 {main_wanip1} description {bgp_main_name2}
ip route-static {bgp_backup_server1} 255.255.255.255 {backup_wanip1} description {bgp_backup_name1}
ip route-static {bgp_backup_server2} 255.255.255.255 {backup_wanip1} description {bgp_backup_name2}
#
ip route-static {bgp_main_server1} 255.255.255.255 NULL0 preference 65 description {bgp_main_name1}
ip route-static {bgp_main_server2} 255.255.255.255 NULL0 preference 65 description {bgp_main_name2}
ip route-static {bgp_backup_server1} 255.255.255.255 NULL0 preference 65 description {bgp_backup_name1}
ip route-static {bgp_backup_server2} 255.255.255.255 NULL0 preference 65 description {bgp_backup_name2}
{extra_return_routes}
七、NAT配置
7.1、创建IPSec对端PE兴趣流地址组
ip address-set FastIP-PE-lo type object
 address 0 10.255.108.0  mask 22
 address 1 10.255.111.128 mask 25

7.2、排除PE兴趣流地址SNAT
nat-policy
 rule name ipsec-NOT-NAT
  destination-address address-set FastIP-PE-lo
  action no-nat
7.3、排除监控地址SNAT
rule name ToMainZabbix
  egress-interface Tunnel1000
  destination-address 114.113.245.99 mask 255.255.255.255
  destination-address 192.168.55.10 mask 255.255.255.255
  action no-nat

rule name ToBackZabbix
  egress-interface Tunnel2000
  destination-address 114.113.245.100 mask 255.255.255.255
  destination-address 192.168.55.11 mask 255.255.255.255
  action no-nat

7.4、创建自环接口地址对
ip address-set IPsec-vrf type object
 address 0 100.66.1.0 mask 30

7.5、自环接口地址对SNAT
nat-policy
rule name ipsec-VRF-to-WAN
  source-zone ipsecZone
  egress-interface {wan_eth}
  source-address address-set IPsec-vrf
  action source-nat easy-ip

7.6、创建内网LAN-IP组
ip address-set LAN-IP type object
 address 0 10.0.0.0 mask 8
 address 1 172.16.0.0 mask 12
 address 2 192.168.0.0 mask 16

7.7、创建主出口NAT地址组
{main_nat_block}

7.8、创建备出口NAT地址组
{backup_nat_block}




7.9、创建所有IP的地址组（用于DNS拦截）
ip address-set ALL-IP type object
 address 0 0.0.0.0 mask 1
 address 1 128.0.0.0 mask 1

7.10、创建DNS拦截成接口IP（用于DNS拦截）
{dns_dnat_block}

7.11、海外主出口SNAT
{main_snat_block}

7.12、海外备出口SNAT
{backup_snat_block}

7.13、国内上网SNAT
nat-policy
 rule name ToChinaOUT
  source-zone local
  source-zone trust
  source-zone untrust
  egress-interface {wan_eth}
  source-address address-set LAN-IP
  action source-nat easy-ip

7.14、DNS拦截DNAT
nat-policy
 rule name DNS-jiechi
 disable
  source-zone untrust
  source-zone trust
  source-address address-set LAN-IP
  destination-address address-set ALL-IP
  service dns
  action destination-nat address-group DNS-IP
  Y

八、NQA配置
8.1、主IPSec兴趣流NQA
#注意 NQA 探测联动时间建议在1分钟或者以上，规避 assistant 周期内 因ipsec 未恢复建立而引起循环重置   切换参数按需修改
nqa test-instance admin ipsec1_nqa
 test-type icmp
 destination-address ipv4 {main_peer_ip}
 source-address ipv4 {main_loopback}
 send-trap probefailure
 send-trap testfailure
 test-failtimes 2
 probe-count 4
 frequency 30
 start now

8.2、备IPSec兴趣流NQA
nqa test-instance admin ipsec2_nqa
 test-type icmp 
 destination-address ipv4 {backup_peer_ip}
 source-address ipv4 {backup_loopback}
 send-trap probefailure
 send-trap testfailure
 test-failtimes 2
 probe-count 4
 frequency 30
 start now

8.3、海外主GRE隧道NQA
nqa test-instance fastip main
 test-type icmp
 destination-address ipv4 {main_wanip1}
 probe-count 1
 frequency 5
 start now

8.4、海外备GRE隧道NQA
nqa test-instance fastip backup
 test-type icmp
 destination-address ipv4 {backup_wanip1}
 probe-count 1
 frequency 5
 start now
8.5、跳板机路由
ip route-static 192.168.55.250 255.255.255.255 {main_wanip1} track nqa fastip main
ip route-static 192.168.55.250 255.255.255.255 {backup_wanip1} preference 70




九、BGP分流配置
9.1、community-list 配置
#to_OUT
ip community-filter 80 index 10 permit 65000:9939
#to_ct
ip community-filter 81 index 10 permit 65000:4134
#to_cnc
ip community-filter 82 index 10 permit 65000:4837
#to_cn_other
ip community-filter 83 index 10 permit 65000:9808
#to_google
ip community-filter 88 index 10 permit 65000:9008
#to_office365
ip community-filter 91 index 10 permit 65000:9009

9.2、BGP分流下一跳配置
9.2.1、主线
route-policy bgp-from--RSVR permit node 100
 description to-main-out
 if-match community-filter 80
 apply ip-address next-hop {main_wanip1}
#
route-policy bgp-from--RSVR permit node 200
 description to-china
 if-match community-filter 81
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 300
 description to-china
 if-match community-filter 82
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 400
 description to-china
 if-match community-filter 83
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 500
 description to-main-out
 if-match community-filter 91
 apply ip-address next-hop {main_wanip1}
#
route-policy bgp-from--RSVR deny node 999
#
9.2.2、备线
route-policy bgp-from--RSVR2 permit node 100
 description to-back-out
 if-match community-filter 80
 apply ip-address next-hop {backup_wanip1}
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 200
 description to-china
 if-match community-filter 81
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 300
 description to-china
 if-match community-filter 82
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 400
 description to-china
 if-match community-filter 83
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 500
 description to-back-out
 if-match community-filter 91
 apply ip-address next-hop {backup_wanip1}
 apply local-preference 50
#
route-policy bgp-from--RSVR2 deny node 999
#
9.2.3、拒绝发布路由给BGPServer
route-policy bgp-from--deny deny node 999
#
9.3、BGP配置
bgp 65000
 router-id {main_export_natip}
 timer keepalive 5 hold 15
 y
 private-4-byte-as enable
 peer {bgp_main_server1} as-number 65000
 peer {bgp_main_server1} connect-interface {bgp_main_lo}
 peer {bgp_main_server2} as-number 65000
 peer {bgp_main_server2} connect-interface {bgp_main_lo}
 peer {bgp_backup_server1} as-number 65000
 peer {bgp_backup_server1} connect-interface {bgp_backup_lo}
 peer {bgp_backup_server2} as-number 65000
 peer {bgp_backup_server2} connect-interface {bgp_backup_lo}
 #
 ipv4-family unicast
  preference 20 50 200
  peer {bgp_main_server1} route-policy bgp-from--RSVR import
  peer {bgp_main_server1} route-policy bgp-from--deny export
  peer {bgp_main_server2} enable
  peer {bgp_main_server2} route-policy bgp-from--RSVR import
  peer {bgp_main_server2} route-policy bgp-from--deny export
  peer {bgp_backup_server1} enable
  peer {bgp_backup_server1} route-policy bgp-from--RSVR2 import
  peer {bgp_backup_server1} route-policy bgp-from--deny export
  peer {bgp_backup_server2} enable
  peer {bgp_backup_server2} route-policy bgp-from--RSVR2 import
  peer {bgp_backup_server2} route-policy bgp-from--deny export
#
十、安全策略
10.1、创建邮件规则
profile type mail-filter name Mail_Protect
anti-spam filter enable

10.2、创建f-guard安全策略
security-policy
 default packet-filter intrazone enable
 rule name f-guard
  source-zone dmz
  source-zone ipsecZone
  source-zone local
  source-zone trust
  source-zone untrust
  destination-zone dmz
  destination-zone ipsecZone
  destination-zone local
  destination-zone trust
  destination-zone untrust
  policy logging
  session logging
  profile av default
  profile ips default
  profile url-filter default
  profile data-filter default
  profile file-block default
  profile dns-filter default
  profile mail-filter Mail_Protect
  action permit 



十二、DNS配置
#USG6000F-dns是全局系统概念 、dns查询路由才有vrf概念、所以dns服务开启代理是对系统生效、不同vrf和接口都可以通用一个智能dns服务
#机制说明：
#1、source-interface需要与dns服务器都在同一个vpn内，或者都在_public_内，否则不生效
#2、dns server X.X.X.X vpn-instance ipsecnat1可以指定dns服务器的vpn
#3、10.255.108.6和  source-interface在同一vpn，因此会正确走感兴趣流访问dns服务器
#4、223.5.5.5和source-interface不在同一vpn，因此按默认设定走_public_的路由，
#5、使用出接口IP作为源地址
#6、如果dns server bind的IP在vpn内，需要指定其vpn，否则不生效
#7、例如：dns server bind local-ip 192.168.250.1 vpn-instance LAN1
#8、先删除旧配置，不然旧的DNS配置可能会影响解析结果
undo dns server
dns resolve
dns server {dns_ip1}
dns server {dns_ip2}


dns server source-interface LoopBack10
不要写，否则DNS劫持不生效
#dns server bind local-ip {lan_ip}
dns-server-select-algorithm fixed
dns proxy enable
dns proxy forward-any-response
dns forward retry-number 0
dns forward retry-timeout 1
 #DNS透明代理测试模板
#dns-transparent-policy
#dns transparent-proxy enable
#dns transparent-proxy exclude domain *.faw.cn server preferred 10.10.10.241
#dns transparent-proxy exclude domain faw.cn server preferred 10.10.10.241
#mode based-on-multi-interface
#rule name dns
# action tpdns


十三、OPS配置
13.1、重置IKE会话
ops
 assistant ipsec1_ike
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature ike name IKE_NEGO_FAIL PeerAddress eq {main_dial_ip}

 assistant ipsec1_sa
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature ipsec name IPSEC_TUNNEL_TEARED_DOWN peer-address eq {main_dial_ip}

 assistant ipsec1_nqa
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature nqa name TEST_FAILED TestName eq ipsec1_nqa

assistant ipsec1_nqa_log
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature nqa name nqaResultsProbeFailed TestName eq ipsec1_nqa

 assistant ipsec2_ike
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature ike name IKE_NEGO_FAIL PeerAddress eq {backup_dial_ip}

 assistant ipsec2_sa
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature ipsec name IPSEC_TUNNEL_TEARED_DOWN peer-address eq {backup_dial_ip}

 assistant ipsec2_nqa
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature nqa name TEST_FAILED TestName eq ipsec2_nqa

assistant ipsec2_nqa_log
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature nqa name nqaResultsProbeFailed TestName eq ipsec2_nqa


"""

# ── 香港出口模板 ──────────────────────────────────────────────────────────────
TEMPLATE_USG_HK = """\

主 IPSEC_PE: {main_dial_pe}
拨号IP：{main_dial_ip}
loIP：{main_loopback}
感兴趣流：{main_loopback}/32 ～ 10.255.108.0/22
认证ID：{main_auth_id}
预共享密钥：both-win

LineID:{main_auth_id}
PE: {main_pe}
WANIP: {main_wanip}
TUNNEL: {main_tunnel}
隧道IP(PE侧): {main_wanip1}
隧道IP(CE侧): {main_wanip2}
PE对接：{main_peer_ip}
CE对接：{main_loopback}
出口ip：
{main_export_summary}

备 IPSEC_PE: {backup_dial_pe}
拨号IP：{backup_dial_ip}
loIP：{backup_loopback}
感兴趣流：{main_loopback}/32 ～ 10.255.108.0/22
感兴趣流：{backup_loopback}/32 ～ 10.255.111.128/25
认证ID：{backup_auth_id}
预共享密钥：both-win

LineID:{backup_auth_id}
PE: {backup_pe}
WANIP: {backup_wanip}
TUNNEL: {backup_tunnel}
隧道IP(PE侧): {backup_wanip1}
隧道IP(CE侧): {backup_wanip2}
PE对接：{backup_peer_ip}
CE对接：{backup_loopback}
出口ip：
{backup_export_summary}

模版是HK出口，WAN口{wan_mode_desc}，LAN口DHCP下发地址
一、初始化配置
1.1、SD卡格式化
system
diagnose
display device disk
format disk partition nlog
Y
return
disk offline
Y
disk online
Y
system
diagnose 
display device disk
display disk partition nlog  
quit

1.2、NTP配置
clock timezone Beijing add 08:00:00
ntp unicast-server 192.168.55.250
ntp unicast-server 203.107.6.88

1.3、Log流量、策略日志开启
log type policy enable
log type traffic enable
log type traffic-report enable

1.4、威胁防护&资产扫描
asset threat-insight enable
asset monitor-host ip 10.0.0.0 mask 8
asset monitor-host ip 172.16.0.0 mask 12
asset monitor-host ip 192.168.0.0 mask 16

1.5、特征库更新升级
update schedule ips-sdb daily 02:44
update schedule av-sdb daily 03:34
update schedule sa-sdb daily 04:20

1.6、创建bothwin账号以及3A认证
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server shared-key cipher bothwin
y
#
aaa
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 3 hwtacacs local
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 service-scheme fnet_tac
  admin-user privilege level 3
 domain fnet_tac
  authentication-scheme fnet_tac  
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  hwtacacs-server fnetlink_tacacs
domain fnet_tac admin
#
aaa
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
  quit
 local-user bothwin password irreversible-cipher .x12Tfe192Ti.2024
 local-user bothwin password-force-change disable
 local-user bothwin privilege level 3
y
 local-user bothwin service-type terminal telnet http ssh
y
local-user bothwin@default password irreversible-cipher .x12Tfe192Ti.2024
local-user bothwin@default password-force-change disable
local-user bothwin@default privilege level 3
y
local-user bothwin@default service-type terminal telnet http ssh
y

1.7、开启web登录权限
web-manager enable port 8443
web-manager http forward enable
web-manager server-source -i GE0/0/0
y
web-manager server-source all-interface
y


1.8、开启ssh登录权限
stelnet server enable
ssh ipv4 server port 2707
Y
ssh server rsa-key min-length 1024
ssh user bothwin
ssh user bothwin authentication-type password
ssh user bothwin service-type all
ssh user bothwin sftp-directory flash:
ssh user bothwin@default 
ssh user bothwin@default authentication-type password
ssh user bothwin@default service-type all
ssh user bothwin@default sftp-directory flash:
ssh server-source all-interface
Y
#
ssh server cipher aes256_gcm aes128_gcm aes256_ctr aes192_ctr aes128_ctr
ssh server hmac sha2_256_96 sha2_256 sha1 sha1_96 md5 md5_96
ssh server key-exchange dh_group_exchange_sha256 dh_group16_sha512 curve25519_sha256
ssh server publickey ecc x509v3-ssh-rsa rsa_sha2_256 rsa_sha2_512
#               
ssh server dh-exchange min-len 1024
#
ssh client first-time enable
#
ssh client publickey x509v3-ssh-rsa rsa_sha2_256 rsa_sha2_512
#
1.9、设置acl白名单登录设备
acl number 3999
 rule 5 permit ip source 202.104.174.178 0
 rule 10 permit ip source 100.64.0.0 0.63.255.255
 rule 15 permit ip source 113.105.190.147 0
 rule 20 permit ip source 114.112.238.8 0.0.0.7
 rule 25 permit ip source 114.113.245.101 0
 rule 30 permit ip source 120.76.31.146 0
 rule 35 permit ip source 127.0.0.1 0
 rule 40 permit ip source 172.16.0.0 0.15.255.255
 rule 45 permit ip source 183.61.239.168 0
 rule 50 permit ip source 192.168.0.0 0.0.255.255
 rule 55 permit ip source 192.168.55.250 0
 rule 65 permit ip source 59.37.126.140 0
 rule 70 permit ip source 10.0.0.0 0.255.255.255
 rule 71 permit ip source 119.145.21.125 0
 rule 72 permit ip source 43.229.117.21 0
 rule 73 permit ip source 119.145.21.126 0
 rule 74 permit ip source 43.229.119.246 0
#
web-manager acl 3999
y

user-interface vty 0 15
 acl 3999 inbound
 authentication-mode aaa
 protocol inbound ssh
#串口
user-interface console 0    
 authentication-mode aaa

#
1.10、设置全局接口tcp-mss
firewall tcp-mss 1200

1.11、中控配置解锁
undo configuration exclusive by-user-name huawei

1.12、关闭状态检测
undo firewall session link-state check

二、接口配置
2.1、新建IPSec的VRF
ip vpn-instance ipsecnat1
 ipv4-family
{wan_if_block}

2.3、LAN口配置
{dhcp_block}


---------------------------------------------------------
2.4、LoopBack接口
2.4.1、ipsec主-LoopBack
interface LoopBack10
 description FastIP-Main-lo 
 ip address {main_loopback} 255.255.255.255

2.4.2、ipsec备-LoopBack
interface LoopBack11
 description FastIP-Back-lo
 ip address {backup_loopback} 255.255.255.255

2.4.3、海外出口公网IP接口（用于BGP）
{main_lo_block}



2.5、自环接口
interface GE0/0/7.100
 description Main_Table_WAN_Customer
 ip address 100.66.1.1 255.255.255.252
 dot1q termination vid 100
 service-manage all permit

interface GE0/0/6.100
 description IPsec_to_ Main_Table_WAN
 ip binding vpn-instance ipsecnat1
 ip address 100.66.1.2 255.255.255.252
 dot1q termination vid 100
 service-manage all permit

2.6、自环感兴趣流路由
ip route-static 10.255.108.0 255.255.252.0 100.66.1.2
ip route-static 10.255.111.128 25 100.66.1.2
ip route-static vpn-instance ipsecnat1 {main_loopback} 32 100.66.1.1
ip route-static vpn-instance ipsecnat1 {backup_loopback} 32 100.66.1.1
三、IPSec配置
3.1、IPSec兴趣流
#主IPSEC感兴趣流
acl number 3004
 rule 5 permit ip vpn-instance ipsecnat1 source {main_loopback} 0 destination 10.255.108.0 0.0.3.255

#备IPSEC感兴趣流
acl number 3005
 rule 5 permit ip vpn-instance ipsecnat1 source {main_loopback} 0 destination 10.255.108.0 0.0.3.255
 rule 10 permit ip vpn-instance ipsecnat1 source {backup_loopback} 0 destination 10.255.111.128 0.0.0.127

3.2、IPSec策略
ipsec remote traffic-identical accept
 ike proposal 1
 encryption-algorithm aes-256
 dh group14
 authentication-algorithm sha2-256
 authentication-method pre-share
 integrity-algorithm hmac-sha2-384
 prf hmac-sha2-384
#
ipsec proposal 1
 encapsulation-mode auto
 undo esp authentication-algorithm
 esp encryption-algorithm aes-128-gcm-128

3.3、主线IKE配置
ike peer fastip1
 pre-shared-key both-win
 ike-proposal 1
 local-id-type fqdn
 remote-id-type none
 local-id {main_auth_id}
 dpd type periodic
 sa binding vpn-instance ipsecnat1
 remote-address vpn-instance ipsecnat1 {main_dial_ip}
 negotiate route inject enable
 y

3.4、备线IKE配置
ike peer fastip2
 pre-shared-key both-win
 ike-proposal 1
 local-id-type fqdn
 remote-id-type none
 local-id {backup_auth_id}
 dpd type periodic
 sa binding vpn-instance ipsecnat1
 remote-address vpn-instance ipsecnat1 {backup_dial_ip}
 negotiate route inject enable
 y

3.5、主线IPSec配置
ipsec policy S2S-Fastip1 10 isakmp
 security acl 3004
 ike-peer fastip1
 proposal 1
 tunnel local 100.66.1.2
 alias FastIP-Main
 sa trigger-mode auto
 sa duration traffic-based 0
 sa duration time-based 3600
 route inject dynamic preference 10

3.6、备线IPSec配置
ipsec policy S2S-Fastip2 10 isakmp
 security acl 3005
 ike-peer fastip2
 proposal 1
 tunnel local 100.66.1.2
 alias FastIP-Back
 sa trigger-mode auto
 sa duration traffic-based 0
 sa duration time-based 3600
 route inject dynamic preference 20

3.7、主IPSec虚拟接口
interface tunnel1
 description FastIP-Main-Tunnnel1
 ip binding vpn-instance ipsecnat1
 ip address unnumbered interface GE0/0/6.100
 tunnel-protocol ipsec
 service-manage all permit
 ipsec policy S2S-Fastip1

3.8、备IPSec虚拟接口
interface tunnel2
 description FastIP-Back-Tunnnel2
 ip binding vpn-instance ipsecnat1
 ip address unnumbered interface GE0/0/6.100
 tunnel-protocol ipsec
 service-manage all permit
 ipsec policy S2S-Fastip2

四、GRE Tunnel 配置
4.1、主出口GRE
interface Tunnel1000
 description Main-{main_pe}-{main_tunnel}
 mtu 1300
 ip address {main_wanip2} 255.255.255.252
 tunnel-protocol gre
 source LoopBack10
 destination {main_peer_ip}
 service-manage all permit

4.2、备出口GRE
interface Tunnel2000
 description BK-{backup_pe}-{backup_tunnel}
 mtu 1300
 ip address {backup_wanip2} 255.255.255.252
 tunnel-protocol gre
 source LoopBack11
 destination {backup_peer_ip}
 service-manage all permit


-----------------------------------------------------------------------------
五、安全区域配置
5.1、untrust区域
firewall zone untrust
add interface {wan_eth}

add interface tunnel1
add interface tunnel2
add interface Tunnel1000
add interface Tunnel2000



5.2、trust区域
firewall zone trust
add interface GE0/0/5
add interface {lan_eth}
5.3、ipsecZone区域
firewall zone name ipsecZone
add interface GE0/0/6.100
add interface GE0/0/7.100

六、静态路由配置
6.1、默认路由
{wan_default_routes}
6.2、IPSec对接路由
ip route-static {backup_dial_ip} 255.255.255.255 1.1.1.1
ip route-static {main_dial_ip} 255.255.255.255 1.1.1.1

6.3、IPSec自环路由
ip route-static vpn-instance ipsecnat1 0.0.0.0 0.0.0.0 100.66.1.1

6.4、乾坤云路由
ip route-static 119.145.21.126 255.255.255.255 1.1.1.1 description qiankunyun
ip route-static 119.145.21.124 255.255.255.255 1.1.1.1 description qiankunyun

6.5、GRE监控路由
ip route-static 114.113.245.99 255.255.255.255 {main_wanip1} description to-mian-zabbix
ip route-static 192.168.55.11 255.255.255.255 {backup_wanip1} description to-backup-zabbix

6.6、公网BGP路由
ip route-static {bgp_main_server1} 255.255.255.255 {main_wanip1} description {bgp_main_name1}
ip route-static {bgp_main_server2} 255.255.255.255 {main_wanip1} description {bgp_main_name2}
ip route-static {bgp_backup_server1} 255.255.255.255 {backup_wanip1} description {bgp_backup_name1}
ip route-static {bgp_backup_server2} 255.255.255.255 {backup_wanip1} description {bgp_backup_name2}
#
ip route-static {bgp_main_server1} 255.255.255.255 NULL0 preference 65 description {bgp_main_name1}
ip route-static {bgp_main_server2} 255.255.255.255 NULL0 preference 65 description {bgp_main_name2}
ip route-static {bgp_backup_server1} 255.255.255.255 NULL0 preference 65 description {bgp_backup_name1}
ip route-static {bgp_backup_server2} 255.255.255.255 NULL0 preference 65 description {bgp_backup_name2}
{extra_return_routes}
七、NAT配置
7.1、创建IPSec对端PE兴趣流地址组
ip address-set FastIP-PE-lo type object
 address 0 10.255.108.0  mask 22
 address 1 10.255.111.128 mask 25

7.2、排除PE兴趣流地址SNAT
nat-policy
 rule name ipsec-NOT-NAT
  destination-address address-set FastIP-PE-lo
  action no-nat
7.3、排除监控地址SNAT
rule name ToMainZabbix
  egress-interface Tunnel1000
  destination-address 114.113.245.99 mask 255.255.255.255
  destination-address 192.168.55.10 mask 255.255.255.255
  action no-nat

rule name ToBackZabbix
  egress-interface Tunnel2000
  destination-address 114.113.245.100 mask 255.255.255.255
  destination-address 192.168.55.11 mask 255.255.255.255
  action no-nat

7.4、创建自环接口地址对
ip address-set IPsec-vrf type object
 address 0 100.66.1.0 mask 30

7.5、自环接口地址对SNAT
nat-policy
rule name ipsec-VRF-to-WAN
  source-zone ipsecZone
  egress-interface {wan_eth}
  source-address address-set IPsec-vrf
  action source-nat easy-ip

7.6、创建内网LAN-IP组
ip address-set LAN-IP type object
 address 0 10.0.0.0 mask 8
 address 1 172.16.0.0 mask 12
 address 2 192.168.0.0 mask 16

7.7、创建海外出口NAT地址组（主备线共用）
{main_nat_block}


7.9、创建所有IP的地址组（用于DNS拦截）
ip address-set ALL-IP type object
 address 0 0.0.0.0 mask 1
 address 1 128.0.0.0 mask 1

7.10、创建DNS拦截成接口IP（用于DNS拦截）
{dns_dnat_block}

7.11、海外主出口SNAT
{main_snat_block}

7.12、海外备出口SNAT（与主线共用同一NAT地址组）
{backup_snat_block}

7.13、国内上网SNAT
nat-policy
 rule name ToChinaOUT
  source-zone local
  source-zone trust
  source-zone untrust
  egress-interface {wan_eth}
  source-address address-set LAN-IP
  action source-nat easy-ip

7.14、DNS拦截DNAT
nat-policy
 rule name DNS-jiechi
 disable
  source-zone untrust
  source-zone trust
  source-address address-set LAN-IP
  destination-address address-set ALL-IP
  service dns
  action destination-nat address-group DNS-IP
  Y

八、NQA配置
8.1、主IPSec兴趣流NQA
nqa test-instance admin ipsec1_nqa
 test-type icmp
 destination-address ipv4 {main_peer_ip}
 source-address ipv4 {main_loopback}
 send-trap probefailure
 send-trap testfailure
 test-failtimes 2
 probe-count 4
 frequency 30
 start now

8.2、备IPSec兴趣流NQA
nqa test-instance admin ipsec2_nqa
 test-type icmp 
 destination-address ipv4 {backup_peer_ip}
 source-address ipv4 {backup_loopback}
 send-trap probefailure
 send-trap testfailure
 test-failtimes 2
 probe-count 4
 frequency 30
 start now

8.3、海外主GRE隧道NQA
nqa test-instance fastip main
 test-type icmp
 destination-address ipv4 {main_wanip1}
 probe-count 1
 frequency 5
 start now

8.4、海外备GRE隧道NQA
nqa test-instance fastip backup
 test-type icmp
 destination-address ipv4 {backup_wanip1}
 probe-count 1
 frequency 5
 start now
8.5、跳板机路由
ip route-static 192.168.55.250 255.255.255.255 {main_wanip1} track nqa fastip main
ip route-static 192.168.55.250 255.255.255.255 {backup_wanip1} preference 70




九、BGP分流配置
9.1、community-list 配置
#to_OUT
ip community-filter 80 index 10 permit 65000:9939
#to_ct
ip community-filter 81 index 10 permit 65000:4134
#to_cnc
ip community-filter 82 index 10 permit 65000:4837
#to_cn_other
ip community-filter 83 index 10 permit 65000:9808
#to_google
ip community-filter 88 index 10 permit 65000:9008
#to_office365
ip community-filter 91 index 10 permit 65000:9009

9.2、BGP分流下一跳配置
9.2.1、主线
route-policy bgp-from--RSVR permit node 100
 description to-main-out
 if-match community-filter 80
 apply ip-address next-hop {main_wanip1}
#
route-policy bgp-from--RSVR permit node 200
 description to-china
 if-match community-filter 81
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 300
 description to-china
 if-match community-filter 82
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 400
 description to-china
 if-match community-filter 83
 apply ip-address next-hop 1.1.1.1
#
route-policy bgp-from--RSVR permit node 500
 description to-main-out
 if-match community-filter 91
 apply ip-address next-hop {main_wanip1}
#
route-policy bgp-from--RSVR deny node 999
#
9.2.2、备线
route-policy bgp-from--RSVR2 permit node 100
 description to-back-out
 if-match community-filter 80
 apply ip-address next-hop {backup_wanip1}
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 200
 description to-china
 if-match community-filter 81
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 300
 description to-china
 if-match community-filter 82
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 400
 description to-china
 if-match community-filter 83
 apply ip-address next-hop 1.1.1.1
 apply local-preference 50
#
route-policy bgp-from--RSVR2 permit node 500
 description to-back-out
 if-match community-filter 91
 apply ip-address next-hop {backup_wanip1}
 apply local-preference 50
#
route-policy bgp-from--RSVR2 deny node 999
#
9.2.3、拒绝发布路由给BGPServer
route-policy bgp-from--deny deny node 999
#
9.3、BGP配置
bgp 65000
 router-id {main_export_ip}
 timer keepalive 5 hold 15
 y
 private-4-byte-as enable
 peer {bgp_main_server1} as-number 65000
 peer {bgp_main_server1} connect-interface LoopBack100
 peer {bgp_main_server2} as-number 65000
 peer {bgp_main_server2} connect-interface LoopBack100
 peer {bgp_backup_server1} as-number 65000
 peer {bgp_backup_server1} connect-interface LoopBack100
 peer {bgp_backup_server2} as-number 65000
 peer {bgp_backup_server2} connect-interface LoopBack100
 #
 ipv4-family unicast
  preference 20 50 200
  peer {bgp_main_server1} route-policy bgp-from--RSVR import
  peer {bgp_main_server1} route-policy bgp-from--deny export
  peer {bgp_main_server2} enable
  peer {bgp_main_server2} route-policy bgp-from--RSVR import
  peer {bgp_main_server2} route-policy bgp-from--deny export
  peer {bgp_backup_server1} enable
  peer {bgp_backup_server1} route-policy bgp-from--RSVR2 import
  peer {bgp_backup_server1} route-policy bgp-from--deny export
  peer {bgp_backup_server2} enable
  peer {bgp_backup_server2} route-policy bgp-from--RSVR2 import
  peer {bgp_backup_server2} route-policy bgp-from--deny export
#
十、安全策略
10.1、创建邮件规则
profile type mail-filter name Mail_Protect
anti-spam filter enable

10.2、创建f-guard安全策略
security-policy
 default packet-filter intrazone enable
 rule name f-guard
  source-zone dmz
  source-zone ipsecZone
  source-zone local
  source-zone trust
  source-zone untrust
  destination-zone dmz
  destination-zone ipsecZone
  destination-zone local
  destination-zone trust
  destination-zone untrust
  policy logging
  session logging
  profile av default
  profile ips default
  profile url-filter default
  profile data-filter default
  profile file-block default
  profile dns-filter default
  profile mail-filter Mail_Protect
  action permit 



十二、DNS配置
undo dns server
dns resolve
dns server {dns_ip1}
dns server {dns_ip2}
dns ser 1234567


dns server source-interface LoopBack10
不要写，否则DNS劫持不生效
#dns server bind local-ip {lan_ip}
dns-server-select-algorithm fixed
dns proxy enable
dns proxy forward-any-response
dns forward retry-number 0
dns forward retry-timeout 1

#dns-transparent-policy
#dns transparent-proxy enable
#dns transparent-proxy exclude domain www.qq.com server preferred 223.5.5.5
#mode based-on-multi-interface
#rule name dns
#  #action tpdns

十三、OPS配置
13.1、重置IKE会话
ops
 assistant ipsec1_ike
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature ike name IKE_NEGO_FAIL PeerAddress eq {main_dial_ip}

 assistant ipsec1_sa
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature ipsec name IPSEC_TUNNEL_TEARED_DOWN peer-address eq {main_dial_ip}

 assistant ipsec1_nqa
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature nqa name TEST_FAILED TestName eq ipsec1_nqa

assistant ipsec1_nqa_log
  execute 1 command reset firewall session table destination global {main_dial_ip}
  condition event feature nqa name nqaResultsProbeFailed TestName eq ipsec1_nqa

 assistant ipsec2_ike
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature ike name IKE_NEGO_FAIL PeerAddress eq {backup_dial_ip}

 assistant ipsec2_sa
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature ipsec name IPSEC_TUNNEL_TEARED_DOWN peer-address eq {backup_dial_ip}

 assistant ipsec2_nqa
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature nqa name TEST_FAILED TestName eq ipsec2_nqa

assistant ipsec2_nqa_log
  execute 1 command reset firewall session table destination global {backup_dial_ip}
  condition event feature nqa name nqaResultsProbeFailed TestName eq ipsec2_nqa


"""

# ── 工具函数 ──────────────────────────────────────────────────────────────────
def clean_value(v):
    v = re.sub(r'\(.*?\)', '', v)
    v = re.sub(r'[;\uff1b\n]', '', v)
    return v.strip()

def safe_split(s, sep):
    parts = s.split(sep, 1)
    return parts[1].strip() if len(parts) > 1 else ''

def parse_ip_mask(ip_str, default_ip='', default_mask='255.255.255.0'):
    ip_str = ip_str.strip()
    if not ip_str:
        return default_ip, default_mask
    if '/' in ip_str:
        try:
            net = ipaddress.IPv4Network(ip_str, strict=False)
            host = ip_str.split('/')[0]
            return host, str(net.netmask)
        except Exception:
            return ip_str.split('/')[0], default_mask
    return ip_str, default_mask

def _validate_cidr_input(value, name="IP"):
    """校验主机 CIDR（如 192.168.1.1/24）。"""
    if not value or not value.strip():
        return True, None
    s = value.strip()
    if s.lower() == "dhcp":
        return True, None
    if "/" not in s:
        return False, f"{name}「{s}」须按 x.x.x.x/x 的 CIDR 格式填写"
    try:
        ipaddress.IPv4Interface(s)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}"
    return True, None

def _validate_ipv4_input(value, name="IP"):
    if not value or not value.strip():
        return True, None
    s = value.strip()
    if s.lower() == "dhcp":
        return True, None
    try:
        ipaddress.IPv4Address(s)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}"
    return True, None

def _validate_inner_nets(raw):
    nets = []
    errors = []
    for token in re.split(r'[\n,，\s]+', raw or ""):
        s = token.strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
            nets.append(str(net))
        except ValueError as e:
            errors.append((s, str(e)))
    return nets, errors

def validate_net_panel_values(wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
                              placeholder_wan_cidr, placeholder_wan_gw, placeholder_lan_cidr):
    errs = []
    if wan_ip and wan_ip.strip() and wan_ip.strip() not in (placeholder_wan_cidr, "dhcp"):
        ok, msg = _validate_cidr_input(wan_ip, "WAN IP")
        if not ok:
            errs.append(msg)
    if wan_gw and wan_gw.strip() and wan_gw.strip() not in (placeholder_wan_gw, "dhcp"):
        ok, msg = _validate_ipv4_input(wan_gw, "WAN网关")
        if not ok:
            errs.append(msg)
    if lan_ip and lan_ip.strip() and lan_ip.strip() != placeholder_lan_cidr:
        ok, msg = _validate_cidr_input(lan_ip, "LAN IP")
        if not ok:
            errs.append(msg)
    if lan_gw and lan_gw.strip() and lan_gw.strip() not in ("", placeholder_lan_cidr):
        ok, msg = _validate_ipv4_input(lan_gw, "LAN网关")
        if not ok:
            errs.append(msg)
    _, inner_errors = _validate_inner_nets(inner_raw)
    for frag, reason in inner_errors:
        errs.append(f"内网段「{frag}」格式错误：{reason}")
    return (len(errs) == 0, errs)

def compute_dhcp_range(lan_ip, lan_mask):
    try:
        net = ipaddress.IPv4Network(f'{lan_ip}/{lan_mask}', strict=False)
        hosts = list(net.hosts())
        if not hosts:
            return str(net.network_address + 1), str(net.broadcast_address - 1)
        start = str(hosts[1]) if len(hosts) > 2 else str(hosts[0])
        end   = str(hosts[-1])
        return start, end
    except Exception:
        parts = lan_ip.split('.')
        parts[-1] = '2'
        start = '.'.join(parts)
        parts[-1] = '254'
        end = '.'.join(parts)
        return start, end

def mask_to_prefix(mask):
    try:
        return ipaddress.IPv4Network(f'0.0.0.0/{mask}').prefixlen
    except Exception:
        return 24

def ip_to_mask(cidr_or_ip, mask='255.255.255.0'):
    """将 CIDR 或纯IP+mask 返回 (ip, mask) 格式"""
    return parse_ip_mask(cidr_or_ip, cidr_or_ip, mask)

def subnet_same_network(ip1, mask1, ip2, mask2):
    """判断两个IP是否在同一网段"""
    try:
        net1 = ipaddress.IPv4Network(f'{ip1}/{mask1}', strict=False)
        net2 = ipaddress.IPv4Network(f'{ip2}/{mask2}', strict=False)
        return net1 == net2
    except Exception:
        return False

def parse_extra_subnets(text):
    """解析额外内网段，返回 list of (network_str, mask_str, original_line)"""
    result = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            net = ipaddress.IPv4Network(line, strict=False)
            result.append((str(net.network_address), str(net.netmask), line))
        except Exception:
            # 尝试带空格的 IP MASK 格式
            parts = line.split()
            if len(parts) == 2:
                try:
                    net = ipaddress.IPv4Network(f'{parts[0]}/{parts[1]}', strict=False)
                    result.append((str(net.network_address), str(net.netmask), line))
                    continue
                except Exception:
                    pass
            # 无法解析，跳过
    return result

def parse_business_data(text):
    """解析运营商开通数据，自动填充字段"""
    data = {}
    lines = text.strip().splitlines()
    prefix = 'main'
    def _add_export_ips(pfx, s):
        if not s:
            return
        for part in re.split(r'[;\uff1b,，\s]+', s):
            part = clean_value(part).strip()
            if not part:
                continue
            # fakeIP-realIP 或 fakeIP-realIP-extraIP...（忽略第三个及之后的IP）
            m_map = re.match(
                r'^\s*(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—]\s*(\d{1,3}(?:\.\d{1,3}){3})(?:\s*[-–—]\s*\d{1,3}(?:\.\d{1,3}){3})*\s*$',
                part
            )
            if m_map:
                fake_ip = m_map.group(1)
                real_ip = m_map.group(2)
                data.setdefault(pfx + '_export_ips', []).append(fake_ip)
                data.setdefault(pfx + '_export_ip_map', {})[fake_ip] = real_ip
                continue
            for ip in re.findall(r'(\d{1,3}(?:\.\d{1,3}){3})', part):
                data.setdefault(pfx + '_export_ips', []).append(ip)

    for line in lines:
        line = line.strip()
        m = re.match(r'^主\s*IPSEC_PE\s*[：:]', line)
        if m: prefix = 'main'; data['main_dial_pe'] = safe_split(line, m.group()); continue
        m = re.match(r'^备\s*IPSEC_PE\s*[：:]', line)
        if m: prefix = 'backup'; data['backup_dial_pe'] = safe_split(line, m.group()); continue
        for pat, key_suffix in [
            (r'^拨号IP\s*[：:]', '_dial_ip'),
            (r'^loIP\s*[：:]', '_loopback'),
            (r'^认证ID\s*[：:]', '_auth_id'),
            (r'^预共享密钥\s*[：:]', '_psk'),
            (r'^PE对接\s*[：:]', '_peer_ip'),
            (r'^CE对接\s*[：:]', None),
            (r'^PE\s*[：:]', '_pe'),
            (r'^WANIP\s*[：:]', '_wanip'),
            (r'^TUNNEL\s*[：:]', '_tunnel'),
        ]:
            m = re.match(pat, line)
            if m and key_suffix:
                val = clean_value(safe_split(line, ':'))
                if not val:
                    val = clean_value(re.split(r'[：:]', line, maxsplit=1)[1] if re.search(r'[：:]', line) else '')
                data[prefix + key_suffix] = val
                break
        # 隧道IP：wanip1=PE侧(网络地址+1)，wanip2=CE侧(网络地址+2)
        m = re.match(r'^WANIP\s*[：:]\s*(.+)', line)
        if m:
            wanip_str = clean_value(m.group(1))
            try:
                net = ipaddress.IPv4Network(wanip_str, strict=False)
                base = int(net.network_address)
                data[prefix + '_wanip1'] = str(ipaddress.IPv4Address(base + 1))
                data[prefix + '_wanip2'] = str(ipaddress.IPv4Address(base + 2))
            except Exception:
                ip, _ = parse_ip_mask(wanip_str)
                data[prefix + '_wanip1'] = ip
                data[prefix + '_wanip2'] = ip
        # 出口ip
        if re.match(r'^出口\s*ip\s*[：:]', line, flags=re.I):
            data[prefix + '_in_export'] = True
            data[prefix + '_export_ips'] = []
            rest = clean_value(re.split(r'[：:]', line, maxsplit=1)[1]) if re.search(r'[：:]', line) else ''
            _add_export_ips(prefix, rest)
            continue
        if data.get(prefix + '_in_export'):
            if line and not re.match(r'^(主|备)\s*IPSEC_PE|^拨号IP|^loIP|^认证ID|^预共享密钥|^PE对接|^CE对接|^PE\s*[：:]|^WANIP|^TUNNEL|^LineID|^感兴趣流', line):
                _add_export_ips(prefix, line)
            else:
                data[prefix + '_in_export'] = False
    return data

def parse_business_data_hk(text):
    return parse_business_data(text)


def _build_usg_format_dict_common(text, is_hk=False, bgp_version=None):
    """可视化编辑器用：从业务文本 + 模块全局 DEFAULT_* 构建完整 format dict。"""
    g = globals()
    _p = "HK_" if is_hk else ""
    if bgp_version is None:
        bgp_version = str(g.get("DEFAULT_BGP_VERSION", "new")).strip()
    d = parse_business_data(text)
    if not d:
        return None, ("empty", [])

    # 检测数据头是否贴错场景（HK/US 交叉）
    # USG HK 数据头 PE 名字通常含 HK/hk（如 hkg1-fgpe3），US 数据头不含
    _pe_names = re.findall(r'PE[：:]\s*(\S+)', text)
    _has_hk_in_pe = any(re.search(r'[Hh][Kk]', pe) for pe in _pe_names)
    if is_hk and not _has_hk_in_pe:
        # HK 场景但 PE 名字不含 HK -> 可能贴了 US 数据头
        return None, ("wrong_scenario", "数据头可能为非香港出口格式（US），PE 名称中未检测到 HK 标识，请确认或切换到「非香港出口」场景")
    if not is_hk and _has_hk_in_pe:
        # US 场景但 PE 名字含 HK -> 可能贴了 HK 数据头
        return None, ("wrong_scenario", "数据头可能为香港出口格式（HK），PE 名称中检测到 HK 标识，请确认或切换到「HK 香港出口」场景")

    wan_dhcp = bool(g.get(_p + "DEFAULT_WAN_DHCP", False))
    lan_dhcp = bool(g.get(_p + "DEFAULT_LAN_DHCP", True))
    rr_enabled = bool(g.get(_p + "DEFAULT_GEN_RETURN_ROUTE", False))

    wan_ip_raw = str(g.get(_p + "DEFAULT_WAN_IP", "192.168.9.190/24"))
    wan_ip, wan_mask = parse_ip_mask(wan_ip_raw, "192.168.9.190", "255.255.255.0")
    wan_gw = str(g.get(_p + "DEFAULT_WAN_GW", "192.168.9.1"))
    lan_ip_raw = str(g.get(_p + "DEFAULT_LAN_IP", "192.168.8.1/24"))
    lan_ip, lan_mask = parse_ip_mask(lan_ip_raw, "192.168.8.1", "255.255.255.0")
    dns1 = str(g.get(_p + "DEFAULT_DNS1", "10.255.108.5" if is_hk else "10.255.108.7"))
    dns2 = str(g.get(_p + "DEFAULT_DNS2", "10.255.108.6" if is_hk else "10.255.108.58"))

    wan_eth = str(g.get(_p + "DEFAULT_WAN_ETH", "GE0/0/9"))
    lan_eth = str(g.get(_p + "DEFAULT_LAN_ETH", "GE0/0/8"))

    wan_mode_desc = "DHCP上网" if wan_dhcp else "静态上网"
    wan_if_block = build_wan_if_block(wan_ip, wan_mask, wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    wan_default_routes = build_wan_default_routes(wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    dns_dnat_block = build_dns_dnat_block(wan_ip, dhcp=wan_dhcp)

    # BGP server 选择（优先使用传入参数，fallback 到模块全局默认值）
    if bgp_version not in ("old", "new"):
        bgp_version = str(g.get("DEFAULT_BGP_VERSION", "new")).strip()
        if bgp_version not in ("old", "new"):
            bgp_version = "new"
    bm1, bm2, bb1, bb2 = _get_bgp_servers(bgp_version)
    bn1, bn2, bn3, bn4 = _get_bgp_server_names(bgp_version)

    if lan_dhcp:
        ds, de = compute_dhcp_range(lan_ip, lan_mask)
        dhcp_block = (
            f"\ndhcp enable\n"
            f"\ninterface {lan_eth}\n"
            f" ip address {lan_ip} {lan_mask}\n"
            f" dhcp select interface\n"
            f" dhcp server ip-range {ds} {de}\n"
            f" dhcp server gateway-list {lan_ip}\n"
            f" dhcp server dns-list {lan_ip}\n"
            f" service-manage all permit"
        )
    else:
        dhcp_block = (
            f"\ninterface {lan_eth}\n"
            f" ip address {lan_ip} {lan_mask}\n"
            f" service-manage all permit"
        )

    extra_routes_block = ""
    inner_raw = str(g.get(_p + "DEFAULT_INNER_NETS", ""))
    if rr_enabled and inner_raw.strip():
        lan_gw_raw = str(g.get(_p + "DEFAULT_LAN_GW", lan_ip_raw))
        rr_nexthop = lan_gw_raw.split("/")[0].strip() or lan_ip
        try:
            nets = _parse_inner_nets(inner_raw)
            if nets:
                subs = []
                for n in nets:
                    net_obj = ipaddress.ip_network(n, strict=False)
                    subs.append((str(net_obj.network_address), str(net_obj.netmask), n))
                extra_routes_block = build_extra_return_routes(subs, rr_nexthop)
        except Exception:
            pass

    def _g(k, default="（待填）"):
        return d.get(k, default)

    main_export_ips = d.get("main_export_ips", [])
    backup_export_ips = d.get("backup_export_ips", [])
    main_ip_map = d.get("main_export_ip_map", {})
    backup_ip_map = d.get("backup_export_ip_map", {})

    if is_hk:
        me = main_export_ips
        mlo = []
        for i, ip in enumerate(me):
            real = main_ip_map.get(ip)
            desc = f"Main-OUT-{i+1}({real})" if real else f"Main-OUT-{i+1}"
            mlo += [f"interface LoopBack{100+i}", f" description {desc}",
                    f" ip address {ip} 255.255.255.255"]
        _rid = (me[0] if me else "")
        if not _rid:
            m_lo = str(_g("main_loopback", ""))
            m_r = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', m_lo)
            _rid = m_r.group(1) if m_r else "0.0.0.0"
        return dict(
            wan_mode_desc=wan_mode_desc, wan_if_block=wan_if_block,
            wan_default_routes=wan_default_routes,
            dns_dnat_block=dns_dnat_block, dhcp_block=dhcp_block,
            wan_eth=wan_eth, lan_eth=lan_eth,
            wan_ip=wan_ip, wan_mask=wan_mask, wan_gw=wan_gw,
            lan_ip=lan_ip, dns_ip1=dns1, dns_ip2=dns2,
            main_lo_block="\n".join(mlo) or "#（主出口LoopBack待填）",
            main_nat_block=build_nat_groups_block(me, "MAIN"),
            main_snat_block=build_snat_rules_block(me, "MAIN", "Tunnel1000", "ToMainOUT"),
            backup_snat_block=build_snat_rules_block(me, "MAIN", "Tunnel2000", "ToBackOUT"),
            main_export_ip=_rid,
            main_export_natip=me[0] if me else "0.0.0.0",
            main_export_summary="\n".join(me) or "（待填）",
            backup_export_summary="\n".join(d.get("backup_export_ips", me)) or "（待填）",
            extra_return_routes=extra_routes_block,
            main_dial_pe=_g("main_dial_pe"), main_dial_ip=_g("main_dial_ip"),
            main_loopback=_g("main_loopback"), main_auth_id=_g("main_auth_id"),
            main_pe=_g("main_pe"), main_wanip=_g("main_wanip"),
            main_tunnel=_g("main_tunnel"), main_wanip1=_g("main_wanip1"),
            main_wanip2=_g("main_wanip2"), main_peer_ip=_g("main_peer_ip"),
            backup_dial_pe=_g("backup_dial_pe"), backup_dial_ip=_g("backup_dial_ip"),
            backup_loopback=_g("backup_loopback"), backup_auth_id=_g("backup_auth_id"),
            backup_pe=_g("backup_pe"), backup_wanip=_g("backup_wanip"),
            backup_tunnel=_g("backup_tunnel"), backup_wanip1=_g("backup_wanip1"),
            backup_wanip2=_g("backup_wanip2"), backup_peer_ip=_g("backup_peer_ip"),
            bgp_main_server1=bm1, bgp_main_server2=bm2,
            bgp_backup_server1=bb1, bgp_backup_server2=bb2,
            bgp_main_name1=bn1, bgp_main_name2=bn2,
            bgp_backup_name1=bn3, bgp_backup_name2=bn4,
        ), None

    main_lo_lines = []
    for i, ip in enumerate(main_export_ips):
        real = main_ip_map.get(ip)
        desc = f" description Main-OUT-{i+1}({real})" if real else f" description Main-OUT-{i+1}"
        main_lo_lines += [f"interface LoopBack{100+i}", desc,
                          f" ip address {ip} 255.255.255.255"]
    backup_lo_lines = []
    for i, ip in enumerate(backup_export_ips):
        real = backup_ip_map.get(ip)
        desc = f" description Backup-OUT-{i+1}({real})" if real else f" description Backup-OUT-{i+1}"
        backup_lo_lines += [f"interface LoopBack{200+i}", desc,
                            f" ip address {ip} 255.255.255.255"]
    return dict(
        wan_mode_desc=wan_mode_desc, wan_if_block=wan_if_block,
        wan_default_routes=wan_default_routes, dns_dnat_block=dns_dnat_block,
        extra_return_routes=extra_routes_block, dhcp_block=dhcp_block,
        wan_eth=wan_eth, lan_eth=lan_eth,
        wan_ip=wan_ip, wan_mask=wan_mask, wan_gw=wan_gw,
        lan_ip=lan_ip, dns_ip1=dns1, dns_ip2=dns2,
        main_lo_block="\n".join(main_lo_lines) or "#（主出口LoopBack待填）",
        backup_lo_block="\n".join(backup_lo_lines) or "#（备出口LoopBack待填）",
        main_nat_block=build_nat_groups_block(main_export_ips, "MAIN"),
        backup_nat_block=build_nat_groups_block(backup_export_ips, "BACKUP"),
        main_snat_block=build_snat_rules_block(main_export_ips, "MAIN", "Tunnel1000", "ToMainOUT"),
        backup_snat_block=build_snat_rules_block(backup_export_ips, "BACKUP", "Tunnel2000", "ToBackOUT"),
        main_export_natip=main_export_ips[0] if main_export_ips else "0.0.0.0",
        bgp_main_lo="LoopBack100",
        bgp_backup_lo="LoopBack200",
        main_export_summary="\n".join(main_export_ips) or "（待填）",
        backup_export_summary="\n".join(backup_export_ips) or "（待填）",
        main_dial_pe=_g("main_dial_pe"), main_dial_ip=_g("main_dial_ip"),
        main_loopback=_g("main_loopback"), main_auth_id=_g("main_auth_id"),
        main_pe=_g("main_pe"), main_wanip=_g("main_wanip"),
        main_tunnel=_g("main_tunnel"), main_wanip1=_g("main_wanip1"),
        main_wanip2=_g("main_wanip2"), main_peer_ip=_g("main_peer_ip"),
        backup_dial_pe=_g("backup_dial_pe"), backup_dial_ip=_g("backup_dial_ip"),
        backup_loopback=_g("backup_loopback"), backup_auth_id=_g("backup_auth_id"),
        backup_pe=_g("backup_pe"), backup_wanip=_g("backup_wanip"),
        backup_tunnel=_g("backup_tunnel"), backup_wanip1=_g("backup_wanip1"),
        backup_wanip2=_g("backup_wanip2"), backup_peer_ip=_g("backup_peer_ip"),
        bgp_main_server1=bm1, bgp_main_server2=bm2,
        bgp_backup_server1=bb1, bgp_backup_server2=bb2,
        bgp_main_name1=bn1, bgp_main_name2=bn2,
        bgp_backup_name1=bn3, bgp_backup_name2=bn4,
    ), None


def build_usg_us_format_dict(text, bgp_version=None):
    """可视化编辑器用：非香港出口。返回 (dict, fail)。"""
    return _build_usg_format_dict_common(text, is_hk=False, bgp_version=bgp_version)


def build_usg_hk_format_dict(text, bgp_version=None):
    """可视化编辑器用：HK 出口。返回 (dict, fail)。"""
    return _build_usg_format_dict_common(text, is_hk=True, bgp_version=bgp_version)


# ── 颜色 / 字体 ───────────────────────────────────────────────────────────────
BG        = '#f0f4f8'
BG_PANEL  = '#ffffff'
BG_INPUT  = '#f8fafc'
BG_HDR    = '#1e3a5f'
ACCENT    = '#0077b6'
ACCENT2   = '#e07b2a'
FG        = '#1a2b3c'
FG_DIM    = '#7a96ad'
FG_BRT    = '#ffffff'
BORDER    = '#c8d8e8'
BTN_BG    = '#005f94'
BTN_HOV   = '#b85e1a'
FONT_MONO = ('Consolas', 10)
FONT_UI   = ('Microsoft YaHei UI', 10)
FONT_HDR  = ('Microsoft YaHei UI', 12, 'bold')
FONT_TINY = ('Microsoft YaHei UI', 9)

# ── 滚动文本 + 右键菜单 ───────────────────────────────────────────────────────
def make_scrolled_text(parent, **kw):
    wrap = tk.Frame(parent, bg=BG_PANEL)
    vsb = ttk.Scrollbar(wrap, orient='vertical', style='Vertical.TScrollbar')
    vsb.pack(side='right', fill='y')
    kw.setdefault('bg', BG_INPUT)
    kw.setdefault('fg', FG)
    kw.setdefault('font', FONT_MONO)
    kw.setdefault('relief', 'flat')
    kw.setdefault('bd', 1)
    kw.setdefault('undo', True)
    t = tk.Text(wrap, yscrollcommand=vsb.set, **kw)
    t.pack(side='left', fill='both', expand=True)
    vsb.config(command=t.yview)
    # 右键菜单
    menu = tk.Menu(t, tearoff=0, bg=BG_PANEL, fg=FG, activebackground=ACCENT, activeforeground=FG_BRT)
    menu.add_command(label='复制  Ctrl+C', command=lambda: t.event_generate('<<Copy>>'))
    menu.add_command(label='剪切  Ctrl+X', command=lambda: t.event_generate('<<Cut>>'))
    menu.add_command(label='粘贴  Ctrl+V', command=lambda: t.event_generate('<<Paste>>'))
    menu.add_separator()
    menu.add_command(label='全选  Ctrl+A', command=lambda: t.tag_add('sel', '1.0', 'end-1c'))
    menu.add_separator()
    menu.add_command(label='撤销  Ctrl+Z', command=lambda: t.event_generate('<<Undo>>'))
    menu.add_command(label='重做  Ctrl+Y', command=lambda: t.event_generate('<<Redo>>'))
    def show_menu(e):
        try:
            has_sel = bool(t.tag_ranges('sel'))
            state = 'normal' if has_sel else 'disabled'
            menu.entryconfig('复制  Ctrl+C', state=state)
            menu.entryconfig('剪切  Ctrl+X', state=state)
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()
    t.bind('<Button-3>', show_menu)
    t.bind('<Button-2>', show_menu)
    return wrap, t

def section_label(parent, text, color=ACCENT):
    lbl = tk.Label(parent, text=text, bg=color, fg=FG_BRT, font=FONT_TINY,
                   anchor='w', padx=8, pady=3)
    lbl.pack(fill='x')
    return lbl

def flat_button(parent, text, command, color=BTN_BG, **kw):
    btn = tk.Label(parent, text=text, bg=color, fg=FG_BRT, font=FONT_UI,
                   cursor='hand2', relief='flat', padx=12, pady=5, **kw)
    btn.bind('<Button-1>', lambda e: command())
    btn.bind('<Enter>', lambda e: btn.config(bg=BTN_HOV))
    btn.bind('<Leave>', lambda e: btn.config(bg=color))
    return btn

# ── 核心逻辑：构建 wan_if_block、wan_default_routes、dns_dnat_block ───────────
def build_wan_if_block(wan_ip, wan_mask, wan_gw, dhcp=False, wan_eth=None):
    _we = wan_eth or DEFAULT_WAN_ETH
    _we_space = _we.replace("GE", "GE ") if _we.startswith("GE") else _we
    if dhcp:
        return (
            "2.2、WAN口DHCP上网\n"
            "#WAN接口，DHCP自动获取IP\n"
            f"interface {_we}\n"
            " description WAN-CT-DHCP\n"
            " ip address dhcp-alloc\n"
            " service-manage all permit\n"
            "#"
            "\n"
            "#配置DHCP方式下1.1.1.1路由（用于IPSec拨号）\n"
            f"ip route-static 1.1.1.1 32 {_we_space} dhcp"
        )
    else:
        return (
            f"2.2.3、静态IP地址\n"
            f"#WAN接口，允许http、ping通过wanip登录设备\n"
            f"interface {_we}\n"
            f" description WAN-CT-GW-{wan_gw}\n"
            f" ip address {wan_ip} {wan_mask}\n"
            f" service-manage all permit\n"
            f" \n"
            f"#\n"
            f"#配置静态默认路由以及IPsec对接路由\n"
            f"ip route-static 1.1.1.1 32 {wan_gw}\n"
            f"ip route-static 0.0.0.0 0.0.0.0 1.1.1.1 preference 222"
        )

def build_wan_default_routes(wan_gw, dhcp=False, wan_eth=None):
    _we = wan_eth or DEFAULT_WAN_ETH
    _we_space = _we.replace("GE", "GE ") if _we.startswith("GE") else _we
    if dhcp:
        return f"#WAN口为DHCP模式，默认路由已由 ip route-static 1.1.1.1 32 {_we_space} dhcp 处理"
    else:
        return (
            f"ip route-static 0.0.0.0 0.0.0.0 1.1.1.1 preference 222\n"
            f"ip route-static 1.1.1.1 32 {wan_gw}"
        )

def build_dns_dnat_block(wan_ip, dhcp=False):
    if dhcp:
        return (
            "#WAN口为DHCP，DNS拦截目标IP需在设备获取WAN IP后手动配置\n"
            "#destination-nat address-group DNS-IP 1\n"
            "# section 0 <WAN_IP> <WAN_IP>"
        )
    else:
        return (
            f"destination-nat address-group DNS-IP 1\n"
            f" section 0 {wan_ip} {wan_ip}"
        )

def build_extra_return_routes(subnets, nexthop):
    """为每个内网段生成一条回程静态路由（不写任何 # 注释）。"""
    if not subnets:
        return ''
    lines = ['']
    for net_addr, net_mask, _orig in subnets:
        lines.append(f'ip route-static {net_addr} {net_mask} {nexthop}')
    return '\n'.join(lines) + '\n'

def build_nat_groups_block(ips, prefix):
    """每个海外 IP 独立生成一个 nat address-group。
    prefix: 'MAIN' 或 'BACKUP'
    输出示例：
        nat address-group MAIN-OUT-IP1
         mode pat
         section 0 1.2.3.4 1.2.3.4
        nat address-group MAIN-OUT-IP2
         ...
    """
    if not ips:
        return f'#（{prefix} 出口 IP 待填，请手动添加 nat address-group）'
    lines = []
    for i, ip in enumerate(ips):
        lines.append(f'nat address-group {prefix}-OUT-IP{i+1}')
        lines.append(f' mode pat')
        lines.append(f' section 0 {ip} {ip}')
    return '\n'.join(lines)

def build_snat_rules_block(ips, nat_prefix, tunnel, rule_prefix):
    """每个海外 IP 独立生成一条 SNAT 规则。
    tunnel:     egress-interface，如 Tunnel1000
    rule_prefix: 规则名前缀，如 ToMainOUT 或 ToBackOUT
    输出示例（单 IP）：
        nat-policy
        rule name ToMainOUT-1
          source-zone trust
          ...
          action source-nat address-group MAIN-OUT-IP1
    """
    if not ips:
        return f'#（{nat_prefix} SNAT 规则待填）'
    lines = []
    for i, ip in enumerate(ips):
        group  = f'{nat_prefix}-OUT-IP{i+1}'
        rule   = f'{rule_prefix}-{i+1}'
        lines += [
            'nat-policy',
            f'rule name {rule}',
            '  source-zone trust',
            '  source-zone untrust',
            f'  egress-interface {tunnel}',
            '  source-address address-set LAN-IP',
            f'  action source-nat address-group {group}',
            '',
        ]
    return '\n'.join(lines).rstrip()

# ── 配置生成逻辑（非香港出口） ──────────────────────────────────────────────────
def generate_config_us(fields, wan_dhcp, extra_subnets_raw, return_route_nexthop, dhcp_en, net=None):
    wan_ip   = fields.get('wan_ip',   DEFAULT_WAN_IP)
    wan_mask = fields.get('wan_mask', DEFAULT_WAN_MASK)
    wan_gw   = fields.get('wan_gw',   DEFAULT_WAN_GW)
    wan_eth  = fields.get('wan_eth',  DEFAULT_WAN_ETH)
    lan_ip   = fields.get('lan_ip',   DEFAULT_LAN_IP)
    lan_mask = fields.get('lan_mask', DEFAULT_LAN_MASK)
    lan_eth  = fields.get('lan_eth',  DEFAULT_LAN_ETH)
    dns1     = fields.get('dns1',     DEFAULT_DNS1)
    dns2     = fields.get('dns2',     DEFAULT_DNS2)

    d = fields.get('parsed', {})

    wan_mode_desc = 'DHCP上网' if wan_dhcp else '静态上网'
    wan_if_block      = build_wan_if_block(wan_ip, wan_mask, wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    wan_default_routes= build_wan_default_routes(wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    dns_dnat_block    = build_dns_dnat_block(wan_ip, dhcp=wan_dhcp)

    if dhcp_en:
        dhcp_start, dhcp_end = compute_dhcp_range(lan_ip, lan_mask)
        prefix = mask_to_prefix(lan_mask)
        dhcp_block = (
            f"\ndhcp enable\n"
            f"\ninterface {lan_eth}\n"
            f" ip address {lan_ip} {lan_mask}\n"
            f" dhcp select interface\n"
            f" dhcp server ip-range {dhcp_start} {dhcp_end}\n"
            f" dhcp server gateway-list {lan_ip}\n"
            f" dhcp server dns-list {lan_ip}\n"      
            f" service-manage all permit"
        )
    else:
        dhcp_block = (
            f"\ninterface {lan_eth}\n"
            f" ip address {lan_ip} {lan_mask}\n"
            f" service-manage all permit"
        )

    # 内网段回程路由：只要 return_route_nexthop 非空就为每个 inner 网段下发，无 LAN 直连过滤
    extra_routes_block = ''
    extra_subnets = parse_extra_subnets(extra_subnets_raw)
    if extra_subnets and return_route_nexthop:
        extra_routes_block = build_extra_return_routes(extra_subnets, return_route_nexthop)

    # 组装 parsed 字段
    m = d
    main_export_ips  = m.get('main_export_ips', [])
    backup_export_ips= m.get('backup_export_ips', [])

    # LoopBack/NAT blocks
    main_lo_lines  = []
    backup_lo_lines= []
    main_ip_map   = m.get('main_export_ip_map', {})
    backup_ip_map = m.get('backup_export_ip_map', {})

    for idx2, ip in enumerate(main_export_ips):
        real = main_ip_map.get(ip)
        desc = f' description Main-OUT-{idx2+1}({real})' if real else f' description Main-OUT-{idx2+1}'
        main_lo_lines.append(f'interface LoopBack{100+idx2}')
        main_lo_lines.append(desc)
        main_lo_lines.append(f' ip address {ip} 255.255.255.255')
    for idx2, ip in enumerate(backup_export_ips):
        real = backup_ip_map.get(ip)
        desc = f' description Backup-OUT-{idx2+1}({real})' if real else f' description Backup-OUT-{idx2+1}'
        backup_lo_lines.append(f'interface LoopBack{200+idx2}')
        backup_lo_lines.append(desc)
        backup_lo_lines.append(f' ip address {ip} 255.255.255.255')

    main_lo_block   = '\n'.join(main_lo_lines)   if main_lo_lines   else '#（主出口LoopBack待填）'
    backup_lo_block  = '\n'.join(backup_lo_lines)  if backup_lo_lines  else '#（备出口LoopBack待填）'
    main_nat_block   = build_nat_groups_block(main_export_ips,   'MAIN')
    backup_nat_block  = build_nat_groups_block(backup_export_ips, 'BACKUP')
    main_snat_block  = build_snat_rules_block(main_export_ips,   'MAIN',   'Tunnel1000', 'ToMainOUT')
    backup_snat_block = build_snat_rules_block(backup_export_ips, 'BACKUP', 'Tunnel2000', 'ToBackOUT')

    main_export_natip  = main_export_ips[0]  if main_export_ips  else '0.0.0.0'
    main_export_summary= '\n'.join(main_export_ips)  if main_export_ips  else '（待填）'
    backup_export_summary='\n'.join(backup_export_ips) if backup_export_ips else '（待填）'
    # BGP connect-interface 始终使用主/备第一个出口IP对应的 LoopBack
    bgp_main_lo   = 'LoopBack100'
    bgp_backup_lo = f'LoopBack{200}' if backup_export_ips else 'LoopBack200'

    def g(k, default='（待填）'):
        return m.get(k, default)

    fmt_kw = dict(
        wan_mode_desc       = wan_mode_desc,
        wan_if_block        = wan_if_block,
        wan_default_routes  = wan_default_routes,
        dns_dnat_block      = dns_dnat_block,
        extra_return_routes = extra_routes_block,
        dhcp_block          = dhcp_block,
        wan_eth             = wan_eth,
        lan_eth             = lan_eth,
        wan_ip              = wan_ip,
        wan_mask            = wan_mask,
        wan_gw              = wan_gw,
        lan_ip              = lan_ip,
        dns_ip1             = dns1,
        dns_ip2             = dns2,
        main_lo_block       = main_lo_block,
        backup_lo_block     = backup_lo_block,
        main_nat_block      = main_nat_block,
        backup_nat_block    = backup_nat_block,
        main_snat_block     = main_snat_block,
        backup_snat_block   = backup_snat_block,
        main_export_natip   = main_export_natip,
        bgp_main_lo         = bgp_main_lo,
        bgp_backup_lo       = bgp_backup_lo,
        main_export_summary = main_export_summary,
        backup_export_summary=backup_export_summary,
        main_dial_pe        = g('main_dial_pe'),
        main_dial_ip        = g('main_dial_ip'),
        main_loopback       = g('main_loopback'),
        main_auth_id        = g('main_auth_id'),
        main_pe             = g('main_pe'),
        main_wanip          = g('main_wanip'),
        main_tunnel         = g('main_tunnel'),
        main_wanip1         = g('main_wanip1'),
        main_wanip2         = g('main_wanip2'),
        main_peer_ip        = g('main_peer_ip'),
        backup_dial_pe      = g('backup_dial_pe'),
        backup_dial_ip      = g('backup_dial_ip'),
        backup_loopback     = g('backup_loopback'),
        backup_auth_id      = g('backup_auth_id'),
        backup_pe           = g('backup_pe'),
        backup_wanip        = g('backup_wanip'),
        backup_tunnel       = g('backup_tunnel'),
        backup_wanip1       = g('backup_wanip1'),
        backup_wanip2       = g('backup_wanip2'),
        backup_peer_ip      = g('backup_peer_ip'),
        bgp_main_server1    = _NEW_BGP_MAIN_1,
        bgp_main_server2    = _NEW_BGP_MAIN_2,
        bgp_backup_server1  = _NEW_BGP_BACKUP_1,
        bgp_backup_server2  = _NEW_BGP_BACKUP_2,
        bgp_main_name1      = "hkg1-bgpserver5",
        bgp_main_name2      = "hkg1-bgpserver6",
        bgp_backup_name1    = "szd-bgpserver5",
        bgp_backup_name2    = "szd-bgpserver6",
    )
    if net:
        inject_usg_template_init_aliases(fmt_kw, net)
    if field_coverage:
        miss = field_coverage.missing_template_fields(
            TEMPLATE_USG_NONHK, fmt_kw, skip=_USG_NONHK_COVER_SKIP)
        field_coverage.show_generation_coverage_notice(
            messagebox, miss, "USG FastIP · 非香港出口")
    return TEMPLATE_USG_NONHK.format(**fmt_kw)

# =====================================================================
# 内网段工具函数
# =====================================================================
def _parse_inner_nets(raw):
    nets = []
    for token in re.split(r'[\n,，\s]+', raw or ''):
        s = token.strip()
        if not s or s.startswith('#'):
            continue
        try:
            nets.append(str(ipaddress.ip_network(s, strict=False)))
        except ValueError:
            pass
    return nets

def _nets_needing_return(lan_ip, lan_mask, inner_nets):
    try:
        lan_net = ipaddress.IPv4Network(f'{lan_ip}/{lan_mask}', strict=False)
        result = []
        for n in inner_nets:
            try:
                snet = ipaddress.ip_network(n, strict=False)
                if snet != lan_net:
                    result.append(n)
            except Exception:
                pass
        return result
    except Exception:
        return inner_nets

# =====================================================================
# GUI 主题
# =====================================================================
BG        = "#f0f4f8"
BG_PANEL  = "#ffffff"
BG_INPUT  = "#f8fafc"
BG_HDR    = "#1e3a5f"
ACCENT_US = "#0077b6"
ACCENT_HK = "#e07b2a"
FG        = "#1a2b3c"
FG_DIM    = "#7a96ad"
FG_BRT    = "#ffffff"
BORDER    = "#c8d8e8"
FONT_MONO = ("Consolas", 10)
FONT_UI   = ("微软雅黑", 10)
FONT_HDR  = ("微软雅黑", 11, "bold")
FONT_TINY = ("Consolas",  9)

if __name__ == "__main__" and "--selftest-parse" in sys.argv:
    raw_b = b""
    if "--file" in sys.argv:
        try:
            p = sys.argv[sys.argv.index("--file") + 1]
        except Exception:
            p = ""
        if p:
            with open(p, "rb") as f:
                raw_b = f.read()
    if not raw_b:
        raw_b = sys.stdin.buffer.read()
    # PowerShell 管道常见是 UTF-16LE（会带大量 \x00），这里做一次自适应解码
    if b"\x00" in raw_b[:200]:
        raw = raw_b.decode("utf-16", errors="ignore")
    else:
        for _enc in ("utf-8-sig", "utf-8", "gbk", "cp936"):
            try:
                raw = raw_b.decode(_enc)
                break
            except Exception:
                raw = raw_b.decode("utf-8", errors="ignore")
    d = parse_business_data(raw)
    me = d.get("main_export_ips", [])
    be = d.get("backup_export_ips", [])
    m_lo = str(d.get("main_loopback", ""))
    m_rid = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", m_lo)
    rid = me[0] if me else (m_rid.group(1) if m_rid else "0.0.0.0")
    print("main_export_ips=" + ",".join(me))
    print("backup_export_ips=" + ",".join(be))
    print("hk_router_id=" + rid)
    raise SystemExit(0)

root = tk.Tk()
root.title("USG FastIP 配置生成工具")
_sw = root.winfo_screenwidth()
_sh = root.winfo_screenheight()
_ww = min(1300, int(_sw * 0.88))
_wh = min(820,  int(_sh * 0.84))
root.geometry(f"{_ww}x{_wh}+{(_sw-_ww)//2}+{max(0,(_sh-_wh)//2-20)}")
root.minsize(900, 600)
root.configure(bg=BG)

sty = ttk.Style(root)
sty.theme_use("clam")
sty.configure("TPanedwindow", background=BG)
sty.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
               arrowcolor=FG_DIM, relief="flat", borderwidth=0, width=8)
sty.map("Vertical.TScrollbar", background=[("active", ACCENT_US)])
sty.configure("TNotebook", tabposition="nw", background=BG_HDR)
sty.configure("TNotebook.Tab", background=BG_HDR, foreground="#7aafd4",
               font=("微软雅黑", 11, "bold"), padding=[20, 8])
sty.map("TNotebook.Tab",
        background=[("selected", BG), ("active", "#2a4a6f")],
        foreground=[("selected", ACCENT_US), ("active", FG_BRT)])

def make_text(parent, readonly=False, **kw):
    vsb = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
    vsb.pack(side="right", fill="y")
    t = tk.Text(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG,
                insertbackground=ACCENT_US, selectbackground=ACCENT_US,
                selectforeground=BG, relief="flat", bd=0, padx=10, pady=6,
                yscrollcommand=vsb.set,
                state=(tk.DISABLED if readonly else tk.NORMAL), **kw)
    t.pack(side="left", fill="both", expand=True)
    vsb.configure(command=t.yview)
    menu = tk.Menu(t, tearoff=0, bg=BG_PANEL, fg=FG,
                   activebackground=ACCENT_US, activeforeground=FG_BRT,
                   font=FONT_UI, bd=0, relief="flat")
    menu.add_command(label="复制",  command=lambda: t.event_generate("<<Copy>>"))
    menu.add_command(label="剪切",  command=lambda: t.event_generate("<<Cut>>"))
    menu.add_command(label="粘贴",  command=lambda: t.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="全选",  command=lambda: (t.tag_add("sel", "1.0", "end"), None))
    menu.add_separator()
    menu.add_command(label="撤销",  command=lambda: t.event_generate("<<Undo>>"))
    menu.add_command(label="重做",  command=lambda: t.event_generate("<<Redo>>"))
    def _show_menu(event):
        has_sel = bool(t.tag_ranges("sel"))
        menu.entryconfig("复制", state="normal" if has_sel else "disabled")
        menu.entryconfig("剪切", state="normal" if (has_sel and not readonly) else "disabled")
        menu.entryconfig("粘贴", state="normal" if not readonly else "disabled")
        menu.entryconfig("撤销", state="normal" if not readonly else "disabled")
        menu.entryconfig("重做", state="normal" if not readonly else "disabled")
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()
    t.bind("<Button-3>", _show_menu)
    t.bind("<Button-2>", _show_menu)
    t.config(undo=True, maxundo=50)
    return t

def flat_btn(parent, text, color):
    darker = {"#e07b2a": "#b85e1a", "#0077b6": "#005f94",
              "#6c757d": "#565e64", "#16a085": "#0e7060"}.get(color, color)
    b = tk.Label(parent, text=text, font=("微软雅黑", 10, "bold"),
                 bg=color, fg=FG_BRT, padx=14, pady=7, cursor="hand2", relief="flat")
    b.bind("<Enter>", lambda e: b.config(bg=darker))
    b.bind("<Leave>", lambda e: b.config(bg=color))
    return b

def mk_entry(parent, row, col, placeholder, accent, width=18):
    e = tk.Entry(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG_DIM,
                 insertbackground=accent, relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=accent, width=width)
    e.grid(row=row, column=col, sticky="ew", pady=3, padx=(0, 8))
    e.insert(0, placeholder)
    def _fi(ev, en=e, p=placeholder):
        if en.get() == p: en.delete(0, tk.END); en.config(fg=FG)
    def _fo(ev, en=e, p=placeholder):
        if not en.get().strip(): en.insert(0, p); en.config(fg=FG_DIM)
    e.bind("<FocusIn>",  _fi)
    e.bind("<FocusOut>", _fo)
    return e

# ── 根布局 ──────────────────────────────────────────────────────────
root.columnconfigure(0, weight=1)
root.rowconfigure(1, weight=1)

hdr = tk.Frame(root, bg=BG_HDR, height=46)
hdr.grid(row=0, column=0, sticky="ew"); hdr.grid_propagate(False)
tk.Frame(hdr, bg="#16a085", width=4).pack(side="left", fill="y")
tk.Label(hdr, text="  USG FastIP", font=("微软雅黑", 13, "bold"),
         bg=BG_HDR, fg=FG_BRT).pack(side="left")
tk.Label(hdr, text="  配置生成工具-单机", font=FONT_HDR, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=4)
right_badges = tk.Frame(hdr, bg=BG_HDR)
right_badges.pack(side="right", padx=14, pady=10)
badge_font = ("微软雅黑", 9, "bold")
tk.Label(right_badges, text=" v5 ", font=badge_font, bg="#16a085", fg=FG_BRT,
         padx=12, pady=4).pack(side="right")
tk.Label(right_badges, text=" 深圳工程部系列宝典 ", font=badge_font, bg="#6c757d", fg=FG_BRT,
         padx=10, pady=4).pack(side="right", padx=(0, 8))

main_nb = ttk.Notebook(root)
main_nb.grid(row=1, column=0, sticky="nsew")
tab_us = tk.Frame(main_nb, bg=BG)
tab_hk = tk.Frame(main_nb, bg=BG)
tab_fl = tk.Frame(main_nb, bg=BG)
main_nb.add(tab_hk, text="  🇭🇰 香港出口  ")
main_nb.add(tab_us, text="  非香港出口  ")
main_nb.add(tab_fl, text="  🔗 其他小功能  ")

# =====================================================================
# 初始化配置面板
# 布局顺序：骨干DNS → 分隔 → WAN DHCP + LAN DHCP（同行）→ WAN IP/网关
#           → LAN IP/LAN网关 → 分隔 → 内网段 → 状态与回程路由开关（同一行）
# =====================================================================
def build_net_panel(parent, accent, wan_dhcp_default=False, lan_dhcp_default=True,
                    dns1_default=DEFAULT_DNS1, dns2_default=DEFAULT_DNS2,
                    gkey_prefix=""):
    hdr_f = tk.Frame(parent, bg=accent, height=26)
    hdr_f.pack(fill="x"); hdr_f.pack_propagate(False)
    tk.Frame(hdr_f, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(hdr_f, text="  初始化配置", font=("微软雅黑", 10, "bold"),
             bg=accent, fg=FG_BRT).pack(side="left", pady=2)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    body = tk.Frame(parent, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=2, pady=2)
    # 4列：col0=标签  col1=输入框  col2=标签  col3=输入框
    # 两侧列宽等权，各有最小宽度防止互相遮挡
    body.columnconfigure(0, minsize=72)
    body.columnconfigure(1, weight=1, minsize=90)
    body.columnconfigure(2, minsize=92)  # 保证“网关/LAN网关”等标签完整显示
    body.columnconfigure(3, weight=1, minsize=90)

    LBL  = dict(font=("微软雅黑", 9), bg=BG_PANEL, fg=FG_DIM, anchor="e")
    PAD  = dict(padx=(2, 4), pady=2)   # 对齐 er_fastip_2in1_v7.py 的紧凑排版
    EPAD = dict(padx=(0, 4), pady=2)

    def small_entry(row, col, ph, colspan=1):
        e = tk.Entry(body, font=("Consolas", 9), bg=BG_INPUT, fg=FG_DIM,
                     insertbackground=accent, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=accent)
        e.grid(row=row, column=col, columnspan=colspan, sticky="ew", **EPAD)
        e.insert(0, ph)
        def _fi(ev, en=e, p=ph):
            if en.get() == p: en.delete(0, tk.END); en.config(fg=FG)
        def _fo(ev, en=e, p=ph):
            if not en.get().strip(): en.insert(0, p); en.config(fg=FG_DIM)
        e.bind("<FocusIn>",  _fi)
        e.bind("<FocusOut>", _fo)
        return e

    def toggle_btn(row, col):
        b = tk.Label(body, font=("微软雅黑", 8, "bold"),
                     padx=8, pady=3, cursor="hand2", relief="flat")
        b.grid(row=row, column=col, sticky="w", **EPAD)
        return b

    def sep(r):
        tk.Frame(body, bg=BORDER, height=1).grid(
            row=r, column=0, columnspan=4, sticky="ew", pady=(3, 1))

    r = 0
    # ── 骨干 DNS ────────────────────────────────────────────────────
    tk.Label(body, text="骨干DNS主", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    e_dns1 = small_entry(r, 1, dns1_default)
    tk.Label(body, text="骨干DNS备", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    e_dns2 = small_entry(r, 3, dns2_default); r += 1

    sep(r); r += 1

    # ── WAN 组：DHCP开关 + IP + 网关 ────────────────────────────────
    tk.Label(body, text="WAN DHCP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    wan_dhcp_var = tk.BooleanVar(value=bool(globals().get("DEFAULT_WAN_DHCP", wan_dhcp_default)))
    tk.Label(body, text="DHCP", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    wan_dhcp_btn = toggle_btn(r, 3)
    r += 1
    tk.Label(body, text="WAN IP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    e_wan_ip = small_entry(r, 1, DEFAULT_WAN_IP)
    tk.Label(body, text="网关", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    e_wan_gw = small_entry(r, 3, DEFAULT_WAN_GW); r += 1

    sep(r); r += 1

    # ── LAN 组：DHCP开关 + IP + 网关 ────────────────────────────────
    tk.Label(body, text="LAN DHCP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    lan_dhcp_var = tk.BooleanVar(value=bool(globals().get("DEFAULT_LAN_DHCP", lan_dhcp_default)))
    tk.Label(body, text="DHCP", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    lan_dhcp_btn = toggle_btn(r, 3)
    r += 1
    tk.Label(body, text="LAN IP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    e_lan_ip = small_entry(r, 1, DEFAULT_LAN_IP)
    tk.Label(body, text="LAN网关", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    e_lan_gw = small_entry(r, 3, DEFAULT_LAN_IP); r += 1

    sep(r); r += 1

    # ── 客户内网段 ────────────────────────────────────────────────────
    tk.Label(body, text="内网段", font=("微软雅黑", 9), bg=BG_PANEL, fg=FG_DIM,
             anchor="ne").grid(row=r, column=0, sticky="ne", **PAD)
    inner_wrap = tk.Frame(body, bg=BG_INPUT, highlightthickness=1,
                          highlightbackground=BORDER, highlightcolor=accent)
    inner_wrap.grid(row=r, column=1, columnspan=3, sticky="ew", **EPAD)
    e_inner = tk.Text(inner_wrap, font=("Consolas", 9), bg=BG_INPUT, fg=FG,
                      height=2, relief="flat", bd=0, padx=4, pady=3,
                      insertbackground=accent)
    e_inner.pack(fill="both", expand=True)
    e_inner.insert("1.0", DEFAULT_INNER_NETS)
    tk.Label(body, text="换行或逗号分隔多条", font=("Consolas", 7),
             bg=BG_PANEL, fg=FG_DIM, anchor="w").grid(
        row=r+1, column=1, columnspan=3, sticky="w", padx=(0, 4))
    r += 2

    # ── 内网段状态 + 回程路由（同一行：提示左、开关右，省一行高度）
    rr_strip = tk.Frame(body, bg=BG_PANEL)
    rr_strip.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(0, 1))
    rr_strip.columnconfigure(0, weight=1)
    r += 1

    status_inner_var = tk.StringVar(value="")
    lbl_inner = tk.Label(
        rr_strip, textvariable=status_inner_var,
        font=("微软雅黑", 8), bg=BG_PANEL,
        anchor="w", wraplength=220, justify="left",
    )
    lbl_inner.grid(row=0, column=0, sticky="w", padx=(4, 4))

    rr_tail = tk.Frame(rr_strip, bg=BG_PANEL)
    rr_tail.grid(row=0, column=1, sticky="e", padx=(4, 4))
    tk.Label(rr_tail, text="回程路由", **LBL, width=8).pack(side="left", padx=(0, 4))
    return_route_var = tk.BooleanVar(value=bool(globals().get("DEFAULT_GEN_RETURN_ROUTE", False)))
    rr_btn = tk.Label(rr_tail, font=("微软雅黑", 8, "bold"),
                      padx=8, pady=3, cursor="hand2", relief="flat")
    rr_btn.pack(side="left")
    rr_tail.grid_remove()

    # ── 逻辑 ─────────────────────────────────────────────────────────
    def _pv(entry, placeholder):
        v = entry.get().strip()
        return "" if v == placeholder else v

    def _real_lan_ip():
        v = _pv(e_lan_ip, DEFAULT_LAN_IP)
        return v if v else DEFAULT_LAN_IP

    def _real_lan_gw():
        v = e_lan_gw.get().strip()
        if not v or v == DEFAULT_LAN_IP:
            return _real_lan_ip().split('/')[0]  # LAN网关默认同 LAN IP
        return v

    def _update_rr_btn():
        on = return_route_var.get()
        rr_btn.config(text="● 生成回程路由" if on else "○ 不生成",
                      bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    def _check_inner(*_):
        lan_raw = _real_lan_ip()
        lan_ip_part, lan_mask_part = parse_ip_mask(lan_raw, DEFAULT_LAN_IP, DEFAULT_LAN_MASK)
        inner_raw = e_inner.get("1.0", tk.END)
        nets = _parse_inner_nets(inner_raw)
        if not nets:
            status_inner_var.set("⚠  未填写有效内网段")
            lbl_inner.config(fg="#c0392b"); rr_tail.grid_remove(); return
        outside = _nets_needing_return(lan_ip_part, lan_mask_part, nets)
        if not outside:
            status_inner_var.set("✓  LAN IP 在所有内网段内")
            lbl_inner.config(fg="#16a085"); rr_tail.grid_remove()
        else:
            preview = " ".join(outside[:2]) + ("…" if len(outside) > 2 else "")
            status_inner_var.set(f"⚠  {len(outside)}条需回程路由：{preview}")
            lbl_inner.config(fg="#e07b2a")
            rr_tail.grid(); _update_rr_btn()

    rr_btn.bind("<Button-1>", lambda e: (
        return_route_var.set(not return_route_var.get()), _update_rr_btn()))

    def _update_wan_dhcp():
        on = wan_dhcp_var.get()
        wan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)
        if on:
            # 变灰 + 写入"dhcp" + 禁止输入
            for en in (e_wan_ip, e_wan_gw):
                en.config(state=tk.NORMAL)
                en.delete(0, tk.END)
                en.insert(0, "dhcp")
                en.config(state=tk.DISABLED, bg="#d8dfe8", fg="#8a9aaa",
                          disabledbackground="#d8dfe8", disabledforeground="#8a9aaa")
        else:
            # 恢复正常
            for en, ph in ((e_wan_ip, DEFAULT_WAN_IP), (e_wan_gw, DEFAULT_WAN_GW)):
                en.config(state=tk.NORMAL, bg=BG_INPUT, fg=FG_DIM,
                          disabledbackground="#d8dfe8", disabledforeground="#8a9aaa")
                en.delete(0, tk.END)
                en.insert(0, ph)

    def _update_lan_dhcp():
        on = lan_dhcp_var.get()
        lan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    _update_wan_dhcp(); _update_lan_dhcp(); _update_rr_btn()
    wan_dhcp_btn.bind("<Button-1>", lambda e: (wan_dhcp_var.set(not wan_dhcp_var.get()), _update_wan_dhcp()))
    lan_dhcp_btn.bind("<Button-1>", lambda e: (lan_dhcp_var.set(not lan_dhcp_var.get()), _update_lan_dhcp()))
    e_lan_ip.bind("<FocusOut>",   _check_inner)
    e_lan_ip.bind("<KeyRelease>", _check_inner)
    e_inner.bind("<KeyRelease>",  _check_inner)
    e_inner.bind("<FocusOut>",    _check_inner)
    root.after(120, _check_inner)

    # ── 对外接口 ─────────────────────────────────────────────────────
    def get_raw_cfg():
        return dict(
            wan_dhcp=wan_dhcp_var.get(),
            wan_ip=e_wan_ip.get().strip(),
            wan_gw=e_wan_gw.get().strip(),
            lan_ip=e_lan_ip.get().strip(),
            lan_gw=e_lan_gw.get().strip(),
            inner_raw=e_inner.get("1.0", tk.END),
        )

    def get_net_cfg():
        g0 = globals()
        _p = gkey_prefix
        wan_ip_raw = _pv(e_wan_ip, DEFAULT_WAN_IP) or DEFAULT_WAN_IP
        wan_ip, wan_mask = parse_ip_mask(wan_ip_raw, DEFAULT_WAN_IP, DEFAULT_WAN_MASK)
        wan_gw = _pv(e_wan_gw, DEFAULT_WAN_GW) or DEFAULT_WAN_GW
        wan_eth = str(g0.get(_p + "DEFAULT_WAN_ETH", DEFAULT_WAN_ETH))
        lan_ip_raw = _pv(e_lan_ip, DEFAULT_LAN_IP) or DEFAULT_LAN_IP
        lan_ip, lan_mask = parse_ip_mask(lan_ip_raw, DEFAULT_LAN_IP, DEFAULT_LAN_MASK)
        lan_eth = str(g0.get(_p + "DEFAULT_LAN_ETH", DEFAULT_LAN_ETH))
        dns1 = _pv(e_dns1, dns1_default) or dns1_default
        dns2 = _pv(e_dns2, dns2_default) or dns2_default
        inner_raw = e_inner.get("1.0", tk.END)
        rr_nexthop = _real_lan_gw() if return_route_var.get() else ""
        lan_ip_cidr = _pv(e_lan_ip, DEFAULT_LAN_IP) or DEFAULT_LAN_IP
        if wan_dhcp_var.get():
            wan_ip_cidr = str(g0.get(_p + "DEFAULT_WAN_IP", DEFAULT_WAN_IP))
        else:
            wan_ip_cidr = _pv(e_wan_ip, DEFAULT_WAN_IP) or DEFAULT_WAN_IP
        lan_gw_eff = _real_lan_gw()
        return dict(wan_dhcp=wan_dhcp_var.get(), wan_ip=wan_ip, wan_mask=wan_mask,
                    wan_gw=wan_gw, wan_eth=wan_eth, lan_ip=lan_ip, lan_mask=lan_mask,
                    lan_eth=lan_eth, lan_dhcp=lan_dhcp_var.get(), dns1=dns1, dns2=dns2,
                    inner_raw=inner_raw, rr_nexthop=rr_nexthop,
                    lan_ip_cidr=lan_ip_cidr, wan_ip_cidr=wan_ip_cidr, lan_gw=lan_gw_eff)

    def reset_net():
        g0 = globals()
        _p = gkey_prefix
        wan_dhcp_var.set(bool(g0.get(_p + "DEFAULT_WAN_DHCP", wan_dhcp_default)))
        lan_dhcp_var.set(bool(g0.get(_p + "DEFAULT_LAN_DHCP", lan_dhcp_default)))
        _update_wan_dhcp(); _update_lan_dhcp()
        _wip = str(g0.get(_p + "DEFAULT_WAN_IP", DEFAULT_WAN_IP))
        _wgw = str(g0.get(_p + "DEFAULT_WAN_GW", DEFAULT_WAN_GW))
        _lip = str(g0.get(_p + "DEFAULT_LAN_IP", DEFAULT_LAN_IP))
        _lgw = str(g0.get(_p + "DEFAULT_LAN_GW", "")).strip() or _lip
        _dns1 = str(g0.get(_p + "DEFAULT_DNS1", dns1_default))
        _dns2 = str(g0.get(_p + "DEFAULT_DNS2", dns2_default))
        _inner = str(g0.get(_p + "DEFAULT_INNER_NETS", DEFAULT_INNER_NETS))
        for en, ph in [(e_wan_ip, _wip), (e_wan_gw, _wgw),
                       (e_lan_ip, _lip), (e_lan_gw, _lgw),
                       (e_dns1, _dns1), (e_dns2, _dns2)]:
            en.config(state=tk.NORMAL)
            en.delete(0, tk.END); en.insert(0, ph); en.config(fg=FG_DIM)
        e_inner.delete("1.0", tk.END); e_inner.insert("1.0", _inner)
        return_route_var.set(bool(g0.get(_p + "DEFAULT_GEN_RETURN_ROUTE", False)))
        _update_rr_btn(); rr_tail.grid_remove()
        root.after(50, _check_inner)

    return get_net_cfg, get_raw_cfg, reset_net


# =====================================================================
# Tab 框架构建器（四象限可拖动布局）
# 左上：备注/示例  右上：初始化配置  左下：数据输入  右下：生成结果
# =====================================================================
def build_tab_shell(tab, accent, note_text, example_text, init_parent):
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)

    # 垂直 PanedWindow（上半 | 下半）
    v_pane = ttk.PanedWindow(tab, orient="vertical")
    v_pane.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 0))

    # 上半：水平 PanedWindow（备注 | 初始化）
    top_h = ttk.PanedWindow(v_pane, orient="horizontal")
    v_pane.add(top_h, weight=1)

    # 左上：备注/示例
    notes_f = tk.Frame(top_h, bg=BG_PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
    top_h.add(notes_f, weight=1)
    notes_f.rowconfigure(0, weight=1); notes_f.columnconfigure(0, weight=1)
    nb = ttk.Notebook(notes_f); nb.grid(row=0, column=0, sticky="nsew")
    tn = tk.Frame(nb, bg=BG_PANEL); nb.add(tn, text="  备注说明  ")
    nt = tk.Text(tn, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat",
                 bd=0, padx=10, pady=4)
    nt.pack(fill="both", expand=True); nt.insert(tk.END, note_text); nt.config(state="disabled")
    te = tk.Frame(nb, bg=BG_PANEL); nb.add(te, text="  填写示例  ")
    ew = tk.Frame(te, bg=BG_PANEL); ew.pack(fill="both", expand=True)
    evsb = ttk.Scrollbar(ew, orient="vertical", style="Vertical.TScrollbar"); evsb.pack(side="right", fill="y")
    et = tk.Text(ew, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat",
                 bd=0, padx=10, pady=4, yscrollcommand=evsb.set)
    et.pack(side="left", fill="both", expand=True); evsb.config(command=et.yview)
    et.insert(tk.END, example_text); et.config(state="disabled")

    # 右上：初始化配置
    init_f = tk.Frame(top_h, bg=BG_PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
    top_h.add(init_f, weight=2)
    init_parent[0] = init_f

    # 下半：水平 PanedWindow（数据输入 | 生成结果）
    bot_h = ttk.PanedWindow(v_pane, orient="horizontal")
    v_pane.add(bot_h, weight=1)

    def make_bot_side(label_text):
        f = tk.Frame(bot_h, bg=BG_PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
        bot_h.add(f, weight=1)
        f.rowconfigure(1, weight=1); f.columnconfigure(0, weight=1)
        h = tk.Frame(f, bg=accent, height=26); h.grid(row=0, column=0, sticky="ew")
        h.grid_propagate(False)
        tk.Frame(h, bg=FG_BRT, width=3).pack(side="left", fill="y")
        tk.Label(h, text=f"  {label_text}", font=FONT_HDR, bg=accent, fg=FG_BRT, pady=2).pack(side="left")
        inner = tk.Frame(f, bg=BG_INPUT); inner.grid(row=1, column=0, sticky="nsew")
        return inner

    li = make_bot_side("数据头输入")
    ri = make_bot_side("生成结果")
    left_text    = make_text(li)
    right_output = make_text(ri)

    # 上下各50%
    def _init_sash(vp=v_pane):
        try:
            total = vp.winfo_height()
            if total > 100:
                vp.sashpos(0, total // 2)
        except Exception:
            pass
    tab.after(150, _init_sash)
    tab.after(600, _init_sash)

    # 状态栏（固定在底部）
    tk.Frame(tab, bg=BORDER, height=1).grid(row=1, column=0, sticky="ew")
    btm = tk.Frame(tab, bg=BG_HDR, height=42)
    btm.grid(row=2, column=0, sticky="ew"); btm.grid_propagate(False)
    tab.rowconfigure(1, weight=0); tab.rowconfigure(2, weight=0)
    status_var = tk.StringVar(value="就绪  ·  等待输入业务数据")
    tk.Label(btm, textvariable=status_var, font=FONT_TINY, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=12)
    btn_exp = flat_btn(btm, "导出 TXT", "#16a085"); btn_exp.pack(side="right", padx=(0, 12), pady=7)
    btn_gen = flat_btn(btm, "⚡  生成配置", accent);  btn_gen.pack(side="right", padx=(0, 5), pady=7)
    btn_rst = flat_btn(btm, "↺  恢复初始", "#6c757d"); btn_rst.pack(side="right", padx=(0, 5), pady=7)
    return left_text, right_output, status_var, btn_gen, btn_exp, btn_rst


# =====================================================================
# Tab 非香港出口
# =====================================================================
US_NOTE = (
    "• WAN IP / LAN IP 请按 x.x.x.x/x 的 CIDR 格式填写，例如 192.168.9.190/24\n"
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
    "• 请自行修改nat/dns/mtu等部分。\n"
    "• nat只会打第一个出口ip的。其余ip请自行添加。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
US_EXAMPLE = (
    "主 IPSEC_PE: szd-ape2\n"
    "拨号IP：121.14.82.235\n"
    "loIP：10.18.12.57\n"
    "感兴趣流：10.18.12.57/32 ～ 10.255.108.0/22\n"
    "认证ID：609157A1\n"
    "预共享密钥：both-win\n\n"
    "LineID:609157A1\n"
    "PE：lax1-fgpe1\n"
    "WANIP: 10.22.98.40/30\n"
    "TUNNEL: tun1213\n"
    "PE对接：10.255.110.6\n"
    "CE对接：10.18.12.57\n"
    "出口ip：10.61.10.49-64.81.158.21\n\n"
    "备 IPSEC_PE: szc-apebk2\n"
    "拨号IP：120.133.138.20\n"
    "loIP：10.18.14.21\n"
    "认证ID：609157A2\n"
    "预共享密钥：both-win\n\n"
    "LineID:609157A2\n"
    "PE：sjc1-fgpe1\n"
    "WANIP: 10.22.32.60/30\n"
    "TUNNEL: tun2305\n"
    "PE对接：10.255.111.128\n"
    "出口ip：10.60.57.87-172.16.14.118\n"
)

us_init_container = [None]
us_left, us_right, us_status, us_gen, us_exp, us_rst = build_tab_shell(
    tab_us, ACCENT_US, US_NOTE, US_EXAMPLE, us_init_container)
us_get_net, us_get_net_raw, us_reset_net = build_net_panel(
    us_init_container[0], ACCENT_US, wan_dhcp_default=False, lan_dhcp_default=True)

us_parsed = {}

def us_generate():
    raw = us_left.get("1.0", tk.END).strip()
    if not raw: us_status.set("⚠  请先输入业务数据"); return
    raw_net = us_get_net_raw()
    ok, errs = validate_net_panel_values(
        "" if raw_net["wan_dhcp"] else raw_net["wan_ip"],
        "" if raw_net["wan_dhcp"] else raw_net["wan_gw"],
        raw_net["lan_ip"],
        raw_net["lan_gw"],
        raw_net["inner_raw"],
        DEFAULT_WAN_IP, DEFAULT_WAN_GW, DEFAULT_LAN_IP
    )
    if not ok:
        messagebox.showwarning("网络格式校验未通过", "\n".join(errs))
        us_status.set("⚠  请修正网络格式后再生成"); return
    d = parse_business_data(raw)
    us_parsed.clear(); us_parsed.update(d)
    net = us_get_net()
    fields = dict(wan_ip=net["wan_ip"], wan_mask=net["wan_mask"], wan_gw=net["wan_gw"],
                  wan_eth=net.get("wan_eth", DEFAULT_WAN_ETH),
                  lan_ip=net["lan_ip"], lan_mask=net["lan_mask"],
                  lan_eth=net.get("lan_eth", DEFAULT_LAN_ETH),
                  dns1=net["dns1"], dns2=net["dns2"], parsed=us_parsed)
    try:
        cfg = generate_config_us(fields,
                                 wan_dhcp=net["wan_dhcp"],
                                 extra_subnets_raw=net["inner_raw"],
                                 return_route_nexthop=net["rr_nexthop"],
                                 dhcp_en=net["lan_dhcp"],
                                 net=net)
        us_right.delete("1.0", tk.END)
        us_right.insert(tk.END, cfg)
        main_cnt = len(us_parsed.get("main_export_ips", []))
        bk_cnt   = len(us_parsed.get("backup_export_ips", []))
        wan_desc = "DHCP" if net["wan_dhcp"] else net["wan_ip"]
        rr_cnt   = len(_parse_inner_nets(net["inner_raw"])) if net["rr_nexthop"] else 0
        us_status.set(
            f"✓  非香港出口配置已生成  ·  {cfg.count(chr(10))}行  "
            f"·  WAN:{wan_desc}  ·  出口IP 主:{main_cnt}个/备:{bk_cnt}个"
            + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else ""))
        log_generate_config(
            tool="usg_fastip", variant="us", input_text=raw, output_text=cfg)
    except KeyError as e:
        us_status.set(f"⚠  字段缺失：{e}")
    except Exception as e:
        us_status.set(f"⚠  {e}")

def us_export():
    c = us_right.get("1.0", tk.END).strip()
    if not c: us_status.set("⚠  尚无配置"); return
    p = filedialog.asksaveasfilename(defaultextension=".txt",
        filetypes=[("Text", "*.txt")], initialfile="usg_us_config.txt")
    if p: open(p, "w", encoding="utf-8").write(c); us_status.set(f"✓  已导出：{p}")

def us_reset():
    us_left.delete("1.0", tk.END); us_right.delete("1.0", tk.END)
    us_parsed.clear(); us_reset_net(); us_status.set("↺  已恢复初始")

us_gen.bind("<Button-1>", lambda e: us_generate())
us_exp.bind("<Button-1>", lambda e: us_export())
us_rst.bind("<Button-1>", lambda e: us_reset())


# =====================================================================
# Tab 香港出口
# =====================================================================
HK_NOTE = (
    "• WAN IP / LAN IP 请按 x.x.x.x/x 的 CIDR 格式填写，例如 192.168.9.190/24\n"
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
    "• 请自行修改nat/dns/mtu等部分。\n"
    "• nat只会打第一个出口ip的。其余ip请自行添加。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
HK_EXAMPLE = (
    "主 IPSEC_PE: bja-ape1\n"
    "拨号IP：118.193.100.10\n"
    "loIP：10.18.5.13\n"
    "感兴趣流：10.18.5.13/32 ～ 10.255.108.0/22\n"
    "认证ID：608810A10\n"
    "预共享密钥：both-win\n\n"
    "*\n"
    "LineID:608810A10\n"
    "PE： hkg1-fgpe3\n"
    "WANIP: 10.22.98.40/30\n"
    "TUNNEL: tun1040\n"
    "PE对接：10.255.110.48\n"
    "CE对接：10.18.5.13\n"
    "出口ip：103.91.158.227;\n"
    "*\n"
    "备 IPSEC_PE: sha-apebk1\n"
    "拨号IP：101.226.24.131\n"
    "loIP：10.18.6.25\n"
    "感兴趣流：10.18.5.13/32 ～ 10.255.108.0/22\n"
    "感兴趣流：10.18.6.25/32 ～ 10.255.111.128/25\n"
    "认证ID：608810A11\n"
    "预共享密钥：both-win\n\n"
    "LineID:608810A11\n"
    "PE： hkj-fgpe1\n"
    "WANIP: 10.22.73.52/30\n"
    "TUNNEL: tun2040\n"
    "PE对接：10.255.111.131\n"
    "CE对接：10.18.6.25\n"
    "出口ip：103.91.158.227;\n"
)

hk_init_container = [None]
hk_left, hk_right, hk_status, hk_gen, hk_exp, hk_rst = build_tab_shell(
    tab_hk, ACCENT_HK, HK_NOTE, HK_EXAMPLE, hk_init_container)
hk_get_net, hk_get_net_raw, hk_reset_net = build_net_panel(
    hk_init_container[0], ACCENT_HK, wan_dhcp_default=False, lan_dhcp_default=True,
    dns1_default=HK_DEFAULT_DNS1, dns2_default=HK_DEFAULT_DNS2,
    gkey_prefix="HK_")

hk_parsed = {}

def hk_generate():
    raw = hk_left.get("1.0", tk.END).strip()
    if not raw: hk_status.set("⚠  请先输入业务数据"); return
    raw_net = hk_get_net_raw()
    ok, errs = validate_net_panel_values(
        "" if raw_net["wan_dhcp"] else raw_net["wan_ip"],
        "" if raw_net["wan_dhcp"] else raw_net["wan_gw"],
        raw_net["lan_ip"],
        raw_net["lan_gw"],
        raw_net["inner_raw"],
        DEFAULT_WAN_IP, DEFAULT_WAN_GW, DEFAULT_LAN_IP
    )
    if not ok:
        messagebox.showwarning("网络格式校验未通过", "\n".join(errs))
        hk_status.set("⚠  请修正网络格式后再生成"); return
    d = parse_business_data_hk(raw)
    hk_parsed.clear(); hk_parsed.update(d)
    net = hk_get_net()
    wan_ip, wan_mask = net["wan_ip"], net["wan_mask"]
    wan_gw  = net["wan_gw"]
    wan_dhcp = net["wan_dhcp"]
    lan_ip, lan_mask = net["lan_ip"], net["lan_mask"]
    dns1, dns2 = net["dns1"], net["dns2"]
    wan_eth = net.get("wan_eth", str(globals().get("HK_DEFAULT_WAN_ETH", DEFAULT_WAN_ETH)))
    lan_eth = net.get("lan_eth", str(globals().get("HK_DEFAULT_LAN_ETH", DEFAULT_LAN_ETH)))
    wan_if_block_hk      = build_wan_if_block(wan_ip, wan_mask, wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    wan_default_rts_hk   = build_wan_default_routes(wan_gw, dhcp=wan_dhcp, wan_eth=wan_eth)
    dns_dnat_block_hk    = build_dns_dnat_block(wan_ip, dhcp=wan_dhcp)
    m = hk_parsed
    def g(k, dv="（待填）"): return m.get(k, dv)

    # 回程路由：所有解析到的内网段统一下发，不再判断是否 LAN 直连
    extra_routes_block = ""
    if net["rr_nexthop"]:
        nets = _parse_inner_nets(net["inner_raw"])
        if nets:
            subs = []
            for n in nets:
                net_obj = ipaddress.ip_network(n, strict=False)
                subs.append((str(net_obj.network_address), str(net_obj.netmask), n))
            extra_routes_block = build_extra_return_routes(subs, net["rr_nexthop"])

    if net["lan_dhcp"]:
        ds, de = compute_dhcp_range(lan_ip, lan_mask)
        dhcp_block = (
            f"\ndhcp enable\n"
            f"\ninterface {lan_eth}\n ip address {lan_ip} {lan_mask}\n"
            f" dhcp select interface\n dhcp server ip-range {ds} {de}\n"
            f" dhcp server gateway-list {lan_ip}\n dhcp server dns-list {lan_ip} \n"
            f" service-manage all permit"
        )
    else:
        dhcp_block = (
            f"\ninterface {lan_eth}\n ip address {lan_ip} {lan_mask}\n service-manage all permit"
        )

    # LoopBack / NAT
    # HK：主备线海外出口IP相同，只用主线IPs生成 LoopBack100+ 和每IP独立的 NAT 地址组
    me = m.get("main_export_ips", [])
    mlo = []
    main_ip_map = m.get('main_export_ip_map', {})
    for i, ip in enumerate(me):
        real = main_ip_map.get(ip)
        desc = f"Main-OUT-{i+1}({real})" if real else f"Main-OUT-{i+1}"
        mlo += [f"interface LoopBack{100+i}", f" description {desc}", f" ip address {ip} 255.255.255.255"]

    main_nat_block_hk  = build_nat_groups_block(me, 'MAIN')
    # HK 备线复用主线 NAT 地址组，只是走 Tunnel2000
    main_snat_block_hk   = build_snat_rules_block(me, 'MAIN', 'Tunnel1000', 'ToMainOUT')
    backup_snat_block_hk = build_snat_rules_block(me, 'MAIN', 'Tunnel2000', 'ToBackOUT')

    try:
        # BGP router-id：优先用主出口IP（LoopBack100），否则回退到主 loIP
        _rid = (me[0] if me else "")
        if not _rid:
            m_lo = str(g("main_loopback", ""))
            m_rid = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', m_lo)
            _rid = m_rid.group(1) if m_rid else "0.0.0.0"
        hk_fmt = dict(
            wan_if_block=wan_if_block_hk,
            wan_default_routes=wan_default_rts_hk,
            dns_dnat_block=dns_dnat_block_hk,
            dhcp_block=dhcp_block, wan_eth=wan_eth, lan_eth=lan_eth,
            wan_ip=wan_ip, wan_mask=wan_mask, wan_gw=wan_gw,
            lan_ip=lan_ip, dns_ip1=dns1, dns_ip2=dns2,
            main_lo_block="\n".join(mlo) or "#（主出口LoopBack待填）",
            main_nat_block=main_nat_block_hk,
            main_snat_block=main_snat_block_hk,
            backup_snat_block=backup_snat_block_hk,
            main_export_ip=_rid,
            main_export_natip=me[0] if me else "0.0.0.0",
            main_export_summary="\n".join(me) or "（待填）",
            backup_export_summary="\n".join(m.get("backup_export_ips", me)) or "（待填）",
            extra_return_routes=extra_routes_block,
            main_dial_pe=g("main_dial_pe"), main_dial_ip=g("main_dial_ip"),
            main_loopback=g("main_loopback"), main_auth_id=g("main_auth_id"),
            main_pe=g("main_pe"), main_wanip=g("main_wanip"),
            main_tunnel=g("main_tunnel"), main_wanip1=g("main_wanip1"),
            main_wanip2=g("main_wanip2"), main_peer_ip=g("main_peer_ip"),
            backup_dial_pe=g("backup_dial_pe"), backup_dial_ip=g("backup_dial_ip"),
            backup_loopback=g("backup_loopback"), backup_auth_id=g("backup_auth_id"),
            backup_pe=g("backup_pe"), backup_wanip=g("backup_wanip"),
            backup_tunnel=g("backup_tunnel"), backup_wanip1=g("backup_wanip1"),
            backup_wanip2=g("backup_wanip2"), backup_peer_ip=g("backup_peer_ip"),
            bgp_main_server1=_NEW_BGP_MAIN_1, bgp_main_server2=_NEW_BGP_MAIN_2,
            bgp_backup_server1=_NEW_BGP_BACKUP_1, bgp_backup_server2=_NEW_BGP_BACKUP_2,
            bgp_main_name1="hkg1-bgpserver5", bgp_main_name2="hkg1-bgpserver6",
            bgp_backup_name1="szd-bgpserver5", bgp_backup_name2="szd-bgpserver6",
        )
        inject_usg_template_init_aliases(hk_fmt, net)
        if field_coverage:
            miss = field_coverage.missing_template_fields(
                TEMPLATE_USG_HK, hk_fmt, skip=_USG_HK_COVER_SKIP)
            field_coverage.show_generation_coverage_notice(
                messagebox, miss, "USG FastIP · 香港出口")
        cfg = TEMPLATE_USG_HK.format(**hk_fmt)
        hk_right.delete("1.0", tk.END)
        hk_right.insert(tk.END, cfg)
        rr_cnt = len(_parse_inner_nets(net["inner_raw"])) if net["rr_nexthop"] else 0
        hk_status.set(
            f"✓  香港配置已生成  ·  {cfg.count(chr(10))}行  "
            f"·  WAN:{wan_ip}  ·  出口IP:{len(me)}个（主备共用）"
            + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else ""))
        log_generate_config(
            tool="usg_fastip", variant="hk", input_text=raw, output_text=cfg)
    except KeyError as e:
        hk_status.set(f"⚠  字段缺失：{e}")
    except Exception as e:
        hk_status.set(f"⚠  {e}")

def hk_export():
    c = hk_right.get("1.0", tk.END).strip()
    if not c: hk_status.set("⚠  尚无配置"); return
    p = filedialog.asksaveasfilename(defaultextension=".txt",
        filetypes=[("Text", "*.txt")], initialfile="usg_hk_config.txt")
    if p: open(p, "w", encoding="utf-8").write(c); hk_status.set(f"✓  已导出：{p}")

def hk_reset():
    hk_left.delete("1.0", tk.END); hk_right.delete("1.0", tk.END)
    hk_parsed.clear(); hk_reset_net(); hk_status.set("↺  已恢复初始")

hk_gen.bind("<Button-1>", lambda e: hk_generate())
hk_exp.bind("<Button-1>", lambda e: hk_export())
hk_rst.bind("<Button-1>", lambda e: hk_reset())


# =====================================================================
# Tab 小功能（飞连 + 新增出口）
# =====================================================================
ACCENT_FL = "#16a085"

tab_fl.columnconfigure(0, weight=1)
tab_fl.rowconfigure(0, weight=1)
fl_sub_nb = ttk.Notebook(tab_fl)
fl_sub_nb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
fl_tab_flink = tk.Frame(fl_sub_nb, bg=BG)
fl_tab_new_exit = tk.Frame(fl_sub_nb, bg=BG)
fl_sub_nb.add(fl_tab_flink, text="  飞连  ")
fl_sub_nb.add(fl_tab_new_exit, text="  新增出口  ")

# ───────────────────────────── 飞连子页 ──────────────────────────────
fl_tab_flink.columnconfigure(0, weight=1)
fl_tab_flink.rowconfigure(1, weight=1)
fl_top = tk.Frame(fl_tab_flink, bg=BG)
fl_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
fl_top.columnconfigure(0, weight=3)
fl_top.columnconfigure(1, weight=1)
fl_tpl_wrap = tk.Frame(fl_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
fl_tpl_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
fl_tpl_hdr = tk.Frame(fl_tpl_wrap, bg=ACCENT_FL, height=28)
fl_tpl_hdr.pack(fill="x")
fl_tpl_hdr.pack_propagate(False)
tk.Frame(fl_tpl_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(fl_tpl_hdr, text="  输入格式说明（飞连信息）", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT).pack(side="left", pady=3)
fl_tpl_body = tk.Frame(fl_tpl_wrap, bg=BG_PANEL)
fl_tpl_body.pack(fill="both", expand=True, padx=6, pady=4)
fl_tpl_text = tk.Text(fl_tpl_body, height=7, font=FONT_MONO, bg=BG_PANEL, fg=FG_DIM, relief="flat", bd=0, padx=8, pady=4, state="normal")
fl_tpl_text.pack(fill="both", expand=True)
fl_tpl_text.insert(tk.END, USG_FL_EXAMPLE)
fl_tpl_text.config(state="disabled")
fl_tun_wrap = tk.Frame(fl_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
fl_tun_wrap.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
fl_tun_hdr = tk.Frame(fl_tun_wrap, bg=ACCENT_FL, height=28)
fl_tun_hdr.pack(fill="x")
fl_tun_hdr.pack_propagate(False)
tk.Frame(fl_tun_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(fl_tun_hdr, text="  Tunnel 号 & 预留IP", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT).pack(side="left", pady=3)
fl_cfg_body = tk.Frame(fl_tun_wrap, bg=BG_PANEL)
fl_cfg_body.pack(fill="both", expand=True, padx=10, pady=6)
_FL_FIELDS = [("主 Tunnel 号", USG_FL_MAIN_TUN_DEFAULT), ("备 Tunnel 号", USG_FL_BK_TUN_DEFAULT)]
fl_entries = []
for i, (lbl, default) in enumerate(_FL_FIELDS):
    tk.Label(fl_cfg_body, text=lbl, font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=i, column=0, sticky="e", padx=(4, 6), pady=6)
    e = tk.Entry(fl_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL, width=12)
    e.insert(0, default)
    e.grid(row=i, column=1, sticky="ew", pady=6)
    fl_cfg_body.columnconfigure(1, weight=1)
    fl_entries.append(e)
fl_entry_main_tun, fl_entry_bk_tun = fl_entries
tk.Frame(fl_cfg_body, bg=BORDER, height=1).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
tk.Label(fl_cfg_body, text="预留IP（自动解析）", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(6, 2))
fl_reserved_text = tk.Text(fl_cfg_body, height=3, font=FONT_MONO, bg=BG_INPUT, fg=ACCENT_FL, relief="flat", bd=0, padx=6, pady=4, state="disabled")
fl_reserved_text.grid(row=4, column=0, columnspan=2, sticky="ew")
fl_pane = ttk.PanedWindow(fl_tab_flink, orient="horizontal")
fl_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
fl_lp = tk.Frame(fl_pane, bg=BG_PANEL)
fl_pane.add(fl_lp, weight=1)
fl_lp.rowconfigure(1, weight=1)
fl_lp.columnconfigure(0, weight=1)
fl_lp_hdr = tk.Frame(fl_lp, bg=ACCENT_FL, height=28)
fl_lp_hdr.grid(row=0, column=0, sticky="ew")
fl_lp_hdr.grid_propagate(False)
tk.Frame(fl_lp_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(fl_lp_hdr, text="  飞连数据头输入", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT, pady=3).pack(side="left")
fl_left_inner = tk.Frame(fl_lp, bg=BG_INPUT)
fl_left_inner.grid(row=1, column=0, sticky="nsew")
fl_left_text = make_text(fl_left_inner)
fl_rp = tk.Frame(fl_pane, bg=BG_PANEL)
fl_pane.add(fl_rp, weight=1)
fl_rp.rowconfigure(1, weight=1)
fl_rp.columnconfigure(0, weight=1)
fl_rp_hdr = tk.Frame(fl_rp, bg=ACCENT_FL, height=28)
fl_rp_hdr.grid(row=0, column=0, sticky="ew")
fl_rp_hdr.grid_propagate(False)
tk.Frame(fl_rp_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(fl_rp_hdr, text="  生成结果", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT, pady=3).pack(side="left")
fl_right_inner = tk.Frame(fl_rp, bg=BG_INPUT)
fl_right_inner.grid(row=1, column=0, sticky="nsew")
fl_right_output = make_text(fl_right_inner)
tk.Frame(fl_tab_flink, bg=BORDER, height=1).grid(row=2, column=0, sticky="ew")
fl_btm = tk.Frame(fl_tab_flink, bg=BG_HDR, height=48)
fl_btm.grid(row=3, column=0, sticky="ew")
fl_btm.grid_propagate(False)
fl_status_var = tk.StringVar(value="就绪  ·  等待输入飞连业务数据")
tk.Label(fl_btm, textvariable=fl_status_var, font=FONT_TINY, bg=BG_HDR, fg="#7ecfc0").pack(side="left", padx=14)
fl_btn_export = flat_btn(fl_btm, "导出 TXT", ACCENT_US)
fl_btn_export.pack(side="right", padx=(0, 14), pady=8)
fl_btn_gen = flat_btn(fl_btm, "⚡  生成配置", ACCENT_FL)
fl_btn_gen.pack(side="right", padx=(0, 6), pady=8)
fl_btn_reset = flat_btn(fl_btm, "↺  恢复初始", "#6c757d")
fl_btn_reset.pack(side="right", padx=(0, 6), pady=8)

# ──────────────────────────── 新增出口子页 ───────────────────────────
fl_tab_new_exit.columnconfigure(0, weight=1)
fl_tab_new_exit.rowconfigure(1, weight=1)
ne_top = tk.Frame(fl_tab_new_exit, bg=BG)
ne_top.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
ne_top.columnconfigure(0, weight=3)
ne_top.columnconfigure(1, weight=2)
ne_tpl_wrap = tk.Frame(ne_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
ne_tpl_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
ne_tpl_hdr = tk.Frame(ne_tpl_wrap, bg=ACCENT_FL, height=28)
ne_tpl_hdr.pack(fill="x")
ne_tpl_hdr.pack_propagate(False)
tk.Frame(ne_tpl_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(ne_tpl_hdr, text="  输入格式说明（新增出口）", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT).pack(side="left", pady=3)
ne_tpl_body = tk.Frame(ne_tpl_wrap, bg=BG_PANEL)
ne_tpl_body.pack(fill="both", expand=True, padx=6, pady=4)
ne_tpl_text = tk.Text(ne_tpl_body, height=9, font=FONT_MONO, bg=BG_PANEL, fg=FG_DIM, relief="flat", bd=0, padx=8, pady=4, state="normal")
ne_tpl_text.pack(fill="both", expand=True)
ne_tpl_text.insert(tk.END, USG_NEW_EXIT_EXAMPLE)
ne_tpl_text.config(state="disabled")
ne_cfg_wrap = tk.Frame(ne_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
ne_cfg_wrap.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
ne_cfg_hdr = tk.Frame(ne_cfg_wrap, bg=ACCENT_FL, height=28)
ne_cfg_hdr.pack(fill="x")
ne_cfg_hdr.pack_propagate(False)
tk.Frame(ne_cfg_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(ne_cfg_hdr, text="  初始化参数（左主线 / 右备线）", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT).pack(side="left", pady=3)
ne_cfg_body = tk.Frame(ne_cfg_wrap, bg=BG_PANEL)
ne_cfg_body.pack(fill="both", expand=True, padx=8, pady=6)
ne_cfg_body.columnconfigure(1, weight=1)
ne_cfg_body.columnconfigure(3, weight=1)
tk.Label(ne_cfg_body, text="主 Tunnel 号", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=0, column=0, sticky="e", padx=(2, 6), pady=4)
ne_entry_main_tun = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_main_tun.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=4)
ne_entry_main_tun.insert(0, USG_NE_MAIN_TUN_DEFAULT)
tk.Label(ne_cfg_body, text="备 Tunnel 号", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=0, column=2, sticky="e", padx=(2, 6), pady=4)
ne_entry_bk_tun = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_bk_tun.grid(row=0, column=3, sticky="ew", pady=4)
ne_entry_bk_tun.insert(0, USG_NE_BK_TUN_DEFAULT)
tk.Label(ne_cfg_body, text="主 LoopBack 起始", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=1, column=0, sticky="e", padx=(2, 6), pady=4)
ne_entry_main_loop = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_main_loop.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=4)
ne_entry_main_loop.insert(0, USG_NE_MAIN_LOOP_START_DEFAULT)
tk.Label(ne_cfg_body, text="备 LoopBack 起始", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=1, column=2, sticky="e", padx=(2, 6), pady=4)
ne_entry_bk_loop = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_bk_loop.grid(row=1, column=3, sticky="ew", pady=4)
ne_entry_bk_loop.insert(0, USG_NE_BK_LOOP_START_DEFAULT)
tk.Label(ne_cfg_body, text="主 NQA 名称", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=2, column=0, sticky="e", padx=(2, 6), pady=4)
ne_entry_main_nqa = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_main_nqa.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
ne_entry_main_nqa.insert(0, USG_NE_MAIN_NQA_DEFAULT)
tk.Label(ne_cfg_body, text="备 NQA 名称", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="e").grid(row=2, column=2, sticky="e", padx=(2, 6), pady=4)
ne_entry_bk_nqa = tk.Entry(ne_cfg_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, insertbackground=ACCENT_FL, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_FL)
ne_entry_bk_nqa.grid(row=2, column=3, sticky="ew", pady=4)
ne_entry_bk_nqa.insert(0, USG_NE_BK_NQA_DEFAULT)
ne_pane = ttk.PanedWindow(fl_tab_new_exit, orient="horizontal")
ne_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
ne_lp = tk.Frame(ne_pane, bg=BG_PANEL)
ne_pane.add(ne_lp, weight=1)
ne_lp.rowconfigure(1, weight=1)
ne_lp.columnconfigure(0, weight=1)
ne_lp_hdr = tk.Frame(ne_lp, bg=ACCENT_FL, height=28)
ne_lp_hdr.grid(row=0, column=0, sticky="ew")
ne_lp_hdr.grid_propagate(False)
tk.Frame(ne_lp_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(ne_lp_hdr, text="  新增出口数据头输入", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT, pady=3).pack(side="left")
ne_left_inner = tk.Frame(ne_lp, bg=BG_INPUT)
ne_left_inner.grid(row=1, column=0, sticky="nsew")
ne_left_text = make_text(ne_left_inner)
ne_rp = tk.Frame(ne_pane, bg=BG_PANEL)
ne_pane.add(ne_rp, weight=1)
ne_rp.rowconfigure(1, weight=1)
ne_rp.columnconfigure(0, weight=1)
ne_rp_hdr = tk.Frame(ne_rp, bg=ACCENT_FL, height=28)
ne_rp_hdr.grid(row=0, column=0, sticky="ew")
ne_rp_hdr.grid_propagate(False)
tk.Frame(ne_rp_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(ne_rp_hdr, text="  生成结果", font=FONT_HDR, bg=ACCENT_FL, fg=FG_BRT, pady=3).pack(side="left")
ne_right_inner = tk.Frame(ne_rp, bg=BG_INPUT)
ne_right_inner.grid(row=1, column=0, sticky="nsew")
ne_right_output = make_text(ne_right_inner)
tk.Frame(fl_tab_new_exit, bg=BORDER, height=1).grid(row=2, column=0, sticky="ew")
ne_btm = tk.Frame(fl_tab_new_exit, bg=BG_HDR, height=48)
ne_btm.grid(row=3, column=0, sticky="ew")
ne_btm.grid_propagate(False)
ne_status_var = tk.StringVar(value="就绪  ·  等待输入新增出口业务数据")
tk.Label(ne_btm, textvariable=ne_status_var, font=FONT_TINY, bg=BG_HDR, fg="#7ecfc0").pack(side="left", padx=14)
ne_btn_export = flat_btn(ne_btm, "导出 TXT", ACCENT_US)
ne_btn_export.pack(side="right", padx=(0, 14), pady=8)
ne_btn_gen = flat_btn(ne_btm, "⚡  生成配置", ACCENT_FL)
ne_btn_gen.pack(side="right", padx=(0, 6), pady=8)
ne_btn_reset = flat_btn(ne_btm, "↺  恢复初始", "#6c757d")
ne_btn_reset.pack(side="right", padx=(0, 6), pady=8)


# =====================================================================
# 飞连数据解析 & 生成逻辑（完整还原原版）
# =====================================================================
def build_usg_flink_format_dict(raw_text: str, main_tun: str | None = None, bk_tun: str | None = None) -> tuple:
    """Build format dict for USG Flink template from header text. Returns (d, err)."""
    parsed = parse_feilink_data(raw_text)
    mn = parsed.get("main") or {}
    if not mn.get("line_id"):
        return None, "未识别到有效的 LineID 块，请检查格式"

    reserved = parsed.get("reserved_ips") or []
    if not reserved:
        return None, "未解析到预留IP，请检查飞连信息中的「预留IP」行"

    d = {}
    for section in ("main", "backup"):
        sub = parsed.get(section, {})
        if isinstance(sub, dict):
            for k, v in sub.items():
                d[f"{section}_{k}"] = v

    rsv_pairs = []
    for ip_cidr in reserved[:3]:
        cidr = str(ip_cidr.get("cidr", "")).strip() if isinstance(ip_cidr, dict) else str(ip_cidr).strip()
        if not cidr:
            rsv_pairs.append(("0.0.0.0", "32"))
            continue
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            rsv_pairs.append((str(net.network_address), str(net.prefixlen)))
        except ValueError:
            if "/" in cidr:
                net_addr, prefix = cidr.split("/", 1)
                rsv_pairs.append((net_addr.strip(), prefix.strip()))
            else:
                rsv_pairs.append((cidr, "32"))
    while len(rsv_pairs) < 3:
        rsv_pairs.append(("0.0.0.0", "32"))
    for i, (net_addr, prefix) in enumerate(rsv_pairs[:3], start=1):
        d[f"reserved{i}_net"] = net_addr
        d[f"reserved{i}_mask"] = prefix

    d["USG_FL_MAIN_TUN_DEFAULT"] = str(main_tun or globals().get("USG_FL_MAIN_TUN_DEFAULT", "3000"))
    d["USG_FL_BK_TUN_DEFAULT"] = str(bk_tun or globals().get("USG_FL_BK_TUN_DEFAULT", "4000"))
    for sfx in ("pe", "line_id", "wanip1", "wanip2", "peer_ip", "ce_docking", "export_summary"):
        d.setdefault(f"main_{sfx}", "")
        d.setdefault(f"backup_{sfx}", "")
    return d, None


def parse_feilink_data(text: str) -> dict:
    result = {"main": {}, "backup": {}, "reserved_ips": []}
    for m in re.finditer(r"预留IP[：:]\s*([\d./]+)", text):
        result["reserved_ips"].append(m.group(1).strip())
    blocks = re.split(r"(?=LineID\s*[:：])", text)
    parsed_blocks = []
    for block in blocks:
        if not re.search(r"LineID", block):
            continue
        d = {}
        def _get(pattern, b=block):
            m = re.search(pattern, b, re.IGNORECASE | re.MULTILINE)
            return m.group(1).strip() if m else ""
        d["line_id"]  = _get(r"LineID\s*[:：]\s*(\S+)")
        d["pe"]       = _get(r"^PE\s*[:：]\s*(.+)$")
        if not d["pe"]:
            d["pe"]   = _get(r"PE\s*[:：]\s*(.+)")
        d["tunnel_id"]= _get(r"Tunnel\s*[:：]\s*(\S+)")
        d["peer_ip"]  = _get(r"PE\s*对接\s*[:：]\s*([\d.]+)")
        d["ce_ip"]    = _get(r"CE\s*对接\s*[:：]\s*([\d.]+)")
        wanip_raw = _get(r"wanip\s*[:：]\s*([\d./]+)")
        d["wanip"] = wanip_raw
        d["wanip1"] = ""; d["wanip2"] = ""
        if wanip_raw and "/" in wanip_raw:
            try:
                hosts = list(ipaddress.ip_network(wanip_raw, strict=False).hosts())
                if len(hosts) >= 2:
                    d["wanip1"] = str(hosts[0])
                    d["wanip2"] = str(hosts[1])
            except Exception:
                pass
        if d["line_id"]:
            parsed_blocks.append(d)
    if len(parsed_blocks) >= 1: result["main"]   = parsed_blocks[0]
    if len(parsed_blocks) >= 2: result["backup"] = parsed_blocks[1]
    return result


def _get_tunnel_num(entry, default):
    v = entry.get().strip()
    return v if v else default


def fl_generate():
    import ipaddress as _ip
    input_text = fl_left_text.get("1.0", tk.END).strip()
    if not input_text:
        fl_status_var.set("⚠  请先输入飞连业务数据")
        messagebox.showwarning("提示", "请输入飞连业务数据"); return
    data = parse_feilink_data(input_text)
    mn = data["main"]; bk = data["backup"]
    if not mn:
        fl_status_var.set("⚠  未识别到有效的 LineID 块，请检查格式")
        messagebox.showwarning("提示", "未识别到有效的 LineID 块"); return
    tun_main = _get_tunnel_num(fl_entry_main_tun, str(globals().get("USG_FL_MAIN_TUN_DEFAULT", "3000")))
    tun_bk   = _get_tunnel_num(fl_entry_bk_tun,   str(globals().get("USG_FL_BK_TUN_DEFAULT", "4000")))
    reserved = data["reserved_ips"]
    fl_reserved_text.config(state="normal")
    fl_reserved_text.delete("1.0", tk.END)
    fl_reserved_text.insert(tk.END,
        "\n".join(reserved) if reserved else "（未解析到预留IP，请手动确认）")
    fl_reserved_text.config(state="disabled")
    lines = []
    lines += [
        f"interface Tunnel{tun_main}",
        f" description Main-{mn.get('pe','')}-flink-{mn.get('line_id','')}",
        f" ip address {mn.get('wanip2','')} 255.255.255.252",
        f" tunnel-protocol gre", f" source LoopBack10",
        f" destination {mn.get('peer_ip','')}", f" service-manage all permit", "",
    ]
    if bk:
        lines += [
            f"interface Tunnel{tun_bk}",
            f" description BK-{bk.get('pe','')}-flink-{bk.get('line_id','')}",
            f" ip address {bk.get('wanip2','')} 255.255.255.252",
            f" tunnel-protocol gre", f" source LoopBack11",
            f" destination {bk.get('peer_ip','')}", f" service-manage all permit", "",
        ]
    lines += [
        f"nqa test-instance admin FLmain", f" test-type icmp",
        f" destination-address ipv4 {mn.get('wanip1','')}",
        f" source-address ipv4 {mn.get('wanip2','')}",
        f" send-trap probefailure", f" send-trap testfailure",
        f" test-failtimes 2", f" probe-count 4", f" frequency 30",
        f" start now", f"q", "",
    ]
    lines += ["firewall zone untrust", f" add interface Tunnel{tun_main}"]
    if bk: lines.append(f" add interface Tunnel{tun_bk}")
    lines.append("")
    if reserved:
        lines.append("ip address-set flink type object")
        for idx, ip_cidr in enumerate(reserved):
            try:
                net = _ip.ip_network(ip_cidr, strict=False)
                lines.append(f" address {idx} {net.network_address} mask {net.prefixlen}")
            except Exception:
                lines.append(f" address {idx} {ip_cidr}")
        lines.append("")
    main_nh = mn.get("wanip1", ""); bk_nh = bk.get("wanip1", "") if bk else ""
    for ip_cidr in reserved:
        try:
            net = _ip.ip_network(ip_cidr, strict=False)
            net_addr = str(net.network_address); prefix_len = net.prefixlen
        except Exception:
            net_addr, prefix_len = ip_cidr, ""
        if main_nh:
            lines.append(f"ip route-static {net_addr} {prefix_len} {main_nh} track nqa admin FLmain")
    lines.append("")
    if bk_nh:
        for ip_cidr in reserved:
            try:
                net = _ip.ip_network(ip_cidr, strict=False)
                net_addr = str(net.network_address); prefix_len = net.prefixlen
            except Exception:
                net_addr, prefix_len = ip_cidr, ""
            lines.append(f"ip route-static {net_addr} {prefix_len} {bk_nh} preference 100")
    output = "\n".join(lines)
    try:
        _rsv = []
        for ip_cidr in reserved[:3]:
            try:
                _net = _ip.ip_network(ip_cidr, strict=False)
                _rsv.append((str(_net.network_address), str(_net.prefixlen)))
            except Exception:
                _rsv.append((ip_cidr, ""))
        while len(_rsv) < 3:
            _rsv.append(("0.0.0.0", "32"))
        _fmt = {
            "USG_FL_MAIN_TUN_DEFAULT": tun_main,
            "USG_FL_BK_TUN_DEFAULT": tun_bk,
            "main_pe": mn.get("pe", ""),
            "main_line_id": mn.get("line_id", ""),
            "main_wanip1": mn.get("wanip1", ""),
            "main_wanip2": mn.get("wanip2", ""),
            "main_peer_ip": mn.get("peer_ip", ""),
            "backup_pe": bk.get("pe", ""),
            "backup_line_id": bk.get("line_id", ""),
            "backup_wanip1": bk.get("wanip1", ""),
            "backup_wanip2": bk.get("wanip2", ""),
            "backup_peer_ip": bk.get("peer_ip", ""),
            "reserved1_net": _rsv[0][0],
            "reserved1_mask": _rsv[0][1],
            "reserved2_net": _rsv[1][0],
            "reserved2_mask": _rsv[1][1],
            "reserved3_net": _rsv[2][0],
            "reserved3_mask": _rsv[2][1],
        }
        output = TEMPLATE_USG_FLINK_VISUAL.format(**_fmt)
    except Exception:
        pass
    fl_right_output.delete("1.0", tk.END)
    fl_right_output.insert(tk.END, output)
    fl_status_var.set(
        f"✓  飞连配置已生成  ·  共 {output.count(chr(10))} 行  "
        f"·  主Tunnel{tun_main} / 备Tunnel{tun_bk}  ·  预留IP {len(reserved)} 段"
    )
    log_generate_config(
        tool="usg_fastip", variant="feilink", input_text=input_text, output_text=output)


def fl_export():
    content = fl_right_output.get("1.0", tk.END).strip()
    if not content:
        fl_status_var.set("⚠  尚无可导出的配置，请先生成")
        messagebox.showwarning("提示", "没有可导出的配置"); return
    path = filedialog.asksaveasfilename(
        defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(content)
            fl_status_var.set(f"✓  已导出至：{path}")
            messagebox.showinfo("成功", "文件导出成功")
        except Exception as e:
            messagebox.showerror("错误", str(e))


def fl_reset():
    fl_left_text.delete("1.0", tk.END)
    fl_right_output.delete("1.0", tk.END)
    fl_entry_main_tun.delete(0, tk.END); fl_entry_main_tun.insert(0, str(globals().get("USG_FL_MAIN_TUN_DEFAULT", "3000")))
    fl_entry_bk_tun.delete(0, tk.END);  fl_entry_bk_tun.insert(0, str(globals().get("USG_FL_BK_TUN_DEFAULT", "4000")))
    fl_reserved_text.config(state="normal")
    fl_reserved_text.delete("1.0", tk.END)
    fl_reserved_text.config(state="disabled")
    fl_status_var.set("↺  已恢复初始状态  ·  等待输入飞连业务数据")


fl_btn_gen.bind("<Button-1>",    lambda e: fl_generate())
fl_btn_export.bind("<Button-1>", lambda e: fl_export())
fl_btn_reset.bind("<Button-1>",  lambda e: fl_reset())


def parse_usg_new_exit_blocks(text: str):
    """解析 USG 新增出口数据头，返回 (parsed, err_msg)。"""
    blocks = [b.strip() for b in re.split(r"(?=LineID\s*[:：])", text or "", flags=re.IGNORECASE) if b.strip()]
    out = {}

    def _get(pat: str, blob: str) -> str:
        m = re.search(pat, blob, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    for block in blocks:
        line_id = _get(r"LineID\s*[:：]\s*(\S+)", block)
        if not line_id:
            continue
        key = "main"
        try:
            key = "main" if int(re.sub(r"\D", "", line_id)[-1:]) % 2 == 1 else "backup"
        except Exception:
            key = "main" if "main" not in out else "backup"
        pe = _get(r"^\s*PE\s*[:：]\s*(.+?)$", block) or _get(r"PE\s*[:：]\s*(.+)", block)
        wanip = _get(r"WANIP\s*[:：]\s*([\d./]+)", block)
        tun_raw = _get(r"TUNNEL\s*[:：]\s*(\S+)", block)
        pe_docking = _get(r"PE\s*对接\s*[:：]\s*([\d.]+)", block)
        ce_docking = _get(r"CE\s*对接\s*[:：]\s*([\d.]+)", block)
        ex_blob_m = re.search(r"出口ip\s*[:：]\s*(.*?)(?=\nLineID\s*[:：]|\Z)", block, re.IGNORECASE | re.DOTALL)
        ex_blob = ex_blob_m.group(1) if ex_blob_m else ""
        pairs = re.findall(r"(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})", ex_blob or "")
        if not pairs:
            ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", ex_blob or "")
            pairs = [(ip, ip) for ip in ips]
        if not all((pe, wanip, tun_raw, pe_docking, ce_docking)) or not pairs:
            return None, f"{line_id} 数据不完整，请检查 PE/WANIP/TUNNEL/PE对接/CE对接/出口ip"
        wanip1 = ""
        wanip2 = ""
        try:
            hs = list(ipaddress.ip_network(wanip, strict=False).hosts())
            if len(hs) >= 2:
                wanip1 = str(hs[0])
                wanip2 = str(hs[1])
        except Exception:
            pass
        if not wanip1 or not wanip2:
            return None, f"{line_id} WANIP 无法解析：{wanip}"
        out[key] = {
            "line_id": line_id,
            "pe": pe,
            "wanip": wanip,
            "wanip1": wanip1,
            "wanip2": wanip2,
            "tunnel_raw": tun_raw,
            "pe_docking": pe_docking,
            "ce_docking": ce_docking,
            "export_pairs": pairs,
        }
    if "main" not in out or "backup" not in out:
        return None, "请同时提供主线与备线（LineID 奇数主线、偶数备线）"
    return out, None


def _ne_int(entry, name: str, default: str, min_v: int = 1, max_v: int = 9999):
    raw = entry.get().strip() or default
    if not raw.isdigit():
        return None, f"{name}必须是整数"
    val = int(raw)
    if not (min_v <= val <= max_v):
        return None, f"{name}范围应为 {min_v}~{max_v}"
    return val, None


def build_new_exit_snat_policy_block(main_ips, backup_ips, main_tun: int, backup_tun: int) -> str:
    """将主备 SNAT 规则放入同一个 nat-policy 段。"""
    lines = ["nat-policy"]
    has_rule = False
    for i, _ip in enumerate(main_ips):
        has_rule = True
        lines.extend([
            f"rule name ToMainNEW-{i + 1}",
            "  source-zone trust",
            "  source-zone untrust",
            f"  egress-interface Tunnel{main_tun}",
            "  source-address address-set LAN-IP",
            f"  action source-nat address-group NEW-MAIN-OUT-IP{i + 1}",
            "",
        ])
    for i, _ip in enumerate(backup_ips):
        has_rule = True
        lines.extend([
            f"rule name ToBackNEW-{i + 1}",
            "  source-zone trust",
            "  source-zone untrust",
            f"  egress-interface Tunnel{backup_tun}",
            "  source-address address-set LAN-IP",
            f"  action source-nat address-group NEW-BACKUP-OUT-IP{i + 1}",
            "",
        ])
    if not has_rule:
        return "#（NEW EXIT SNAT 规则待填）"
    return "\n".join(lines).rstrip()


def build_usg_new_exit_format_dict(parsed: dict, init_cfg: dict) -> dict:
    mn = parsed["main"]
    bk = parsed["backup"]
    m_pairs = list(mn.get("export_pairs") or [])
    b_pairs = list(bk.get("export_pairs") or [])
    m_left_ips = [lp for lp, _rp in m_pairs]
    b_left_ips = [lp for lp, _rp in b_pairs]
    main_tun = int(init_cfg["main_tun"])
    backup_tun = int(init_cfg["bk_tun"])
    m_loop_start = int(init_cfg["main_loop_start"])
    b_loop_start = int(init_cfg["bk_loop_start"])
    main_lo_lines = []
    for i, (lip, rip) in enumerate(m_pairs):
        main_lo_lines.extend([
            f"interface LoopBack{m_loop_start + i}",
            f" description Main-OUT-{i + 1}({rip})",
            f" ip address {lip} 255.255.255.255",
            "",
        ])
    bk_lo_lines = []
    for i, (lip, rip) in enumerate(b_pairs):
        bk_lo_lines.extend([
            f"interface LoopBack{b_loop_start + i}",
            f" description Backup-OUT-{i + 1}({rip})",
            f" ip address {lip} 255.255.255.255",
            "",
        ])
    return {
        "USG_NE_MAIN_TUN_DEFAULT": str(init_cfg["main_tun"]),
        "USG_NE_BK_TUN_DEFAULT": str(init_cfg["bk_tun"]),
        "USG_NE_MAIN_NQA_DEFAULT": init_cfg["main_nqa"],
        "USG_NE_BK_NQA_DEFAULT": init_cfg["bk_nqa"],
        "main_line_id": mn["line_id"],
        "main_pe": mn["pe"],
        "main_wanip1": mn["wanip1"],
        "main_wanip2": mn["wanip2"],
        "main_peer_ip": mn["pe_docking"],
        "main_ce_docking": mn["ce_docking"],
        "backup_line_id": bk["line_id"],
        "backup_pe": bk["pe"],
        "backup_wanip1": bk["wanip1"],
        "backup_wanip2": bk["wanip2"],
        "backup_peer_ip": bk["pe_docking"],
        "backup_ce_docking": bk["ce_docking"],
        "USG_NE_MAIN_LOOPBACK_BLOCK": "\n".join(main_lo_lines).strip(),
        "USG_NE_BK_LOOPBACK_BLOCK": "\n".join(bk_lo_lines).strip(),
        "USG_NE_MAIN_NAT_GROUP_BLOCK": build_nat_groups_block(m_left_ips, "NEW-MAIN"),
        "USG_NE_BK_NAT_GROUP_BLOCK": build_nat_groups_block(b_left_ips, "NEW-BACKUP"),
        "USG_NE_MAIN_SNAT_BLOCK": build_new_exit_snat_policy_block(m_left_ips, b_left_ips, main_tun, backup_tun),
        "USG_NE_BK_SNAT_BLOCK": "",
    }


def new_exit_generate():
    input_text = ne_left_text.get("1.0", tk.END).strip()
    if not input_text:
        ne_status_var.set("⚠  请先输入新增出口业务数据")
        messagebox.showwarning("提示", "请输入新增出口业务数据")
        return
    parsed, err = parse_usg_new_exit_blocks(input_text)
    if err:
        ne_status_var.set("⚠  新增出口数据格式不正确")
        messagebox.showwarning("提示", err)
        return
    main_tun, e1 = _ne_int(ne_entry_main_tun, "主 Tunnel 号", str(globals().get("USG_NE_MAIN_TUN_DEFAULT", "1001")))
    if e1:
        ne_status_var.set(f"⚠  {e1}")
        messagebox.showwarning("参数错误", e1)
        return
    bk_tun, e2 = _ne_int(ne_entry_bk_tun, "备 Tunnel 号", str(globals().get("USG_NE_BK_TUN_DEFAULT", "1002")))
    if e2:
        ne_status_var.set(f"⚠  {e2}")
        messagebox.showwarning("参数错误", e2)
        return
    main_loop, e3 = _ne_int(ne_entry_main_loop, "主 LoopBack 起始", str(globals().get("USG_NE_MAIN_LOOP_START_DEFAULT", "111")))
    if e3:
        ne_status_var.set(f"⚠  {e3}")
        messagebox.showwarning("参数错误", e3)
        return
    bk_loop, e4 = _ne_int(ne_entry_bk_loop, "备 LoopBack 起始", str(globals().get("USG_NE_BK_LOOP_START_DEFAULT", "211")))
    if e4:
        ne_status_var.set(f"⚠  {e4}")
        messagebox.showwarning("参数错误", e4)
        return
    main_nqa = ne_entry_main_nqa.get().strip() or str(globals().get("USG_NE_MAIN_NQA_DEFAULT", "main2")).strip()
    bk_nqa = ne_entry_bk_nqa.get().strip() or str(globals().get("USG_NE_BK_NQA_DEFAULT", "backup2")).strip()
    if not main_nqa or not bk_nqa:
        ne_status_var.set("⚠  NQA 名称不能为空")
        messagebox.showwarning("参数错误", "主/备 NQA 名称不能为空")
        return
    if main_tun == bk_tun:
        ne_status_var.set("⚠  主备 Tunnel 号不能相同")
        messagebox.showwarning("参数错误", "主备 Tunnel 号不能相同")
        return
    m_cnt = len(parsed["main"]["export_pairs"])
    b_cnt = len(parsed["backup"]["export_pairs"])
    m_end = main_loop + m_cnt - 1
    b_end = bk_loop + b_cnt - 1
    if not (m_end < bk_loop or b_end < main_loop):
        ne_status_var.set("⚠  主备 LoopBack 区间重叠")
        messagebox.showwarning(
            "参数错误",
            f"主备 LoopBack 区间重叠：主[{main_loop},{m_end}]，备[{bk_loop},{b_end}]",
        )
        return
    init_cfg = {
        "main_tun": main_tun,
        "bk_tun": bk_tun,
        "main_loop_start": main_loop,
        "bk_loop_start": bk_loop,
        "main_nqa": main_nqa,
        "bk_nqa": bk_nqa,
    }
    fmt = build_usg_new_exit_format_dict(parsed, init_cfg)
    try:
        output = TEMPLATE_USG_NEW_EXIT_VISUAL.format(**fmt)
    except Exception as ex:
        ne_status_var.set(f"⚠  模板渲染失败: {ex}")
        messagebox.showwarning("模板错误", f"渲染失败：{ex}")
        return
    ne_right_output.delete("1.0", tk.END)
    ne_right_output.insert(tk.END, output)
    total_ips = len(parsed["main"]["export_pairs"]) + len(parsed["backup"]["export_pairs"])
    ne_status_var.set(f"✓  新增出口配置已生成  ·  海外IP:{total_ips}条  ·  Tunnel{main_tun}/Tunnel{bk_tun}")
    log_generate_config(tool="usg_fastip", variant="new_exit", input_text=input_text, output_text=output)


def new_exit_export():
    content = ne_right_output.get("1.0", tk.END).strip()
    if not content:
        ne_status_var.set("⚠  尚无可导出的配置，请先生成")
        messagebox.showwarning("提示", "没有可导出的配置")
        return
    path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")], initialfile="usg_new_exit_config.txt")
    if path:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            ne_status_var.set(f"✓  已导出至：{path}")
            messagebox.showinfo("成功", "文件导出成功")
        except Exception as ex:
            messagebox.showerror("错误", str(ex))


def new_exit_reset():
    ne_left_text.delete("1.0", tk.END)
    ne_right_output.delete("1.0", tk.END)
    ne_entry_main_tun.delete(0, tk.END)
    ne_entry_main_tun.insert(0, str(globals().get("USG_NE_MAIN_TUN_DEFAULT", "1001")))
    ne_entry_bk_tun.delete(0, tk.END)
    ne_entry_bk_tun.insert(0, str(globals().get("USG_NE_BK_TUN_DEFAULT", "1002")))
    ne_entry_main_loop.delete(0, tk.END)
    ne_entry_main_loop.insert(0, str(globals().get("USG_NE_MAIN_LOOP_START_DEFAULT", "111")))
    ne_entry_bk_loop.delete(0, tk.END)
    ne_entry_bk_loop.insert(0, str(globals().get("USG_NE_BK_LOOP_START_DEFAULT", "211")))
    ne_entry_main_nqa.delete(0, tk.END)
    ne_entry_main_nqa.insert(0, str(globals().get("USG_NE_MAIN_NQA_DEFAULT", "main2")))
    ne_entry_bk_nqa.delete(0, tk.END)
    ne_entry_bk_nqa.insert(0, str(globals().get("USG_NE_BK_NQA_DEFAULT", "backup2")))
    ne_status_var.set("↺  已恢复初始状态  ·  等待输入新增出口业务数据")


ne_btn_gen.bind("<Button-1>", lambda e: new_exit_generate())
ne_btn_export.bind("<Button-1>", lambda e: new_exit_export())
ne_btn_reset.bind("<Button-1>", lambda e: new_exit_reset())


def _visual_merge_usg_init(region: str, updates: dict) -> None:
    """all_in_one 可视化编辑器：按 region='hk'|'us'|'flink'|'new_exit' 同步并刷新控件。"""
    g = globals()
    prefix = "HK_" if region == "hk" else ""
    _BOOL_SUFFIXES = frozenset({"DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE"})

    def _pb(val) -> bool:
        s = str(val).strip().lower()
        return s in ("1", "true", "yes", "on", "开")

    for k, v in updates.items():
        gk = prefix + k
        if gk not in g:
            if k in g:
                gk = k
            else:
                continue
        if k in _BOOL_SUFFIXES:
            g[gk] = _pb(v)
        else:
            g[gk] = str(v).strip()
    if region == "flink":
        try:
            fl_entry_main_tun.delete(0, tk.END)
            fl_entry_main_tun.insert(0, str(g.get("USG_FL_MAIN_TUN_DEFAULT", "3000")))
            fl_entry_bk_tun.delete(0, tk.END)
            fl_entry_bk_tun.insert(0, str(g.get("USG_FL_BK_TUN_DEFAULT", "4000")))
        except Exception:
            pass
        return
    if region == "new_exit":
        try:
            ne_entry_main_tun.delete(0, tk.END)
            ne_entry_main_tun.insert(0, str(g.get("USG_NE_MAIN_TUN_DEFAULT", "1001")))
            ne_entry_bk_tun.delete(0, tk.END)
            ne_entry_bk_tun.insert(0, str(g.get("USG_NE_BK_TUN_DEFAULT", "1002")))
            ne_entry_main_loop.delete(0, tk.END)
            ne_entry_main_loop.insert(0, str(g.get("USG_NE_MAIN_LOOP_START_DEFAULT", "111")))
            ne_entry_bk_loop.delete(0, tk.END)
            ne_entry_bk_loop.insert(0, str(g.get("USG_NE_BK_LOOP_START_DEFAULT", "211")))
            ne_entry_main_nqa.delete(0, tk.END)
            ne_entry_main_nqa.insert(0, str(g.get("USG_NE_MAIN_NQA_DEFAULT", "main2")))
            ne_entry_bk_nqa.delete(0, tk.END)
            ne_entry_bk_nqa.insert(0, str(g.get("USG_NE_BK_NQA_DEFAULT", "backup2")))
        except Exception:
            pass
        return
    if region == "hk":
        try:
            hk_reset_net()
        except Exception:
            pass
    else:
        try:
            us_reset_net()
        except Exception:
            pass


def _visual_merge_init_defaults(updates: dict) -> None:
    """兼容旧调用：同时更新 US 和 HK。"""
    _visual_merge_usg_init("us", updates)
    _visual_merge_usg_init("hk", updates)


root.mainloop()
