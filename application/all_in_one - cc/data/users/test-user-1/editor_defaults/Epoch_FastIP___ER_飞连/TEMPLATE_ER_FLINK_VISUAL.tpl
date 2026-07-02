set track name flink failure-count '2'
set track name flink success-count '2'
set track name flink test 0 resp-time '5'
set track name flink test 0 target {ER_FL_MAIN_NH_DEFAULT}
set track name flink test 0 ttl-limit '1'
set track name flink test 0 type 'ping'

set protocols static route {route1} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink
set protocols static route {route2} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink
set protocols static route {route3} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink

set protocols static route {route1} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
set protocols static route {route2} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
set protocols static route {route3} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
