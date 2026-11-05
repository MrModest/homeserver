```
/mnt/pools/
├── fast <-- SSD pool
│   ├── apps-data <-- apps' volumes
│   │   ├── homepage
│   │   ├── immich
│   │   ├── nginx
│   │   ├── observability
│   │   │   ├── grafana
│   │   │   ├── loki
│   │   │   ├── prometheus
│   │   │   └── promtail
│   │   └── portainer
│   └── docker
│       └── compose-files
│           ├── homepage
│           │   ├── compose.yml
│           │   └── .env
│           ├── immich
│           ├── nginx
│           ├── observability
│           └── portainer
└── slow <-- HDD pool
    ├── apps-data <-- same as '/fast/apps-data', but in HDD drives
    │   ├── immich
    │   └── paperless
    ├── backups
    │   ├── backrest
    │   │   └── repos
    │   └── db_dumps
    │       ├── immich
    │       └── paperless
    └── shared <-- SMB shares' root
        ├── media <-- dataset slow/media; apps:apps; applications only, no SMB
        ├── samba <-- dataset slow/samba; sambashare:sambashare; empty new SMB share
        └── time-machine <-- dataset slow/time-machine; sambashare:sambashare; SMB
            └── Mac13.sparsebundle
```
