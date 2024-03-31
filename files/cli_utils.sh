function docker_sh () {
    docker exec -t -i $1 /bin/bash
    if [ "$?" -ne "0" ]
    then
        docker exec -t -i $1 /bin/sh
    fi
}

function check_port() {
    sudo ss -lptn 'sport = :$1'
}

function install_z() {
    mkdir ~/.cli_customs
    wget "https://raw.githubusercontent.com/rupa/z/master/z.sh" -O ~/.cli_customs/z.sh
    echo "source ~/.cli_customs/z.sh" >> ~/.bashrc
}