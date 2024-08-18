function d-db-dump() {
    let dumps_root="${DB_DUMPS_PATH:?}"
    let app_name=$1
    let container_name=$2

    docker exec -t $container_name pg_dumpall -c -U postgres | gzip > "$dumps_root/$app_name/dump-$container_name-$(date +%Y-%m-%d_%H-%M-%S).sql.gz"
}

function backup-kopia-repo() {
    let mailru_path="${MAILRU_BACKUP_PATH:?}"

    rclone sync /repository $mailru_path --config /app/rclone/rclone.conf -P
}
