# ER 域名分流 · 完整模板（占位符与「我来定模板」初始化一致；{ER_DS_DOMAINLIST_COMPUTED}、{ER_DS_POLICY_ROUTE_COMPUTED} 等由预览根据 address-group 推导；domainlist=/opt 文件名均为 A+组名）
# --- 写入域名列表（shell）---
sudo tee /opt/{ER_DS_DOMAINLIST_COMPUTED}.txt >/dev/null <<'EOF'
{ER_DS_DOMAINS_DEFAULT}
EOF
sudo chmod 777 /opt/{ER_DS_DOMAINLIST_COMPUTED}.txt

set firewall group address-group {ER_DS_ADDR_GROUP_DEFAULT}

set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} address-group '{ER_DS_ADDR_GROUP_DEFAULT}'
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} file '/opt/{ER_DS_DOMAINLIST_COMPUTED}.txt'
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} recursion-desired
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} server '{ER_DS_DNS1_DEFAULT}'
{ER_DS_OPT_DNS2_LINE}
{ER_DS_OPT_POLICY_ROUTE_BLOCK}set protocols static route {ER_DS_TABLE_NH_PRIMARY_DEFAULT}/32 next-hop {ER_DS_STATIC32_PRIMARY_NH_DEFAULT}{ER_DS_OPT_TRACK_SUFFIX}
{ER_DS_OPT_S32BAK_LINE}
{ER_DS_OPT_FNET_BLOCK}
