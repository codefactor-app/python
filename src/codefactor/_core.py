"""Project-local Core selection. Analysis never performs network requests."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from . import _installer

class ConfigError(RuntimeError):
    pass


VALUE_OPTIONS = {'--config', '--file', '--root', '--format', '--out', '--lang', '--limit', '--group-by', '--function', '--from', '--to', '--depth', '--max-paths', '--architecture-profile', '--log-level', '--color', '--port', '--host', '--a', '--b', '--category'}


def argument_context(args):
    config = root = None
    positional = []
    iterator = iter(args)
    for arg in iterator:
        if arg == '--':
            positional.extend(iterator)
            break
        if arg.startswith('--'):
            key, separator, value = arg.partition('=')
            if key in VALUE_OPTIONS:
                value = value if separator else next(iterator, None)
                if key == '--config' or (key == '--file' and positional[:1] == ['config']):
                    config = value
                if key == '--root':
                    root = value
        elif not arg.startswith('-'):
            positional.append(arg)
    if root is None and positional and positional[0] in {'scan', 'metrics', 'serve', 'ast'}:
        root = next(iter(positional[1:]), None)
    if config is None and positional[:1] == ['config'] and positional[1:2] in (['check'], ['show']):
        config = 'analyzer.yaml'
    return {'config': config, 'root': root}


def selection(config=None, root=None, cwd=None):
    cwd = Path(cwd or Path.cwd())
    directory = (cwd / (root or '.')).resolve()
    if directory.is_file():
        directory = directory.parent
    config = (cwd / config).resolve() if config else next((directory / name for name in ('analyzer.yaml', 'analyzer.yml') if (directory / name).is_file()), None)
    if config:
        config = config.resolve()
    version = os.environ.get('CODEFACTOR_CORE_VERSION')
    if config:
        import yaml
        class Loader(yaml.SafeLoader):
            def construct_mapping(self, node, deep=False):
                keys = set()
                for key_node, _ in node.value:
                    if key_node.tag == 'tag:yaml.org,2002:merge':
                        continue
                    key = self.construct_object(key_node, deep=deep)
                    try:
                        if key in keys:
                            raise yaml.constructor.ConstructorError(None, None, 'duplicate YAML key', key_node.start_mark)
                        keys.add(key)
                    except TypeError:
                        raise yaml.constructor.ConstructorError(None, None, 'invalid YAML key', key_node.start_mark)
                return super().construct_mapping(node, deep=deep)
        try:
            document = yaml.load(config.read_text(encoding='utf-8'), Loader=Loader)
        except (yaml.YAMLError, OSError) as error:
            raise ConfigError(str(error)) from error
        if document is not None and not isinstance(document, dict):
            raise ConfigError('Codefactor config must be a mapping')
        if version is None and document is not None and 'core' in document:
            if not isinstance(document['core'], dict):
                raise ConfigError('core must be a mapping')
            version = document['core'].get('version', 'latest')
            if version is None:
                raise ConfigError('core.version must be latest or X.Y.Z')
    version = 'latest' if version is None else version
    if not isinstance(version, str) or not re.fullmatch(r'latest|[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ConfigError('core.version must be latest or X.Y.Z')
    release = json.loads((_installer.ROOT / 'release.json').read_text(encoding='utf-8'))
    base = os.environ.get('CODEFACTOR_RELEASE_BASE_URL') or release['base_url']
    latest = '' if os.environ.get('CODEFACTOR_RELEASE_BASE_URL') else release['latest_url']
    source = hashlib.sha256((base.rstrip('/') + '\n' + latest.rstrip('/')).encode()).hexdigest()
    return version, (config.parent if config else directory) / '.codefactor/core' / source / _installer.platform_id()


def validate_manifest(manifest, version='latest'):
    platform = _installer.platform_id()
    filename = f'codefactor-{platform}' + ('.exe' if os.name == 'nt' else '')
    if not isinstance(manifest, dict) or not isinstance(manifest.get('version'), str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', manifest['version']) or (version != 'latest' and manifest['version'] != version) or manifest.get('platform') != platform or manifest.get('file') != filename or not isinstance(manifest.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', manifest['sha256']) or type(manifest.get('size')) is not int or not 0 < manifest['size'] <= 128 * 1024 * 1024:
        raise RuntimeError('Invalid Codefactor release manifest')
    return manifest


def cached_path(directory, manifest):
    return directory / manifest['version'] / manifest['sha256'] / ('codefactor.exe' if os.name == 'nt' else 'codefactor')


def verified(binary, manifest):
    return binary.is_file() and binary.stat().st_size == manifest['size'] and hashlib.sha256(binary.read_bytes()).hexdigest() == manifest['sha256']


def resolve_binary(**context):
    if override := os.environ.get('CODEFACTOR_BINARY'):
        return Path(override).resolve()
    version, directory = selection(**context)
    active = directory / 'active.json'
    if active.is_file():
        manifest = validate_manifest(json.loads(active.read_text(encoding='utf-8')))
        if version == 'latest' or version == manifest['version']:
            binary = cached_path(directory, manifest)
            if not verified(binary, manifest):
                raise RuntimeError('Codefactor cached binary is damaged; run codefactor core update')
            return binary
    if version != 'latest':
        for metadata in sorted((directory / version).glob('*/codefactor.manifest.json')):
            manifest = validate_manifest(json.loads(metadata.read_text(encoding='utf-8')), version)
            binary = cached_path(directory, manifest)
            if metadata.parent.name == manifest['sha256'] and verified(binary, manifest):
                return binary
    binary = _installer.binary_path()
    if binary.is_file():
        if version == 'latest':
            return binary
        metadata = binary.parent / 'codefactor.manifest.json'
        if metadata.is_file():
            manifest = validate_manifest(json.loads(metadata.read_text(encoding='utf-8')))
            if version == manifest['version'] and verified(binary, manifest):
                return binary
    suffix = f" --config {context['config']}" if context.get('config') else ''
    raise RuntimeError(f'Codefactor Core {version} is not installed; run codefactor core update{suffix}')


def update(**context):
    if override := os.environ.get('CODEFACTOR_BINARY'):
        binary = Path(override).resolve()
        if not binary.is_file():
            raise RuntimeError('CODEFACTOR_BINARY does not point to a file')
        return 'external', binary
    version, directory = selection(**context)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / '.update.lock'
    for _ in range(300):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(0.1)
    else:
        raise RuntimeError(f'Codefactor update is locked; if no update is running remove {lock}')
    temporary = None
    try:
        release = json.loads((_installer.ROOT / 'release.json').read_text(encoding='utf-8'))
        base = _installer.release_base(release, version)
        manifest = validate_manifest(json.loads(_installer.download(f'{base}/manifest-{_installer.platform_id()}.json', 65536)), version)
        binary = cached_path(directory, manifest)
        _installer.install(version=version, destination=binary, manifest=manifest)
        import tempfile
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(manifest).encode())
        os.replace(temporary, directory / 'active.json')
        return manifest['version'], binary
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
        lock.rmdir()


def update_command(args):
    import argparse
    parser = argparse.ArgumentParser(prog='codefactor core')
    sub = parser.add_subparsers(dest='command', required=True)
    update_parser = sub.add_parser('update', help='Download the configured Core without updating this package')
    update_parser.add_argument('--config')
    options = parser.parse_args(args)
    version, binary = update(config=options.config)
    print(f'Codefactor Core {version}: {binary}')
    return 0
