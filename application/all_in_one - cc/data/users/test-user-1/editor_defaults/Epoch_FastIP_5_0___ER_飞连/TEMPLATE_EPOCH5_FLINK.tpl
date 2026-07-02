set protocols failover2 track tomain source-address '{ER_FL_FAILOVER_SRC}'
set protocols failover2 track tomain target '{ER_FL_MAIN_NH_DEFAULT}'
set protocols failover2 track tomain type 'icmp'

set protocols failover2 route {route1} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'
set protocols failover2 route {route2} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'
set protocols failover2 route {route3} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'

set protocols static route {route1} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10
set protocols static route {route2} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10
set protocols static route {route3} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10

set firewall group network-group LAN-NET network {route1}
set firewall group network-group LAN-NET network {route2}
set firewall group network-group LAN-NET network {route3}