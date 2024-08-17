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
│       ├── compose-files
│       │   ├── homepage
│       │   │   ├── compose.yml
│       │   │   └── .env
│       │   ├── immich
│       │   ├── nginx
│       │   ├── observability
│       │   └── portainer
│       └── data-root <-- `/var/lib/docker`
└── slow <-- HDD pool
    ├── apps-data <-- same as '/fast/apps-data', but in HDD drives
    │   └── immich
    └── shared <-- SMB shares' root
        └── shared
```
