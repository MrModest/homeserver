Ansible playbook to configure a home server <br/>
⚠️ Still in WIP

# Requirements

- Ubuntu 22.04 LTS
- First installation should be finished before this playbook to run

# Recommended configurations
- Boot system and root in a dedicated SSD drive with the default ext4 partitioning and stores nothing but OS
- All other drives are formatted into ZFS pools
  - a "fast" pool with 2 SSD in a mirror mode (~256Gb each)
    - to store applications data, caches and other I/O demanded files
  - a "slow" pool with 2 HDD in a mirror mode (~2Tb each)
    - to store media files or other big amoung of applications data (like photos or documents)
  - a "very big and slow" pool with 1 HDD in a stripe mode (~8Tb)
    - to store big files that doesn't need to be redundant or backed up (for example, something that easily retractable from the internet)
  
# Remarks
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

# Docker daemon configuration

```jsonc
{
  "data-root": "{{ dcr_daemon_conf.data_root }}", # https://docs.docker.com/engine/reference/commandline/dockerd/#on-linux
  "storage-driver": "zfs", #  https://docs.docker.com/storage/storagedriver/select-storage-driver/
  "log-driver": "loki", # https://grafana.com/docs/loki/latest/send-data/docker-driver/configuration/#change-the-default-logging-driver
  "log_opts": { #  https://grafana.com/docs/loki/latest/send-data/docker-driver/configuration/#supported-log-opt-options
    "loki-url": "{{ dcr_daemon_conf.logger.host }}:{{ dcr_daemon_conf.logger.port }}/loki/api/v1/push",
    "loki-batch-size": "400",
    "max-size": "100m",
    "max-file": "2"
  },
  "metrics-addr" : "{{ dcr_daemon_conf.metrics.host }}:{{ dcr_daemon_conf.metrics.port }}", # For Prometheus metrics - https://freedium.cfd/https://medium.com/geekculture/how-to-monitor-docker-metrics-using-prometheus-grafana-707b970f1f06
  "experimental" : true
}
```

```json
{
  "data-root": "/mnt/pools/fast/docker/data-root",
  "storage-driver": "zfs",
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://127.0.0.1:3100/loki/api/v1/push",
    "loki-batch-size": "400",
    "max-size": "100m",
    "max-file": "2"
  },
  "metrics-addr" : "127.0.0.1:9323",
  "experimental" : true
}
```

# ToDo

- Server
  - [ ] Configure observability
    - [x] Configure Docker containers observability with Loki/Prometheus/Grafana
    - [ ] Configure internal bridges between Prometheus and apps that pushes metrics
      - [ ] Fix docker metrics providing
      - [ ] Fix immich metrics providing
    - [ ] Configure host logs and metrics
      - [ ] Install Promtail to push `/var/log/*` logs to Loki
      - [ ] Push Storage/RAM/CPU of host machine to Prometheus
      - [ ] Collect ZFS related metrics
  - [x] Configure Samba
  - [ ] Configure reverse-proxy
  - [ ] Configure HTTPS
  - [ ] Configure backups
  - [ ] Configure Tailscale
- Applications
  - [x] Immich
  - [x] Dockge
  - [ ] Paperless
  - [ ] Nextcloud
  - [ ] homepage
  - [ ] Portainer
  - [ ] AriaNg
  - [ ] metube
  - [ ] Stirling-PDF
  - [ ] Jellyfin
  - [ ] Grist
  - [ ] n8n
  - [ ] Kasm
  - [ ] Cockpit
  - [ ] NoteCalc
  - [ ] Open Speed Test
  - [ ] PiHole (for local DNS)