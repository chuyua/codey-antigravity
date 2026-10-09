#!/usr/bin/env python3
"""Package platform binaries with exact native schema and reconstructable source."""
import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('example', type=pathlib.Path)
parser.add_argument('output', type=pathlib.Path)
parser.add_argument('--cargo', default='cargo')
parser.add_argument('--target', required=True)
args = parser.parse_args()
example = args.example.resolve()
repo = example.parents[2]
version = '0.10.0'


def describe_target(target: str) -> dict:
    """Map a Rust target triple to manifest, artifact and bundle labels."""
    if target.endswith('-pc-windows-msvc') or target.endswith('-pc-windows-gnu'):
        rust_arch = target.split('-', 1)[0]
        return {
            'target': target, 'platform': 'windows', 'rust_arch': rust_arch,
            'label': ('x64' if rust_arch == 'x86_64' else rust_arch),
            'library': 'codey_plugin_antigravity_router.dll',
            'proxy': 'antigravity-proxy.exe',
            'proxy_source': pathlib.Path('release/antigravity-proxy.exe'),
            'runtime': 'powershell',
            'gnu': target.endswith('-gnu'),
        }
    if target.endswith('-apple-darwin'):
        rust_arch = target.split('-', 1)[0]
        return {
            'target': target, 'platform': 'macos', 'rust_arch': rust_arch,
            'label': ('x64' if rust_arch == 'x86_64' else 'arm64'),
            'library': 'libcodey_plugin_antigravity_router.dylib',
            'proxy': 'antigravity-proxy',
            'proxy_source': pathlib.Path('release/antigravity-proxy'),
            'runtime': 'posix',
            'gnu': False,
        }
    if target.endswith('-unknown-linux-gnu') or target.endswith('-unknown-linux-musl'):
        rust_arch = target.split('-', 1)[0]
        return {
            'target': target, 'platform': 'linux', 'rust_arch': rust_arch,
            'label': ('x64' if rust_arch == 'x86_64' else 'arm64'),
            'library': 'libcodey_plugin_antigravity_router.so',
            'proxy': 'antigravity-proxy',
            'proxy_source': pathlib.Path('release/antigravity-proxy'),
            'runtime': 'posix',
            'gnu': False,
        }
    raise SystemExit(f'Unsupported release target: {target}')


spec = describe_target(args.target)
bundle_name = f'codey-antigravity-{version}-{spec["platform"]}-{spec["label"]}'
if args.output.exists():
    raise SystemExit('Output already exists; choose a new directory')
args.output.mkdir(parents=True)
bundle = args.output / bundle_name
(bundle / 'bin').mkdir(parents=True)
native = args.output / f'antigravity-router-{version}-{spec["platform"]}-{spec["label"]}.codey-plugin'
library = repo / 'target' / args.target / 'release' / spec['library']
if not library.is_file():
    raise SystemExit(f'Native library not found: {library}')
proxy = example / 'proxy-rust' / 'target' / args.target / spec['proxy_source']
if not proxy.is_file():
    raise SystemExit(f'Proxy binary not found: {proxy}')
subprocess.run([
    sys.executable, str(repo / 'scripts/package-plugin.py'),
    '--library', str(library), '--config', str(example / 'config.json'),
    '--output', str(native), '--id', 'codey.antigravity-router',
    '--name', 'Antigravity', '--version', version,
    '--platform', spec['platform'], '--arch', spec['rust_arch'],
    '--capability', 'request.lifecycle.v1', '--capability', 'provider.route.v1',
    '--header', 'x-antigravity-provider', '--lifecycle-failure-policy', 'continue',
], check=True)
subprocess.run([
    sys.executable, str(example / 'scripts/verify-native.py'), str(native),
    '--platform', spec['platform'], '--arch', spec['rust_arch'], '--entry', f'lib/{spec["library"]}',
], check=True)
shutil.copy2(native, bundle / native.name)
shutil.copy2(proxy, bundle / 'bin' / spec['proxy'])

# Per-platform documentation and runtime entrypoints.
shared_docs = ('README.md', 'INSTALL.md', 'BUILDING.md', 'NOTICE.md', 'LICENSE')
if spec['runtime'] == 'powershell':
    entrypoints = ('start-proxy.ps1', 'stop-proxy.ps1')
    script_files = ('runtime.ps1', 'install.ps1', 'verify-bundle.ps1', 'LICENSE')
else:
    entrypoints = ('start-proxy.sh', 'stop-proxy.sh')
    script_files = ('runtime.sh', 'install.sh', 'verify-bundle.sh', 'LICENSE')
for filename in shared_docs + entrypoints:
    destination = bundle / filename
    shutil.copy2(example / filename, destination)
    if filename.endswith('.sh'):
        destination.chmod(destination.stat().st_mode | 0o111)
