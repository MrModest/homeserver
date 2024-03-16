Ansible playbook to configure a home server

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