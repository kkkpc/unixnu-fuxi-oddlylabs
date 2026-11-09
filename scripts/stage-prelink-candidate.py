#!/usr/bin/env python3
"""Materialize the prelink candidate before archive-time ABI audits.

The normal UniXNU pipeline emits the candidate after the archive chain.  A
board archive that audits an original kext before compiling against it needs
the same operation earlier, using the bootstrap native kernel and the exact
profile-pinned original kernelcache.  This script deliberately delegates the
Mach-O work to the pinned XnuPrelink emitter; it never fabricates a report.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_KERNELCACHE = "f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7"
OUTPUT = ROOT / "build/xnu-prelink/native-owner-mobile-graphics-candidate.macho"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def prelink_spec():
    # In CI, ROOT is the assembled out/.../tree.  profiles/ belongs to the
    # UniXNU source checkout above it and is intentionally not copied into
    # the assembled tree.
    profile_roots = [ROOT / "profiles/os"]
    profile_roots.extend(parent / "profiles/os" for parent in ROOT.parents)
    seen = set()
    profiles = []
    for profile_root in profile_roots:
        if profile_root in seen or not profile_root.is_dir():
            continue
        seen.add(profile_root)
        for profile in sorted(profile_root.glob("*/profile.toml")):
            with profile.open("rb") as stream:
                data = tomllib.load(stream)
            spec = data.get("kernel", {}).get("prelink")
            # The profile is read from the UniXNU checkout, but build outputs
            # and component kits are rooted in the assembled device tree.
            if spec:
                profiles.append((profile, data, spec))
    wanted_build = os.environ.get("UNIXNU_IPSW_BUILD")
    for _, data, spec in profiles:
        if wanted_build and data.get("ipsw", {}).get("build") == wanted_build:
            return ROOT, spec
    for profile, _, spec in profiles:
        if profile.parent.name.startswith("ipados-17."):
            return ROOT, spec
    raise SystemExit("no profile-pinned kernel.prelink spec matches the bootstrap kernel")


def original_kernelcache():
    override = os.environ.get("UNIXNU_KERNELCACHE")
    candidates = [Path(override)] if override else []
    candidates += [
        ROOT / ".cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed",
        ROOT / ".cache/firmware/kernelcache.decompressed",
    ]
    build = os.environ.get("UNIXNU_IPSW_BUILD")
    if build:
        for parent in ROOT.parents:
            candidates.append(parent / "ipsw" / build / "kernelcache.decompressed")
    for path in candidates:
        if path and path.is_file() and sha256(path) == EXPECTED_KERNELCACHE:
            return path

    # This is the same framework-owned fetch used by the final prelink step.
    # It downloads only the KernelCache member, not the full IPSW.
    framework = next((parent for parent in ROOT.parents if (parent / "unixnu").is_file()), None)
    require(framework is not None, "framework CLI not found while locating the original kernelcache")
    command = [str(framework / "unixnu"), "ipsw", "fetch", "KernelCache"]
    states = [parent / "state.json" for parent in ROOT.parents]
    for state in states:
        if state.is_file():
            device = json.loads(state.read_text()).get("device")
            if device:
                command += ["--device", device]
            break
    result = subprocess.run(command, cwd=framework, text=True, capture_output=True, timeout=900)
    require(result.returncode == 0,
            "framework KernelCache fetch failed: " + (result.stderr.strip() or result.stdout.strip()))
    for path in candidates:
        if path and path.is_file() and sha256(path) == EXPECTED_KERNELCACHE:
            return path
    raise SystemExit("fetched KernelCache does not match the pinned 21H461 sha256")


def ensure_native_kernel(kernel):
    if kernel.is_file():
        return
    # The first XNU pass is intentionally allowed to fail after leaving
    # compile records.  At archive-19 the storage, PMGR and USB archives are
    # now available, so make the native kernel once with those real inputs.
    # Display and Adreno archives are later in board.toml and are explicitly
    # disabled for this prelink carrier; the final build relinks with them.
    script = ROOT / "scripts/build-xnu-4k-baseline.sh"
    require(script.is_file(), f"XNU build script missing: {script}")
    environment = dict(os.environ)
    environment.update({
        "XNU_BOOTSTRAP": "0",
        "XNU_BOOT_PROGRESS": "0",
        "XNU_NATIVE_ADRENO": "0",
        "XNU_NATIVE_MOBILE_DISPLAY": "0",
        "XNU_NATIVE_LEGACY_DISPLAY": "0",
    })
    result = subprocess.run(["bash", str(script)], cwd=ROOT, env=environment,
                            text=True, capture_output=True, timeout=900)
    if result.returncode:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("prelink carrier native relink failed")
    require(kernel.is_file(), f"native relink emitted no kernel: {kernel}")


def main():
    tree_root, spec = prelink_spec()
    kernel = tree_root / spec["kernel"]
    ensure_native_kernel(kernel)
    cache = original_kernelcache()
    require(sha256(cache) == EXPECTED_KERNELCACHE, "wrong original kernelcache for the ABI audit")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tool = tree_root / spec["tool"]
    command = [sys.executable, str(tool), "--kernel", str(kernel), "--prelinked", str(cache),
               f"--slide={spec['slide']}"]
    for root in spec.get("roots", []):
        command += ["--root", root]
    if spec.get("early_security_init"):
        command += ["--early-security-init", spec["early_security_init"]]

    with tempfile.TemporaryDirectory(dir=OUTPUT.parent, prefix=".stage-prelink-") as directory:
        candidate = Path(directory) / OUTPUT.name
        result = subprocess.run(command + ["--output", str(candidate)], cwd=ROOT,
                                text=True, capture_output=True, timeout=900)
        if result.returncode:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(result.returncode)
        report = candidate.with_suffix(".json")
        require(candidate.is_file() and report.is_file(),
                "XnuPrelink emitted no candidate/report")
        OUTPUT.write_bytes(candidate.read_bytes())
        OUTPUT.with_suffix(".json").write_bytes(report.read_bytes())
    require(sha256(OUTPUT) == json.loads(OUTPUT.with_suffix(".json").read_text())["candidate_sha256"],
            "staged candidate does not match its XnuPrelink report")
    print(f"staged {OUTPUT.relative_to(ROOT)} from bootstrap kernel and pinned KernelCache")


if __name__ == "__main__":
    main()