(bundle / 'scripts').mkdir()
for filename in script_files:
    source = example / 'scripts' / filename
    destination = bundle / 'scripts' / filename
    shutil.copy2(source, destination)
    if filename.endswith('.sh'):
        destination.chmod(destination.stat().st_mode | 0o111)
shutil.copy2(example / 'proxy-rust/LICENSE', bundle / 'bin/LICENSE')
subprocess.run([
    sys.executable, str(example / 'scripts/collect-licenses.py'),
    str(bundle / 'third-party-licenses'), '--target', args.target, '--cargo', args.cargo,
], check=True)
if spec['gnu']:
    shutil.copytree(example / 'toolchain-runtime-licenses', bundle / 'toolchain-runtime-licenses')

# A minimal workspace uses the actual SDK source and pinned versions, without the host.
with tempfile.TemporaryDirectory(prefix='codey-antigravity-source-') as temp:
    source = pathlib.Path(temp)
    source_example = source / 'examples/plugins/antigravity-router'
    for filename in (
        'Cargo.toml', 'config.json', 'README.md', 'INSTALL.md', 'BUILDING.md',
        'NOTICE.md', 'LICENSE', '.gitignore', 'start-proxy.ps1', 'stop-proxy.ps1',
        'start-proxy.sh', 'stop-proxy.sh',
    ):
        origin = example / filename
        if not origin.is_file():
            continue
        destination = source_example / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    for folder in ('src', 'tests', 'scripts', 'toolchain-runtime-licenses'):
        shutil.copytree(example / folder, source_example / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'auth.json', '.env'))
    shutil.copytree(example / 'proxy-rust/src', source_example / 'proxy-rust/src')
    for filename in ('Cargo.toml', 'Cargo.lock', 'LICENSE', 'README.md'):
        shutil.copy2(example / 'proxy-rust' / filename, source_example / 'proxy-rust' / filename)
    sdk = source / 'crates/codey-plugin-sdk'
    shutil.copytree(repo / 'crates/codey-plugin-sdk/src', sdk / 'src')
    for filename in ('Cargo.toml', 'README.md', 'REQUEST_LIFECYCLE.md', 'PROVIDER_TRANSPORT.md'):
        shutil.copy2(repo / 'crates/codey-plugin-sdk' / filename, sdk / filename)
    shutil.copy2(repo / 'LICENSE', sdk / 'LICENSE')
    # Keep SDK unit tests; omit host-only test dependencies whose sources are not bundled.
    sdk_manifest = (sdk / 'Cargo.toml').read_text(encoding='utf-8').split('\n[dev-dependencies]', 1)[0]
    (sdk / 'Cargo.toml').write_text(sdk_manifest + '\n[dev-dependencies]\ntempfile = "3"\n', encoding='utf-8')
    workspace = re.sub(r'members = \[.*?\]', 'members = ["crates/codey-plugin-sdk", "examples/plugins/antigravity-router"]', (repo / 'Cargo.toml').read_text(encoding='utf-8'), count=1, flags=re.S)
    (source / 'Cargo.toml').write_text(workspace, encoding='utf-8')
    shutil.copy2(repo / 'Cargo.lock', source / 'Cargo.lock')
    shutil.copy2(repo / 'LICENSE', source / 'LICENSE')
    for filename in ('README.md', 'UPSTREAM.md'):
        shutil.copy2(repo / filename, source / filename)
    (source / 'docs').mkdir()
    shutil.copy2(repo / 'docs/HOST_COMPATIBILITY.md', source / 'docs/HOST_COMPATIBILITY.md')
    (source / 'scripts').mkdir()
    shutil.copy2(repo / 'scripts/package-plugin.py', source / 'scripts/package-plugin.py')
    subprocess.run([
        args.cargo, 'metadata', '--manifest-path', str(source / 'Cargo.toml'),
        '--offline', '--filter-platform', args.target, '--format-version', '1',
    ], check=True, stdout=subprocess.DEVNULL)
    with zipfile.ZipFile(bundle / 'source.zip', 'x', zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def sums(directory: pathlib.Path, recursive: bool = True) -> str:
    paths = directory.rglob('*') if recursive else directory.iterdir()
    return ''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(directory).as_posix()}\n'
        for path in sorted(paths)
        if path.is_file() and path.name != 'SHA256SUMS'
    )


(bundle / 'SHA256SUMS').write_text(sums(bundle), encoding='utf-8')
with zipfile.ZipFile(args.output / f'{bundle.name}.zip', 'x', zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            archive.write(path, path.relative_to(args.output).as_posix())
(args.output / 'SHA256SUMS').write_text(sums(args.output, recursive=False), encoding='utf-8')
print(f'Portable bundle: {bundle}')
