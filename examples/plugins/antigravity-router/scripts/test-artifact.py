"""Test a CI portable release directly. Never runs Cargo or any compiler."""
import argparse
import os
import pathlib
import platform
import stat
import subprocess
import sys
import tempfile
import zipfile


def run(*args, env=None):
    subprocess.run([str(a) for a in args], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=pathlib.Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    example = pathlib.Path(__file__).resolve().parents[1]
    windows = sys.platform == 'win32'
    target_platform = 'windows' if windows else ('macos' if sys.platform == 'darwin' else 'linux')
    arch = 'aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64'
    native_packages = list(bundle.glob('*.codey-plugin'))
    if len(native_packages) != 1:
        raise SystemExit('Expected exactly one native package in the bundle')
    source = bundle / 'source.zip'
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise SystemExit('Duplicate source archive entry')
        forbidden = {'auth.json', 'antigravity-accounts.json', 'antigravity-catalog-cache.json', '.env'}
        for item in archive.infolist():
            path = pathlib.PurePosixPath(item.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename
                    or any(part in forbidden or part in ('.git', '.runtime', '__pycache__') for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise SystemExit(f'Unsafe source archive entry: {item.filename}')
    print('PASS source archive: no traversal, duplicate entries, links or credential files', flush=True)
    if not (bundle / 'proxy_manager.py').is_file():
        raise SystemExit('Missing unified cross-platform proxy_manager.py')
    if windows:
        run('powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            bundle / 'scripts/verify-bundle.ps1', '-Bundle', bundle)
    else:
        run('bash', bundle / 'scripts/verify-bundle.sh', bundle)
    with tempfile.TemporaryDirectory(prefix='codey-release-中文 space-') as temp:
        extension = '.dll' if windows else ('.dylib' if sys.platform == 'darwin' else '.so')
        library = pathlib.Path(temp) / ('release' + extension)
        run(sys.executable, example / 'scripts/verify-native.py', native_packages[0],
            '--platform', target_platform, '--arch', arch, '--extract-library', library)
        run(sys.executable, example / 'tests/prebuilt-native-abi.py', '--library', library)
    env = os.environ.copy()
    env['RUST_PROXY_EXE'] = str(bundle / 'bin' / ('antigravity-proxy.exe' if windows else 'antigravity-proxy'))
    run('node', example / 'tests/e2e-rust-proxy.test.mjs', env=env)
    if windows:
        run('powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            example / 'scripts/test-portable.ps1', '-Bundle', bundle)
    else:
        run('bash', example / 'scripts/test-portable.sh', bundle)
    print('PASS CI release: source safety / exact bundle / native package / C ABI / full mock E2E / portable install', flush=True)


if __name__ == '__main__':
    main()
