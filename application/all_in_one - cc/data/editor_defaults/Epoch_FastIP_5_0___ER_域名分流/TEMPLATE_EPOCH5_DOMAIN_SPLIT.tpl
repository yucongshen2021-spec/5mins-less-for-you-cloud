# ER 5.0 域名分流 · VyOS set 语法
# --- 写入域名列表（shell）---
sudo tee /opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt >/dev/null <<'EOF'
{ER5_DS_DOMAINS_DEFAULT}
EOF
sudo chmod 777 /opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt

set firewall group address-group {ER5_DS_ADDR_GROUP_DEFAULT}

set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} address-group '{ER5_DS_ADDR_GROUP_DEFAULT}'
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} file '/opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt'
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} name-server {ER5_DS_DNS1_DEFAULT}
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} recursion-desired
{ER5_DS_OPT_DNS2_LINE}
{ER5_DS_OPT_POLICY_ROUTE_BLOCK}set protocols static route {ER5_DS_TABLE_NH_PRIMARY_DEFAULT}/32 next-hop {ER5_DS_STATIC32_PRIMARY_NH_DEFAULT}{ER5_DS_OPT_TRACK_SUFFIX}
{ER5_DS_OPT_S32BAK_LINE}
{ER5_DS_OPT_FNET_BLOCK}