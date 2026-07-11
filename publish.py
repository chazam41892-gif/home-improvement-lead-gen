#!/usr/bin/env python3
"""Universal Updater — publish to PyPI + npm in one command.

Usage:
    python publish.py                    # publish current version
    python publish.py --bump patch       # bump version, then publish
    python publish.py --bump minor
    python publish.py --bump major
    python publish.py --dry-run          # show what would happen

Reads version from pyproject.toml, syncs to package.json, builds both,
and publishes to both registries. Works for any project with both configs.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_JSON = ROOT / "package.json"


def load_version() -> str:
    """Read version from pyproject.toml (canonical source)."""
    import tomllib
    data = tomllib.loads(PYPROJECT.read_text())
    return data["project"]["version"]


def save_version(version: str):
    """Write version to both pyproject.toml and package.json."""
    # pyproject.toml
    content = PYPROJECT.read_text()
    import re
    content = re.sub(
        r'^version\s*=\s*"[^"]*"',
        f'version = "{version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    PYPROJECT.write_text(content)

    # package.json
    pkg = json.loads(PACKAGE_JSON.read_text())
    pkg["version"] = version
    PACKAGE_JSON.write_text(json.dumps(pkg, indent=2) + "\n")

    print(f"  version -> {version} (pyproject.toml + package.json)")


def bump_version(current: str, level: str) -> str:
    """Bump semver: major.minor.patch."""
    parts = [int(x) for x in current.split(".")]
    if level == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif level == "minor":
        parts[1] += 1
        parts[2] = 0
    elif level == "patch":
        parts[2] += 1
    return ".".join(str(p) for p in parts)


def run(cmd: list[str], label: str) -> bool:
    """Run a command, print output, return success."""
    print(f"\n  [{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    if result.returncode != 0:
        print(f"  FAILED: {label}")
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                print(f"    {line}")
        return False
    return True


def publish_pypi() -> bool:
    """Build wheel and upload to PyPI."""
    if not run(["python", "-m", "build"], "build wheel"):
        return False
    wheels = list(ROOT.glob("dist/*.whl"))
    tars = list(ROOT.glob("dist/*.tar.gz"))
    if not wheels and not tars:
        print("  No dist files found — build may have failed silently")
        return False
    return run(["twine", "upload", "dist/*"], "upload PyPI")


def publish_npm() -> bool:
    """Publish to npm registry."""
    return run(["npm", "publish"], "publish npm")


def git_tag(version: str) -> bool:
    """Create and push a git tag."""
    tag = f"v{version}"
    if not run(["git", "add", "pyproject.toml", "package.json"], "git add"):
        return False
    if not run(["git", "commit", "-m", f"release: v{version}"], "git commit"):
        print("  (commit may have been empty — continuing)")
    if not run(["git", "tag", tag], f"git tag {tag}"):
        return False
    return run(["git", "push", "origin", tag], "git push tag")


def main():
    parser = argparse.ArgumentParser(description="Publish to PyPI + npm")
    parser.add_argument("--bump", choices=["patch", "minor", "major"],
                        help="Bump version before publishing")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without publishing")
    parser.add_argument("--skip-pypi", action="store_true",
                        help="Skip PyPI publish")
    parser.add_argument("--skip-npm", action="store_true",
                        help="Skip npm publish")
    parser.add_argument("--skip-git", action="store_true",
                        help="Skip git tag")
    args = parser.parse_args()

    current = load_version()
    version = bump_version(current, args.bump) if args.bump else current

    print(f"\n  Lead Gen Pro — Universal Publisher")
    print(f"  {'=' * 40}")
    print(f"  Current:  {current}")
    if args.bump:
        print(f"  Bump:     {args.bump} -> {version}")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would publish v{version} to:")
        if not args.skip_pypi:
            print(f"    PyPI:  pip install leadgen-pro=={version}")
        if not args.skip_npm:
            print(f"    npm:   npm install -g leadgen-pro@{version}")
        if not args.skip_git:
            print(f"    Git:   tag v{version}")
        return

    if args.bump:
        save_version(version)

    ok = True
    if not args.skip_pypi:
        ok &= publish_pypi()
    if not args.skip_npm:
        ok &= publish_npm()
    if not args.skip_git:
        ok &= git_tag(version)

    print(f"\n  {'=' * 40}")
    if ok:
        print(f"  PUBLISHED v{version} to PyPI + npm")
        print(f"  pip install leadgen-pro=={version}")
        print(f"  npm install -g leadgen-pro@{version}")
    else:
        print(f"  FAILED — check errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
