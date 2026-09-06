"""Operator-only approval capture. Creates a NEW config; never overwrites approvals."""
import argparse
import json
from pathlib import Path
from scheduled_refresh import REQUIRED_GUARDS, REQUIRED_RUNNER_FILES, sha
from semantic_snapshot import LAKE_POLICY


def generate(workspace, deployed, destination, python, node, state_dir, gh_config_dir):
    workspace, deployed, destination = Path(workspace).resolve(), Path(deployed).resolve(), Path(destination)
    if deployed.is_relative_to(workspace):
        raise ValueError('Deploy reviewed helper copies outside the updating workspace first')
    guards = set(REQUIRED_GUARDS)
    guards.update('correlations/ops/vps/'+name for name in REQUIRED_RUNNER_FILES)
    # Guard every deployed source companion that exists in the repository, including this generator.
    guards.update('correlations/ops/vps/'+path.name for path in deployed.glob('*.py') if (workspace/'correlations/ops/vps'/path.name).exists())
    hashes = {name: sha(workspace/name) for name in sorted(guards)}
    for name in REQUIRED_RUNNER_FILES:
        if sha(deployed/name) != hashes['correlations/ops/vps/'+name]:
            raise ValueError('Deployment copy differs from approved checkout: '+name)
    config = {'schema_version': 1, 'workspace': str(workspace), 'state_dir': str(Path(state_dir).resolve()),
              'python': str(Path(python).absolute()), 'node': str(Path(node).absolute()),
              'node_version': (workspace/'astronomical-signs/.nvmrc').read_text().strip(),
              'gh_config_dir': str(Path(gh_config_dir).resolve()), 'workers': 2, 'command_timeout_seconds': 7200,
              'semantic_policy': dict(LAKE_POLICY),
              'guard_sha256': hashes, 'runner_sha256': {path.name: sha(path) for path in sorted(deployed.glob('*.py'))}}
    with destination.open('x') as handle:
        json.dump(config, handle, indent=2, sort_keys=True); handle.write('\n')
    destination.chmod(0o600)
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'deployed', 'destination', 'python', 'node', 'state-dir', 'gh-config-dir']:
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    generate(**vars(args))
