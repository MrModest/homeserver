function docker_sh () {
    docker exec -t -i $1 /bin/bash
}
