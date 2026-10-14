"""Local build and Authenticode signing helpers. No account secrets are stored."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / '.venv' / 'Scripts' / 'python.exe'
UNSIGNED = ROOT / 'dist' / 'KestrelDiskImager.exe'
SIGNED = ROOT / 'dist' / 'signed' / 'KestrelDiskImager.exe'


def signtool():
    matches = sorted((ROOT / 'tools' / 'vendor' / 'windows-sdk').rglob('signtool.exe'))
    if not matches:
        raise RuntimeError('Microsoft SignTool is missing under tools/vendor/windows-sdk.')
    return matches[-1]


def run(arguments, **options):
    subprocess.run([str(a) for a in arguments], cwd=ROOT, check=True, **options)


def signature(path):
    if not path.is_file():
        raise RuntimeError(f'EXE not found: {path}')
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:KESTREL_SIGNING_TARGET; "
        "[pscustomobject]@{Status=[string]$s.Status;"
        "Signer=$s.SignerCertificate.Subject;"
        "TimestampSigner=$s.TimeStamperCertificate.Subject}|ConvertTo-Json -Compress"
    )
    env = dict(os.environ, KESTREL_SIGNING_TARGET=str(path.resolve()))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             command], env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def verify(path):
    run([signtool(), 'verify', '/pa', '/all', '/v', '/tw', path])
    details = signature(path)
    if details['Status'] != 'Valid' or not details['TimestampSigner']:
        raise RuntimeError('A valid Authenticode signature AND a trusted timestamp are required.')
    print(json.dumps(details, ensure_ascii=True, indent=2))


def doctor():
    if not PYTHON.is_file():
        raise RuntimeError('Workspace Python environment is missing: .venv/Scripts/python.exe')
    run([PYTHON, '-c', "import wx,win32file,PyInstaller; print('Python build dependencies: OK')"])
    print('SignTool:', signtool())
    clients = list((ROOT / 'tools' / 'vendor' / 'codesigntool').rglob('CodeSignTool.bat'))
    print('SSL.com CLI:', clients[0] if clients else 'NOT FOUND')
    if not clients:
        raise RuntimeError('SSL.com CodeSignTool is missing.')
    print('eSigner CKA installer:', ROOT / 'tools' / 'vendor' / 'esigner-cka')
    command = (
        "@(Get-ChildItem Cert:\\CurrentUser\\My,Cert:\\LocalMachine\\My -CodeSigningCert | "
        "Where-Object {$_.HasPrivateKey -and $_.NotBefore -le (Get-Date) -and "
        "$_.NotAfter -gt (Get-Date)} | Select-Object Subject,Thumbprint,HasPrivateKey)|"
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             command], capture_output=True, text=True, check=True)
    print('Available signing certificates:', result.stdout.strip() or 'NONE (account/certificate required)')
    if UNSIGNED.is_file():
        print('Current EXE:', json.dumps(signature(UNSIGNED), ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Check tools and certificate availability; no signing/network call.')
    commands.add_parser('esigner-help', help='Run the downloaded SSL.com CLI help locally.')
    commands.add_parser('build', help='Build the unsigned EXE with the existing PyInstaller spec.')
    sign = commands.add_parser('sign', help='Sign a COPY using a Windows-store certificate or eSigner CKA.')
    sign.add_argument('--thumbprint', required=True)
    sign.add_argument('--machine-store', action='store_true')
    sign.add_argument('--timestamp-url', default='http://ts.ssl.com')
    check = commands.add_parser('verify', help='Verify signature, trust and timestamp.')
    check.add_argument('file', nargs='?', type=Path, default=SIGNED)
    args = parser.parse_args()
    if args.command == 'doctor':
        doctor()
    elif args.command == 'esigner-help':
        client = ROOT / 'tools' / 'vendor' / 'codesigntool'
        run([client / 'jdk-11.0.2' / 'bin' / 'java.exe', '-jar',
             client / 'jar' / 'code_sign_tool-1.3.3.jar', '-h'])
    elif args.command == 'build':
        if UNSIGNED.exists() and signature(UNSIGNED)['Signer']:
            raise RuntimeError('Existing EXE is signed; build refused to preserve it.')
        run([PYTHON, '-m', 'PyInstaller', '--noconfirm', ROOT / 'KestrelDiskImager.spec'])
        shutil.copy2(ROOT / 'assets' / 'ICON-LICENSE.txt', ROOT / 'dist' / 'ICON-LICENSE.txt')
    elif args.command == 'sign':
        thumbprint = re.sub(r'\s', '', args.thumbprint)
        if not re.fullmatch(r'[0-9a-fA-F]{40}', thumbprint):
            raise RuntimeError('Expected a 40-hex-digit certificate thumbprint.')
        timestamp = urlparse(args.timestamp_url)
        if timestamp.scheme not in ('http', 'https') or not timestamp.netloc:
            raise RuntimeError('Timestamp URL must be an HTTP(S) endpoint.')
        if not UNSIGNED.is_file():
            raise RuntimeError('Build the unsigned EXE first.')
        if SIGNED.exists():
            raise RuntimeError(f'Output already exists; refusing to overwrite: {SIGNED}')
        tool = signtool()
        # Exclusive creation prevents overwriting a previous signed release.
        SIGNED.parent.mkdir(parents=True, exist_ok=True)
        with UNSIGNED.open('rb') as src, SIGNED.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        try:
            arguments = [tool, 'sign', '/fd', 'SHA256', '/td', 'SHA256', '/tr',
                         args.timestamp_url, '/s', 'My', '/sha1', thumbprint]
            if args.machine_store:
                arguments.append('/sm')
            run(arguments + ['/d', 'Kestrel Disk Imager', SIGNED])
            verify(SIGNED)
        except Exception:
            # Remove only this newly created, unsuccessful signing candidate.
            SIGNED.unlink(missing_ok=True)
            raise
        print('Signed release ready:', SIGNED)
    else:
        verify(args.file.resolve())


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
