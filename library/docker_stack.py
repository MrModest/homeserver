#!/usr/bin/python
from ansible.module_utils.basic import AnsibleModule
import os
import yaml

class DockerStack:
    def __init__(self, module: AnsibleModule) -> None:
        self.module: AnsibleModule = module
        self.name: str = module.params['name']
        self.stack_definition: dict[str, any] = module.params['stack_definition']
        self.templates: dict[str, any] = module.params.get('templates', {})
        self.storage_pools: dict[str, str] = module.params['storage_pools']
        self.default_user: str = module.params.get('default_user', '1000:1000')

        # Determine compose file location (use first pool, typically 'fast')
        self.base_path: str = list(self.storage_pools.values())[0]

    def deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge two dicts, override takes precedence"""
        result = base.copy()
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self.deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def resolve_container(self, container_def: dict[str, any]) -> dict[str, any]:
        """Resolve template and merge with overrides"""
        if 'template' in container_def:
            template_name = container_def['template']
            if template_name not in self.templates.get('containers', {}):
                raise ValueError(f"Template '{template_name}' not found")

            base = self.templates['containers'][template_name].copy()
            overrides = container_def.get('override', {})

            # Remove template/override keys before merging
            container_def = {k: v for k, v in container_def.items() if k not in ['template', 'override']}

            # Merge: base -> container_def -> overrides
            result = self.deep_merge(base, container_def)
            result = self.deep_merge(result, overrides)
            return result

        return container_def

    def parse_volumes(self, volumes: list | dict, container_name: str) -> tuple[list[str], set[str]]:
        """Parse volume definitions and return (volume_list, named_volumes_set)"""
        volume_list: list[str] = []
        named_volumes: set[str] = set()

        if isinstance(volumes, dict):
            # Dict format: {host: container} shorthand
            for host, container in volumes.items():
                if host.startswith('/'):
                    # Absolute path
                    volume_list.append(f"{host}:{container}")
                else:
                    # Relative to default pool
                    host_path = f"{self.base_path}/{host}"
                    volume_list.append(f"{host_path}:{container}")

        elif isinstance(volumes, list):
            # List format: explicit definitions
            for vol_def in volumes:
                if isinstance(vol_def, dict):
                    vol_type = vol_def.get('type', 'bind')

                    if vol_type == 'named':
                        # Named volume
                        vol_name = f"{self.name}-{vol_def['host']}"
                        volume_list.append(f"{vol_name}:{vol_def['container']}")
                        named_volumes.add(vol_name)

                    elif vol_type == 'absolute':
                        # Absolute path
                        volume_list.append(f"{vol_def['host']}:{vol_def['container']}")

                    else:  # bind (default)
                        # Use pool hint if provided
                        pool = vol_def.get('pool', 'fast')
                        if pool not in self.storage_pools:
                            raise ValueError(f"Unknown storage pool '{pool}'. Available: {list(self.storage_pools.keys())}")

                        pool_path = self.storage_pools[pool]
                        host_path = f"{pool_path}/{vol_def['host']}"
                        volume_list.append(f"{host_path}:{vol_def['container']}")

                elif isinstance(vol_def, str):
                    # String format (fallback for compatibility)
                    volume_list.append(vol_def)

        return volume_list, named_volumes

    def ensure_dirs(self) -> bool:
        """Create volume directories with correct permissions"""
        changed = False

        for container_name, container_def in self.stack_definition.get('containers', {}).items():
            container = self.resolve_container(container_def)

            if 'volumes' not in container:
                continue

            # Determine user for this container
            user = container.get('user', self.default_user)
            if ':' in str(user):
                uid, gid = map(int, str(user).split(':'))
            else:
                uid = gid = int(user)

            volumes, _ = self.parse_volumes(container['volumes'], container_name)

            for vol in volumes:
                if ':' not in vol:
                    continue

                host_path = vol.split(':')[0]

                # Skip named volumes and non-absolute paths
                if not host_path.startswith('/'):
                    continue

                if not os.path.exists(host_path):
                    os.makedirs(host_path, mode=0o754)
                    os.chown(host_path, uid, gid)
                    changed = True

        return changed

    def generate_compose(self) -> dict[str, any]:
        """Generate docker-compose.yml structure"""
        compose: dict[str, any] = {
            'name': self.name,
            'services': {}
        }

        all_named_volumes: set[str] = set()

        for container_name, container_def in self.stack_definition.get('containers', {}).items():
            container = self.resolve_container(container_def)

            # Build service definition
            service_name = f"{self.name}_{container_name}" if container_name != 'main' else self.name
            service: dict[str, any] = {}

            # Image
            if 'image' in container:
                img = container['image']
                service['image'] = f"{img['repository']}:{img['tag']}"

            # Container name
            service['container_name'] = service_name

            # Restart policy
            service['restart'] = container.get('restart', 'unless-stopped')

            # User
            if 'user' in container:
                service['user'] = str(container['user'])
            else:
                service['user'] = self.default_user

            # Environment variables
            if 'env_vars' in container:
                service['environment'] = container['env_vars']

            # Volumes
            if 'volumes' in container:
                volumes, named_vols = self.parse_volumes(container['volumes'], container_name)
                service['volumes'] = volumes
                all_named_volumes.update(named_vols)

            # Ports
            if 'ports' in container:
                service['ports'] = container['ports']

            # Networks
            service['networks'] = [self.name]

            # Depends on
            if 'depends_on' in container:
                # Prefix dependency names with stack name if not main
                deps = []
                for dep in container['depends_on']:
                    if dep == 'main':
                        deps.append(self.name)
                    else:
                        deps.append(f"{self.name}_{dep}")
                service['depends_on'] = deps

            # Command
            if 'command' in container:
                service['command'] = container['command']

            # Healthcheck
            if 'healthcheck' in container:
                service['healthcheck'] = container['healthcheck']

            # Resource limits
            if 'resource_limits' in container:
                service['deploy'] = {
                    'resources': {
                        'limits': container['resource_limits']
                    }
                }

            # Logging (default)
            service['logging'] = {
                'driver': 'json-file',
                'options': {
                    'max-size': '1m',
                    'max-file': '1'
                }
            }

            compose['services'][service_name] = service

        # Add named volumes
        if all_named_volumes:
            compose['volumes'] = {vol: {} for vol in all_named_volumes}

        # Add network
        compose['networks'] = {
            self.name: {
                'driver': 'bridge'
            }
        }

        return compose

    def generate_env_file(self) -> dict[str, str]:
        """Generate .env file with stack-level variables"""
        env_vars = {
            'COMPOSE_PROJECT_NAME': self.name,
        }

        # Add common service names for dependencies
        for container_name in self.stack_definition.get('containers', {}).keys():
            if container_name == 'postgres':
                service_name = f"{self.name}_{container_name}"
                env_vars['POSTGRES_HOST'] = service_name
                env_vars['POSTGRES_PORT'] = '5432'
            elif container_name == 'redis':
                service_name = f"{self.name}_{container_name}"
                env_vars['REDIS_HOST'] = service_name
                env_vars['REDIS_PORT'] = '6379'

        # Add reverse proxy info if configured
        for container_name, container_def in self.stack_definition.get('containers', {}).items():
            container = self.resolve_container(container_def)
            if 'reverse_proxy' in container:
                # Assuming you'll pass domain info through module params
                domain = self.module.params.get('app_domain', f"{self.name}.example.com")
                env_vars['APP_DOMAIN'] = f"https://{domain}"

        return env_vars

    def write_files(self, compose: dict[str, any], env_vars: dict[str, str]) -> None:
        """Write docker-compose.yml and .env files"""
        # Write compose file
        compose_path = f"{self.base_path}/docker-compose.yml"
        with open(compose_path, 'w') as f:
            yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

        # Write .env file
        env_path = f"{self.base_path}/.env"
        with open(env_path, 'w') as f:
            for key, val in env_vars.items():
                f.write(f"{key}={val}\n")
        os.chmod(env_path, 0o600)

def main() -> None:
    module: AnsibleModule = AnsibleModule(
        argument_spec={
            'name': {'type': 'str', 'required': True},
            'stack_definition': {'type': 'dict', 'required': True},
            'templates': {'type': 'dict', 'default': {}},
            'storage_pools': {'type': 'dict', 'required': True},
            'default_user': {'type': 'str', 'default': '1000:1000'},
            'app_domain': {'type': 'str', 'default': None},
            'state': {'type': 'str', 'default': 'present', 'choices': ['present', 'absent']}
        }
    )

    stack: DockerStack = DockerStack(module)

    changed: bool = stack.ensure_dirs()
    compose: dict[str, any] = stack.generate_compose()
    env_vars: dict[str, str] = stack.generate_env_file()
    stack.write_files(compose, env_vars)

    module.exit_json(
        changed=changed,
        compose_path=f"{stack.base_path}/docker-compose.yml",
        env_path=f"{stack.base_path}/.env"
    )

if __name__ == '__main__':
    main()
