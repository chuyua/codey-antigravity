"""Validate one .codey-plugin archive against the expected platform contract."""
import argparse
import hashlib
import json
import pathlib
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("package", type=pathlib.Path)
parser.add_argument("--platform", choices=["macos", "windows", "linux"])
parser.add_argument("--arch")
parser.add_argument("--entry")
parser.add_argument("--extract-library", type=pathlib.Path)
args = parser.parse_args()

with zipfile.ZipFile(args.package) as archive:
    names = archive.namelist()
    assert len(names) == 3 and len(set(names)) == 3, names
    manifest = json.loads(archive.read("manifest.json"))
    config = archive.read("config.json")
    assert len(config) <= 1048576 and isinstance(json.loads(config), dict)
    assert manifest["id"] == "dev.codey.antigravity-router" and manifest["version"] == "0.10.0"
    assert manifest["abiVersion"] == 1
    if args.platform:
        assert manifest["platform"] == args.platform, manifest["platform"]
    if args.arch:
        assert manifest["arch"] == args.arch, manifest["arch"]
    assert set(manifest["capabilities"]) == {"provider.route.v1", "request.lifecycle.v1"}
    if args.entry:
        assert manifest["entry"] == args.entry, manifest["entry"]
    assert set(names) == {"manifest.json", "config.json", manifest["entry"]}, names
    assert hashlib.sha256(archive.read(manifest["entry"])).hexdigest() == manifest["librarySha256"]
    if args.extract_library:
        args.extract_library.write_bytes(archive.read(manifest["entry"]))
print(
    "PASS native package: exact three files / ABI / platform / capabilities / config / library SHA256"
)
