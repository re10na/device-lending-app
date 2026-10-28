#!/bin/bash
# MySQL の初回起動時（db-data ボリュームが空のとき）だけ実行される。
# 社員・機種のマスタ（master）を作り、app に sql/migrations を順に流す。
set -euo pipefail

run_sql() {
    mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" "$@"
}

run_sql < /sql/seed/master.sql
# アプリからはマスタを読むだけ
run_sql -e "GRANT SELECT ON master.* TO '${MYSQL_USER}'@'%'"

for path in /sql/migrations/*.sql; do
    echo "apply ${path}"
    run_sql "$MYSQL_DATABASE" < "$path"
done
