"""8000 端口黑盒测试 — 全场景数据头 fixtures。

每个数据头都是一份完整的业务输入示例（来源于各场景的 _EXAMPLE_MAP /
现有单元测试），用于驱动对应 generate 路由生成配置。

数据头与场景的对应关系由 SCENARIOS 列表（见 test_full_api.py）维护，
这里只放原始文本，避免循环引用。
"""
from __future__ import annotations

# ═════════════════════════════════════════════════════════════
# ER FastIP 4.0
# ═════════════════════════════════════════════════════════════
ER_HK = """hostname:TEST-CE
LineID:609157A1
PE:szd-ape2
tunnel:vtun1213
wanip:10.22.98.40/30
对接IP:10.255.110.6
LineID:609157A2
PE:szd-ape3
tunnel:vtun1214
wanip:10.22.98.44/30
对接IP:10.255.110.10"""

ER_US = """LineID:609169A1
PE:gzd-upe5
Tunnel:Tunnel0/0/1165
wanip:10.55.14.64/30
PE 对接:192.168.247.17
海外出口ip:
10.60.44.28-218.32.88.83

LineID:609169A5
PE:twb-natpe2
WANIP:10.21.32.124/30
TUNNEL:tun1267
PE Docking:192.168.239.12
BGPSERVER IP:103.252.19.25,43.229.117.226
海外出口ip:
10.60.44.28-218.32.88.83"""

ER_FLINK = """PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.1.0/29
PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.1.0/29
PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.1.0/29"""

ER_NEW_EXIT = """LineID:609353B7
PE： tyo2-natpe4
WANIP: 10.22.86.196/30
TUNNEL: tun1083
PE Docking：192.168.205.67
CE Docking：: 10.22.242.21
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.21.185-103.57.50.44

LineID:609353B8
PE： tyo4-natpe2
WANIP: 10.22.100.120/30
TUNNEL: tun1033
PE Docking：10.33.54.78
CE Docking：: 10.22.242.21
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.21.186-103.57.50.45"""

ER_DOMAIN_SPLIT = """google.com
youtube.com"""

# ═════════════════════════════════════════════════════════════
# ER FastIP 5.0
#   5.0 HK / domain_split 用 MAIN/BACKUP 块格式（与 4.0 不同！）
#   5.0 US / new_exit 用与 4.0 相同的 LineID 格式
# ═════════════════════════════════════════════════════════════
ER5_HK = """MAIN
lineid: 603642Ar3
主PE： szd-natflr2
WANIP: 10.40.25.188/30
TUNNEL: vtun40826
Docking：121.12.81.3
CE LOIP: 10.20.186.235
HKIP：10.60.241.250 --> 103.48.141.157
BGPSERVER IP： 10.10.99.168,10.10.99.169

BACKUP
PE：szc-natbk10
WANIP: 10.41.25.188/30
TUNNEL: vtun50826
Docking： 120.133.129.72
CE LOIP: 10.20.186.235
HKIP：10.60.241.250 --> 103.48.141.157
BGPSERVER IP：10.10.99.198,10.10.99.199
"""

ER5_US = ER_US  # 5.0 US 与 4.0 US 数据头格式一致

# 5.0 US + IPSec：含 IKE/IPSec proposal 块（B1/B2 IPSec + B5/B6 NAT）
ER5_US_IPSEC = """LineID:609430B1
PE:szd-upe3
Tunnel:Tunnel0/0/2013
wanip:10.40.129.148/30
PE 对接:10.200.200.37
CE 对接:10.50.86.74
PE AS号:65510
客户内网路由:10.22.242.223
拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.74
拨号ip:183.56.161.86
秘钥:both-win
--- IKE (ike-peer IPSEC) ---
key-exchange: ikev1/ikev2
proposal 1:
  dh-group: 2
  encryption: aes128 3des
  hash: sha1
dead-peer-detection: no
--- IPsec proposal (IPSEC) ---
proposal 1:
  encryption: aes128 3des
  hash: sha1

LineID:609430B2
PE:szc-upe1
Tunnel:Tunnel0/0/1163
wanip:10.30.37.168/30
PE 对接:10.200.200.27
CE 对接:10.50.118.76
PE AS号:65107
客户内网路由:10.22.242.223
拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.76
拨号ip:120.133.134.72
秘钥:both-win

LineID:609430B5
PE： lax1-natpe7
WANIP: 10.22.113.36/30
TUNNEL: tun2209
PE Docking：192.168.215.12
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.52.46-8.3.6.111

LineID:609430B6
PE： sjc1-natpe3
WANIP: 10.22.115.28/30
TUNNEL: tun1080
PE Docking：10.33.54.118
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.79.99-172.16.212.58
"""

ER5_FLINK = ER_FLINK  # 5.0 飞连与 4.0 数据头格式一致

