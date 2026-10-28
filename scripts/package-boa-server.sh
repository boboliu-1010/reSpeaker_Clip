#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
python3 - <<'PY'
from pathlib import Path
import datetime,hashlib,json,subprocess,tarfile,tempfile

root=Path.cwd();dist=root/'dist';dist.mkdir(exist_ok=True)
version='beta.8';name='Boa-Server-Web-'+version
archive=dist/(name+'.tar.gz')
if archive.is_symlink():raise SystemExit('Refusing to replace a symlink')
commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain']))
with tempfile.TemporaryDirectory(prefix='boa-server-package-') as folder:
    stage=Path(folder)/name;stage.mkdir()
    components=('server',
                'tools/upload/__init__.py','tools/upload/tests/test_dtls_receiver.py')
    sources=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard',*components]).split(b'\0')
    for relative_name in sorted(set(sources)):
        if relative_name:
            path=root/relative_name.decode()
            if not path.is_file() or path.is_symlink():continue
            relative=path.relative_to(root)
            if any(p in ('__pycache__','.pytest_cache','.ruff_cache','node_modules','artifacts','data','private','credentials') for p in relative.parts):continue
            if path.suffix in ('.pyc','.pyo'):continue
            # There is one dependency manifest for the unified runtime.
            if relative.name.startswith('requirements') and relative != Path('server/requirements.txt'):continue
            if path.suffix in ('.pem','.key','.token','.sqlite3','.dmg','.wav','.bin'):
                raise SystemExit('Unexpected private/data artifact in package: '+str(relative))
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
    license_file=root/'LICENSE'
    if license_file.is_file():(stage/'LICENSE').write_bytes(license_file.read_bytes())
    (stage/'README.md').write_text('''# Boa Server + Web Beta

One service, one data directory. Frontend HTTPS: 9529. Backend HTTPS/API and Clip DTLS/UDP: 9528.

```sh
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
.venv/bin/python -m server --data-dir /path/to/persistent-data --host 0.0.0.0 --port 9528 --web-port 9529 --tls-root /path/to/tls
```

TLS root contains private/server-chain.pem and private/server.key. Reuse existing credentials and the persistent data directory when upgrading. No user data, certificates or device credentials are included in this archive.

For the requested trusted-development ID-only login, append --allow-id-login (or set BOA_ALLOW_ID_LOGIN=1). IDs select registered accounts and do not prove identity; developer actions still require a Bearer credential.

Open https://YOUR_SERVER:9529/ in Chrome. Web API calls remain same-origin and use the same authenticated backend instance. App and Clip retain port 9528. See server/README.md and server/boa/DEPLOYMENT.md for provisioning, TLS and rollback instructions.

Local HTTP only: use --http-only --host 127.0.0.1 instead of --tls-root; this mode has no Clip DTLS listener.
''')
    (stage/'BUILD.json').write_text(json.dumps({'version':version,'base_commit':commit,
        'working_tree_snapshot':dirty,'built_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'web_port':9529,'api_and_dtls_port':9528,
        'entrypoint':'python -m server','requirements':'server/requirements.txt'},indent=2)+'\n')
    manifest=[]
    for path in sorted(stage.rglob('*')):
        if path.is_file():manifest.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+str(path.relative_to(stage)))
    (stage/'MANIFEST.sha256').write_text('\n'.join(manifest)+'\n')
    temporary=dist/(name+'.tar.gz.tmp')
    with tarfile.open(temporary,'w:gz') as output:output.add(stage,arcname=name)
    temporary.replace(archive)
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix(archive.suffix+'.sha256').write_text(digest+'  '+archive.name+'\n')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':digest}))
PY
