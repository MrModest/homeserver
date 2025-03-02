# Ansible playbook to configure a home server

> [!WARNING]
> Still In Progress

## Requirements

- Ubuntu Server 22.04 LTS
- First installation should be finished before this playbook to run

## Recommended configurations
- Boot system and root in a dedicated SSD drive with the default ext4 partitioning and stores nothing but OS
- All other drives are formatted into ZFS pools
  - a "fast" pool with 2 SSD in a mirror mode (~256Gb each)
    - to store applications data, caches and other I/O demanded files
  - a "slow" pool with 2 HDD in a mirror mode (~2Tb each)
    - to store media files or other big amoung of applications data (like photos or documents)
  - a "very big and slow" pool with 1 HDD in a stripe mode (~8Tb)
    - to store big files that doesn't need to be redundant or backed up (for example, something that easily retractable from the internet)

## Remarks
- Users
  - `apps` to run all non-priviliged contaners
  - `homessh` to connect via ssh
  - `sambashare` to connect to SMB share via clients
- Variables
  - with prefix `g_`
    - described in `group_vars/all.yml`
    - meant to be "global" across the whole homeserver
    - to store all global values except passwords/secrets
  - with prefix `v_`
    - described in `vars/vault.yml`
    - meant to store passwords and secrets
    - encrypted with password written in `.vault_pass` file
    - not supposed to be shared and should be stored only localy
  - with prefix `p_`
    - described in `main.yaml` (the entrypoint-playbook) in `vars` section
    - meant to be playbook-run scoped variables
  - another prefixes like `bkrs_`
    - described in a dedicated role's `defaults` directory
    - meant to be a role-scoped variables aka "role's input parameters"
- Permissions
  - `0644` - More relevant for files
    - Owner can read & write.
    - Group and Other can only read
  - `0754` - More relevant for directories
    - Owner can everything
    - Group can read and "open" directory (see what inside), but can't write
    - Other can only see the directory, but can't "go inside" nor write.
- Directory structure
  - `/` only for OS
  - `/mnt/pools` to mount ZFS pools
  - `/mnt/pools/<fast|slow>/apps-data/<app's name>` stores all stuff dedicated to the given app directly
  - `/mnt/pools/fast/docker/data-root` is dedicated to store all docker related stuff instead of `/var/lib/docker`
- [Files Structure](docs/Files%20Structure.md)

## Docker daemon configuration

```jsonc
{
  "data-root": "/mnt/pools/fast/docker/data-root",
  "storage-driver": "overlay2", // no needs to use zfs-driver since zfs 2.0
  "log-driver": "json-file", // for 'promtail' and 'loki'
  "log-opts": {
    "max-size": "1m",
    "max-file": "1"
  },
  "metrics-addr" : "0.0.0.0:9323", // for 'prometheus'
  "experimental" : true
}
```

---


# ToDo

### Server
- [ ] Configure observability
  - [x] Configure Docker containers observability with Loki/Prometheus/Grafana
  - [x] Configure internal bridges between Prometheus and apps that pushes metrics
    - [x] Fix docker metrics providing
    - [x] Fix immich metrics providing
  - [ ] Configure host logs and metrics
    - [x] Install Promtail to push `/var/log/*` logs to Loki
    - [x] Push Storage/RAM/CPU of host machine to Prometheus
    - [ ] Collect ZFS related metrics
      - [ ] Error rate
      - [ ] Datasets
      - [ ] Snapshots
- [x] Configure Samba
  - [ ] Configure MacOS TimeMachine backup
- [x] Configure reverse-proxy
- [x] Configure HTTPS
- [ ] Configure backups
  - [x] Install [backrest](https://github.com/garethgeorge/backrest)
  - [x] Schedule local backups
  - [ ] Shedule remote backups
    - [x] WebDAV MailRu Cloud
    - [x] Google Drive
    - [ ] Yandex.Disk
    - [ ] Mega
    - [ ] Backblaze B2 (?)
  - [x] Configure DB dumps
  - [ ] Configure auto snapshoting
  - [ ] Configure backuping from snapshots
- [x] Configure remote access without public exposure (Tailscale)
- [x] Configure local DNS
  - [x] Setup [PiHole](https://github.com/pi-hole/docker-pi-hole/?tab=readme-ov-file#quick-start)

### Docker Applications
- [x] [Immich](https://github.com/immich-app/immich)
  - [ ] Migrate albums information from Google Photos
- [ ] ~~[Dockge](https://github.com/louislam/dockge)~~
- [x] [Paperless](https://github.com/paperless-ngx/paperless-ngx)
- [ ] [Nextcloud](https://github.com/nextcloud/all-in-one)
  - or OwnCloud Infinite Scale 
  - or OpenCloud
- [x] [homepage](https://github.com/gethomepage/homepage)
- [x] [Portainer](https://docs.portainer.io/v/2.20/start/install-ce/server/docker/linux)
- [x] [Hoarder](https://github.com/hoarder-app/hoarder)
- [X] [Wallos](https://github.com/ellite/Wallos)
- [ ] [Cronicle](https://github.com/jhuckaby/Cronicle)
  - [ ] Move to docker container
- [ ] [AriaNg](https://hub.docker.com/r/hurlenko/aria2-ariang)
- [ ] [metube](https://github.com/alexta69/metube)
- [ ] [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF/tree/main)
- [ ] [Jellyfin](https://jellyfin.org/docs/general/installation/container)
- [x] [Grist](https://github.com/gristlabs/grist-core)
- [ ] [n8n](https://docs.n8n.io/hosting/installation/docker/)
- [ ] [NoteCalc](https://github.com/bbodi/notecalc3)
- [ ] [Open Speed Test](https://hub.docker.com/r/openspeedtest/latest)
- [ ] [pgAdmin](https://hub.docker.com/r/dpage/pgadmin4/)
- [ ] Syncthings
  - [ ] Configure sync Paperless folders to NextCloud

### "Bare metal" Applications
  - [ ] ~~[Cockpit](https://cockpit-project.org/)~~
  - [ ] [Kasm](https://www.kasmweb.com/docs/latest/install/single_server_install.html)
