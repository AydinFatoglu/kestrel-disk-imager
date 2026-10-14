# Kestrel Disk Imager

A small Windows tool that writes a compressed disk image (`.img.xz`) to an SD card
or USB drive and then checks every byte. It was built to prepare Raspberry Pi boot
media safely, but it works with any raw disk image packed as `.img.xz`.

The user interface is in Turkish.

## What it does

1. **Checks the image file.** You pick an `.img.xz` file. The tool computes its
   SHA-256 and compares it with the published checksum file, if there is one
   (see [Checksums](#checksums)). Then it decompresses the file once without
   writing anything, to confirm the archive is intact and to measure the real
   image size.
2. **Finds safe targets.** It lists every disk except the Windows boot/system
   disk. Only SD, MMC and USB disks that are online, writable and at least 2 GiB
   can be selected. Each row shows why a disk is or is not allowed. Nothing is
   selected automatically.
3. **Asks for final confirmation.** All data and partitions on the chosen disk
   will be erased.
4. **Rechecks the target.** Just before writing, the disk is scanned again. If it
   was removed, replaced or changed, the write is cancelled.
5. **Writes and verifies.**
   - Volumes on the disk are locked and dismounted.
   - The old partition table is removed (the same as `diskpart clean`).
   - The image body is written in 4 MiB blocks with write-through.
   - The first block (which holds the partition table) is held back.
   - The body is read back and compared byte for byte.
   - Only then is the first block written and read back.
   - Windows is told to reload the disk layout.

   Holding back the partition table until the rest is verified follows the same
   order as the official Raspberry Pi Imager. It stops Windows from mounting a
   half-written card and changing it during verification.

Every step is logged to `writer.log` next to the program (rotated at 5 MB, 3 backups).

## Requirements

- Windows 10 or 11
- Administrator rights (the EXE requests them on start)
- An image packed as `.img.xz`

## Checksums

Any `.img.xz` image can be written. If a file named `<image>.img.xz.sha256`
sits next to the image (as Raspberry Pi OS and many other distributions
publish it), the image's SHA-256 must match it, or the write is blocked. A
checksum file that exists but cannot be read is also treated as a failure.
Both `<hash>  <file name>` and a bare hash are accepted.

To make a checksum file for your own image:

```powershell
(Get-FileHash .\your-image.img.xz -Algorithm SHA256).Hash | Set-Content .\your-image.img.xz.sha256
```

`FSDS_IMAGE_SHA256` in [`kestrel_disk_imager.py`](kestrel_disk_imager.py) holds
the hash of one known image. When it matches, the tool only shows an extra
notice ("FSDS imajı doğrulandı"). It does not restrict which images can be written.

`DEFAULT_IMAGE_DIR` sets the folder that the file dialog opens first. If that
folder does not exist, the dialog opens in your user folder.

## Download

Signed builds are published on the GitHub **Releases** page. You can check the
signature in Explorer under *Properties > Digital Signatures*, or with PowerShell:

```powershell
Get-AuthenticodeSignature .\KestrelDiskImager.exe
```

## Build from source

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm KestrelDiskImager.spec
```

The EXE is written to `dist\KestrelDiskImager.exe`. Run from source with
`.\.venv\Scripts\python.exe kestrel_disk_imager.py` in an elevated terminal.

## Tests

The tests use only the Python standard library (`unittest`). They never open a
real disk: device detection is fed with sample data, and write ordering is tested
against an in-memory disk.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
.\.venv\Scripts\python.exe tools\test_release.py
```

## Privacy

This program does not send any information to other computers. It makes no
network connections. It only reads the image file you select, reads disk
information from Windows, writes to the disk you confirm, and writes its own log
file.

## Code signing

See [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md).

## More documentation

- [docs/rpi-imager-windows.md](docs/rpi-imager-windows.md): how write ordering and
  partition-table handling compare with the official Raspberry Pi Imager
- [docs/usb-readers.md](docs/usb-readers.md): how USB card readers and drives are
  detected
- [docs/startup-threading.md](docs/startup-threading.md): background scanning and
  UI threading
- [docs/signing.md](docs/signing.md): local build and signing helpers

The `docs/` notes are written in Turkish.

## License

[MIT](LICENSE). The application icon is from Open Iconic (MIT); see
[assets/ICON-LICENSE.txt](assets/ICON-LICENSE.txt).
