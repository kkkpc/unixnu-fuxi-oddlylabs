#!/usr/bin/env python3
"""Fetch the exact Adreno inputs without depending on GitHub's anonymous API quota."""
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'scripts/data/adreno-inputs.json').read_text())
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')


def request_bytes(url):
    headers = {'User-Agent': 'sheng-offline-adreno-audit'}
    if TOKEN and 'api.github.com' in url:
        headers['Authorization'] = 'Bearer ' + TOKEN
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            retryable = error.code == 403 and 'api.github.com' in url or error.code == 429 or error.code >= 500
            if not retryable or attempt == 4:
                if error.code == 403 and 'api.github.com' in url and not TOKEN:
                    raise RuntimeError('GitHub API denied the firmware request; GITHUB_TOKEN is required') from error
                raise
            retry_after = error.headers.get('Retry-After')
            delay = min(30, int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)
            time.sleep(delay)


def fetch(item):
    path, url, expected, blob, encoding = item
    if path.exists():
        data = path.read_bytes()
    else:
        data = request_bytes(url)
        if blob:
            data = base64.b64decode(json.loads(data)['content'])
        elif encoding == 'gitiles-base64':
            data = base64.b64decode(data, validate=False)
    if hashlib.sha256(data).hexdigest() != expected['sha256'] or (expected.get('bytes') and len(data) != expected['bytes']):
        raise ValueError('Pinned input hash/size differs: ' + path.name)
    if blob and hashlib.sha1(('blob ' + str(len(data)) + '\0').encode() + data).hexdigest() != blob:
        raise ValueError('Pinned Git blob identity differs: ' + path.name)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return len(data)


if __name__ == '__main__':
    jobs = []
    linux = PINS['linux']
    for name, expected in linux['files'].items():
        url = linux['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') + '/' + linux['commit'] + '/' + name
        jobs.append((ROOT / '.cache/adreno-source' / name, url, expected, None, None))
    mesa = PINS['mesa']
    for name, expected in mesa['files'].items():
        url = mesa['mirror'] + '/+/' + mesa['commit'] + '/' + name + '?format=TEXT'
        jobs.append((ROOT / '.cache/adreno-source/mesa' / name, url, expected, None, 'gitiles-base64'))
    firmware = PINS['firmware']
    for name, expected in firmware['files'].items():
        blob = expected['git_blob_sha1']
        url = firmware['repository'].replace('https://github.com/', 'https://api.github.com/repos/') + '/git/blobs/' + blob
        jobs.append((ROOT / '.cache/firmware/sheng-gpu' / name, url, expected, blob, None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        sizes = list(executor.map(fetch, jobs))
    print(f'PASS: {len(sizes)} exact source/firmware inputs, {sum(sizes)} bytes; no GPU execution/authenticity claim')
