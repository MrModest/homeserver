function docker_sh () {
    docker exec -t -i $1 /bin/bash
}

function check_port() {
    sudo ss -lptn 'sport = :$1'
}