
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

