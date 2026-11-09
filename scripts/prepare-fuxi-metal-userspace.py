#!/usr/bin/env python3
"""Prepare pinned external source trees for the fuxi Adreno Metal payload build."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

def run(command):
    print("+", " ".join(str(x) for x in command), flush=True)
    subprocess.run([str(x) for x in command], check=True)

def out(command):
    return subprocess.check_output([str(x) for x in command], text=True).strip()

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fresh_checkout(urls, commit, destination, sparse=()):
    destination = destination.resolve()
    if destination.exists() and not (destination / ".git").is_dir():
        shutil.rmtree(destination)
    if not (destination / ".git").is_dir():
        last = ""
        for url in urls:
            result = subprocess.run(
                ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(destination)],
                text=True, capture_output=True)
            if result.returncode == 0:
                break
            last = result.stderr
            shutil.rmtree(destination, ignore_errors=True)
        else:
            raise SystemExit("Unable to clone pinned source: " + last)
    if sparse:
        run(["git", "-C", destination, "sparse-checkout", "init", "--cone"])
        run(["git", "-C", destination, "sparse-checkout", "set", "--skip-checks", *sparse])
    run(["git", "-C", destination, "fetch", "--depth=1", "origin", commit])
    run(["git", "-C", destination, "checkout", "--detach", "FETCH_HEAD"])
    run(["git", "-C", destination, "reset", "--hard", commit])
    run(["git", "-C", destination, "clean", "-fd"])
    actual = out(["git", "-C", destination, "rev-parse", "HEAD"])
    if actual != commit:
        raise SystemExit(f"Pinned checkout mismatch: expected {commit}, got {actual}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True, help="resolved UniXNU target tree")
    args = parser.parse_args()
    root = args.tree.resolve()
    compiler_path = root / "scripts/data/adreno-compiler-inputs.json"
    metal_path = root / "scripts/data/gpu-metal-vulkan-inputs.json"
    if not compiler_path.is_file() or not metal_path.is_file():
        raise SystemExit(f"not a resolved UniXNU tree: {root}")
    cache = root / ".cache"
    cache.mkdir(parents=True, exist_ok=True)

    compiler = json.loads(compiler_path.read_text())
    mesa_pin = compiler["mesa"]
    mesa_urls = [value for value in (mesa_pin.get("mirror"), mesa_pin.get("repository")) if value]
    mesa = cache / "mesa-work"
    fresh_checkout(mesa_urls, mesa_pin["commit"], mesa, mesa_pin.get("sparse_directories", []))
    tree = out(["git", "-C", mesa, "rev-parse", "HEAD^{tree}"])
    if tree != mesa_pin["tree"]:
        raise SystemExit(f"Mesa tree mismatch: expected {mesa_pin['tree']}, got {tree}")
    for relative in compiler["patches"]:
        patch = root / relative
        if not patch.is_file():
            raise SystemExit(f"Missing recorded Mesa patch: {relative}")
        run(["git", "-C", mesa, "apply", "--check", patch])
        run(["git", "-C", mesa, "apply", patch])

    metal = json.loads(metal_path.read_text())
    translator = metal["translator"]
    source = cache / "gpu-reference/metal2vulkan"
    source.parent.mkdir(parents=True, exist_ok=True)
    fresh_checkout([translator["repository"]], translator["commit"], source)
    for relative, digest in translator.get("files", {}).items():
        path = source / relative
        if not path.is_file() or sha256(path) != digest:
            raise SystemExit(f"Translator pin mismatch: {relative}")

    venv = cache / "mesa-venv"
    if not (venv / "bin/python").is_file():
        run([sys.executable, "-m", "venv", venv])
    run([venv / "bin/python", "-m", "pip", "install", "--disable-pip-version-check",
         "-r", root / "scripts/requirements-adreno-compiler.txt"])
    print("PASS: pinned Mesa + recorded patches, pinned metal2vulkan, and Mesa Python environment prepared")
    print("Mesa:", mesa_pin["commit"])
    print("Translator:", translator["commit"])

if __name__ == "__main__":
    main()