ER5_NEW_EXIT = """LineID:609430B5
PE： lax1-natpe7
WANIP: 10.22.113.36/30
TUNNEL: tun2209
PE Docking：192.168.215.12
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.52.46-8.3.6.111

LineID:609430B6
PE： sjc1-natpe3
WANIP: 10.22.115.28/30
TUNNEL: tun1080
PE Docking：10.33.54.118
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.79.99-172.16.212.58
"""

# ═════════════════════════════════════════════════════════════
# USG FastIP
# ═════════════════════════════════════════════════════════════
USG_US = """main IPSEC_PE: szd-ape2
main dial_ip: 121.14.82.235
main loopback: 10.18.12.57
main auth_id: 609157A1
LineID:609157A1
PE:lax1-fgpe1
WANIP:10.22.98.40/30
TUNNEL:tun1213
PE对接:10.255.110.6
出口ip:64.81.158.21

backup IPSEC_PE: szc-apebk2
backup dial_ip: 120.133.138.20
backup loopback: 10.18.14.21
backup auth_id: 609157A2
LineID:609157A2
PE:sjc1-fgpe1
WANIP:10.22.32.60/30
TUNNEL:tun2305
PE对接:10.255.111.128
出口ip:172.16.14.118"""

USG_HK = """主 IPSEC_PE: bja-ape1
拨号IP：118.193.100.10
loIP：10.18.5.13
认证ID：608810A10
预共享密钥：both-win

LineID:608810A10
PE： hkg1-fgpe3
WANIP: 10.22.98.40/30
TUNNEL: tun1040
PE对接：10.255.110.48
CE对接：10.18.5.13
出口ip：103.91.158.227;

备 IPSEC_PE: sha-apebk1
拨号IP：101.226.24.131
loIP：10.18.6.25
认证ID：608810A11
预共享密钥：both-win

LineID:608810A11
PE： hkj-fgpe1
WANIP: 10.22.73.52/30
TUNNEL: tun2040
PE对接：10.255.111.40
CE对接：10.18.6.25
出口ip：103.91.158.227;"""

# USG 飞连数据头：含账号 + FPE + 预留IP（与普通 US 不同）
USG_FLINK = """LineID:609526A3
PE:szd-upe3
Tunnel:Tunnel0/0/2017
wanip:10.40.99.44/30
PE 对接:10.255.110.13
CE 对接:10.18.16.58

LineID:609526A4
PE:szc-upe2
Tunnel:Tunnel0/0/1601
wanip:10.40.194.24/30
PE 对接:10.255.111.139
CE 对接:10.18.14.165

账号：60952601@fnetlink.com  密码：BLEIOYxT
账号：60952602@fnetlink.com  密码：uYC3zALF
PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.11.144/29
PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.11.144/29
PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.11.144/29"""

USG_NEW_EXIT = """LineID:609424A1
PE： lax1-fgpe1
WANIP: 10.22.110.24/30
TUNNEL: tun1248
PE对接：10.255.110.6
CE对接：10.18.16.20
出口ip：
10.61.10.78-64.81.20.174
10.61.10.106-64.81.20.178
LineID:609424A2
PE： sjc1-fgpe2
WANIP: 10.22.106.20/30
TUNNEL: tun1229
PE对接：10.255.111.158
CE对接：10.18.14.127
出口ip：
10.60.76.6-172.16.23.8
10.60.76.14-172.16.23.9"""

# ═════════════════════════════════════════════════════════════
# Epoch MPLS
# ═════════════════════════════════════════════════════════════
MPLS_CN = """LineID:609291A1
PE:nna-upe1
Tunnel:Tunnel0/0/1030
wanip:10.40.79.92/30
PE 对接:192.168.204.1
CE 对接:10.40.91.42
PE AS号:65512
PE:nna-ipsecgw1
Tunnel:vtun10013
wanip:10.40.91.40/30
PE 对接:180.142.110.241

LineID:609291A2
PE:szd-upebk2
Tunnel:Tunnel10447
wanip:10.40.195.188/30
PE 对接:192.168.253.80
PE AS号:65531"""

# ═════════════════════════════════════════════════════════════
# AR SD-WAN
# ═════════════════════════════════════════════════════════════
AR_SDWAN = """LineID:604604Hw1
PE:gzd-upe5
Tunnel:Tunnel0/0/1147
wanip:10.40.232.248/30
PE 对接:10.200.200.76
CE 对接:10.50.131.16
拨号PE:gzd-upe5
对接IP:10.200.200.76
LoopIP:10.50.131.16
拨号ip:183.63.68.174
秘钥:both-win

LineID:604604Hw2
PE:szd-upebk1
Tunnel:Tunnel0/0/1605
wanip:10.30.115.252/30
PE 对接:10.200.200.22
CE 对接:10.120.47.20
拨号PE:szd-upebk1
对接IP:10.200.200.22
LoopIP:10.120.47.20
拨号ip:183.56.163.24
秘钥:both-win"""

# ═════════════════════════════════════════════════════════════
# AR 传统组网 · 双线（华为 VRP 语法：sysname / acl / bgp）
# ═════════════════════════════════════════════════════════════
AR_TRADITIONAL = """LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""
