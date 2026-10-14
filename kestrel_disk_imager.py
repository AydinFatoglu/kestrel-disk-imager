"""Kestrel Disk Imager — Windows only. pip install wxPython pywin32"""
import ctypes
from contextlib import contextmanager
import hashlib
import json
import lzma
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import wx
import win32con
import win32file
import pywintypes

from about_dialog import REPO_URL, AboutDialog, github_link

APP = 'Kestrel Disk Imager'
APP_VERSION = '1.0.0'  # keep in sync with version_info.txt
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
ICON_PATH = Path(__file__).resolve().parent / 'assets' / 'kestrel.ico'
LOG_PATH = APP_DIR / 'writer.log'
logger = logging.getLogger('kestrel.writer')


def configure_logging():
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024,
                                 backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | pid=%(process)d | %(threadName)s | %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info('Program started; log=%s', LOG_PATH)
    logger.info('I/O profile: fixed 4 MiB blocks, two-block prefetch, sequential write-through, direct verification with compatibility fallback; partition table committed AFTER body verification')
    def unhandled(exc_type, exc, traceback):
        logger.critical('Unhandled exception', exc_info=(exc_type, exc, traceback))
        sys.__excepthook__(exc_type, exc, traceback)
    sys.excepthook = unhandled
    def thread_error(args):
        logger.critical('Unhandled thread exception: %s', args.thread.name,
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_error


DEFAULT_IMAGE_DIR = Path(r'C:\FS_Digital_Signage')
# Known compressed image; a match only adds a notice, other images stay writable.
FSDS_IMAGE_SHA256 = 'CFD285AEDE1CA6572D818CD7F348A325E8E0CBDA072BE6B8BF2B0A934E240C92'
SIDECAR_MAX_BYTES = 4096
SHA256_TOKEN = re.compile(r'^\s*([0-9a-fA-F]{64})(?:\s|$)')
CHUNK = 4 * 1024 * 1024
PREFETCH_BLOCKS = 2
DIRECT_IO_UNSUPPORTED = (1, 50, 87)  # invalid function / not supported / invalid parameter
# winioctl.h: CTL_CODE(IOCTL_DISK_BASE, function, METHOD_BUFFERED, access).
IOCTL_DISK_DELETE_DRIVE_LAYOUT = 0x0007C100
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020

# Only explicitly identified card readers; brand/removable status alone is unsafe.
READER_DESCRIPTION = re.compile(
    r'\b(?:card\s*reader|(?:sd|mmc|sdhc|sdxc|micro\s*sd)\s*(?:/\s*mmc\s*)?reader|'
    r'sd\s*/\s*mmc)\b', re.IGNORECASE)

DEVICE_SCAN_SCRIPT = r'''
function Device-Info($device) {
    $properties = @{}
    Get-PnpDeviceProperty -InstanceId $device.InstanceId -KeyName `
        'DEVPKEY_Device_BusReportedDeviceDesc','DEVPKEY_Device_Parent' `
        -ErrorAction SilentlyContinue | ForEach-Object { $properties[$_.KeyName] = $_.Data }
    [pscustomobject]@{
        InstanceId = $device.InstanceId
        FriendlyName = $device.FriendlyName
        Description = $properties['DEVPKEY_Device_BusReportedDeviceDesc']
        Parent = $properties['DEVPKEY_Device_Parent']
    }
}
$present = @{}
Get-PnpDevice -PresentOnly | ForEach-Object { $present[$_.InstanceId] = $_ }
$usb = @{}
foreach ($device in $present.Values) {
    if ($device.InstanceId -match '^USB\\VID_' -and $device.Class -in @('USB','USBDevice','DiskDrive')) {
        $usb[$device.InstanceId] = Device-Info $device
    }
}
$drives = @{}
Get-CimInstance Win32_DiskDrive | ForEach-Object { $drives[[int]$_.Index] = $_ }
$disks = @(foreach ($disk in Get-Disk) {
    $drive = $drives[[int]$disk.Number]
    $chain = @()
    if ([string]$disk.BusType -eq 'USB' -and $drive) {
        $instance = $drive.PNPDeviceID
        for ($depth = 0; $depth -lt 8 -and $instance -and $present.ContainsKey($instance); $depth++) {
            $info = if ($usb.ContainsKey($instance)) { $usb[$instance] } else { Device-Info $present[$instance] }
            $chain += $info
            # Stop at this physical USB device: a hub's other slots are not this disk.
            if ($instance -match '^USB\\VID_' -and $instance -notmatch '&MI_') { break }
            $instance = $info.Parent
        }
    }
    [pscustomobject]@{
        Number = $disk.Number; FriendlyName = $disk.FriendlyName; BusType = [string]$disk.BusType
        Size = $disk.Size; IsBoot = $disk.IsBoot; IsSystem = $disk.IsSystem
        IsReadOnly = $disk.IsReadOnly; IsOffline = $disk.IsOffline
        PartitionStyle = [string]$disk.PartitionStyle; UniqueId = $disk.UniqueId
        LogicalSectorSize = $disk.LogicalSectorSize; PhysicalSectorSize = $disk.PhysicalSectorSize
        PNPDeviceID = $drive.PNPDeviceID; DeviceChain = @($chain)
    }
})
[pscustomobject]@{ Disks = @($disks); UsbDevices = @($usb.Values) } | ConvertTo-Json -Depth 6 -Compress
'''


def powershell(script):
    p = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        '$ErrorActionPreference="Stop"; ' + script],
                       capture_output=True, text=True, encoding='utf-8-sig', errors='replace',
                       timeout=35, creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:
        logger.error('PowerShell failed: returncode=%s stderr=%s stdout=%s',
                     p.returncode, p.stderr.strip(), p.stdout.strip())
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()


def is_card_reader(device):
    # Classify the reported device description without vendor/model/ID allowlists.
    description = ' '.join(str(device.get(key) or '') for key in ('FriendlyName', 'Description'))
    return bool(READER_DESCRIPTION.search(description.replace('_', ' ')))


def disk_rejection_reasons(device):
    reasons = []
    bus = str(device.get('BusType', '')).upper()
    supported = bus in ('SD', 'MMC', 'USB')
    if not supported:
        reasons.append('SD/MMC veya USB depolama aygıtı değil')
    if device.get('IsBoot') or device.get('IsSystem'):
        reasons.append('Windows boot/sistem diski')
    if device.get('IsReadOnly'):
        reasons.append('Salt okunur')
    if device.get('IsOffline'):
        reasons.append('Çevrimdışı')
    size = int(device.get('Size') or 0)
    if not size:
        reasons.append('Kart yok veya kapasite okunamadı')
    elif size < 2 * 1024**3:
        reasons.append('Kapasite 2 GiB altında')
    return reasons


def scan_devices(include_diagnostics=False):
    inventory = json.loads(powershell(DEVICE_SCAN_SCRIPT))
    readers = [d for d in inventory.get('UsbDevices', []) if is_card_reader(d)]
    disks = inventory.get('Disks', [])
    candidates = [d for d in disks if not disk_rejection_reasons(d)]
    logger.info('Device scan: total=%s eligible=%s', len(disks), len(candidates))
    if include_diagnostics:
        visible = [d for d in disks if not d.get('IsBoot') and not d.get('IsSystem')]
        return candidates, readers, visible
    return candidates, readers


def scan_disks():
    return scan_devices()[0]


def disk_identity(device):
    return tuple(str(device.get(key) or '') for key in
                 ('Number', 'UniqueId', 'PNPDeviceID', 'Size', 'BusType'))


def volumes_on_disk(number):
    script = (f'Get-Partition -DiskNumber {int(number)} -ErrorAction SilentlyContinue | '
              'Where-Object { $_.DriveLetter } | Select-Object -ExpandProperty DriveLetter | ConvertTo-Json -Compress')
    raw = powershell(script)
    if not raw:
        return []
    obj = json.loads(raw)
    return [obj] if isinstance(obj, str) else obj


def digest_file(path, callback=None):
    h = hashlib.sha256()
    total = path.stat().st_size
    count = 0
    with path.open('rb') as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            count += len(chunk)
            if callback:
                callback(count, total)
    return h.hexdigest().lower()


def sidecar_sha256(image_path):
    """Expected hash from '<image>.sha256' ('<hash>  <name>' or bare hash); None if absent."""
    sidecar = image_path.with_name(image_path.name + '.sha256')
    if not sidecar.is_file():
        return None
    with sidecar.open('rb') as f:
        text = f.read(SIDECAR_MAX_BYTES).decode('utf-8-sig', errors='replace')
    match = SHA256_TOKEN.match(text)
    if not match:
        # Fail closed: a present but unreadable checksum must not be ignored.
        raise RuntimeError(f'{sidecar.name} geçerli bir SHA-256 değeri içermiyor. Yazma engellendi.')
    return match.group(1).lower()


def image_check_note(digest, expected):
    if digest == FSDS_IMAGE_SHA256.lower():
        return 'FSDS imajı doğrulandı.'
    if expected:
        return 'İmaj .sha256 dosyasıyla doğrulandı.'
    return '.sha256 dosyası yok; imaj yalnız xz bütünlük denetiminden geçti.'


def compressed_size(path):
    total = 0
    last_log = time.monotonic()
    with lzma.open(path, 'rb') as f:
        while block := f.read(CHUNK):
            total += len(block)
            if time.monotonic() - last_log >= 10:
                logger.info('Image decompression check: expanded_bytes=%s', total)
                last_log = time.monotonic()
    logger.info('Image decompression check passed: expanded_bytes=%s', total)
    return total


@contextmanager
def image_blocks(path):
    """One decoder owns the source; at most two decoded blocks wait in RAM."""
    pending = queue.Queue(maxsize=PREFETCH_BLOCKS)
    stop = threading.Event()

    def send(item):
        while not stop.is_set():
            try:
                pending.put(item, timeout=0.1)
                return
            except queue.Full:
                pass

    def decode():
        try:
            with lzma.open(path, 'rb') as src:
                while not stop.is_set():
                    block = src.read(CHUNK)
                    if not block:
                        break
                    send((block, None))
        except Exception as error:
            send((None, error))
        finally:
            send((None, None))

    def consume():
        while True:
            block, error = pending.get()
            if error is not None:
                raise error
            if block is None:
                return
            yield block

    decoder = threading.Thread(target=decode, name='ImageDecoder', daemon=True)
    decoder.start()
    try:
        yield consume()
    finally:
        stop.set()
        decoder.join(timeout=5)
        if decoder.is_alive():
            logger.warning('Source decoder is still finishing a read; disk I/O has stopped')


def write_block(disk, block):
    """Keep sequential 4 MiB writes; slices share memory on partial writes."""
    view = memoryview(block)
    pos = 0
    while pos < len(view):
        _, count = win32file.WriteFile(disk, view[pos:])
        if count <= 0 or count > len(view) - pos:
            raise IOError('Disk yazma işlemi geçersiz bayt sayısı döndürdü.')
        pos += count


class AlignedDiskReader:
    """Read-only, synchronous direct I/O with a VirtualAlloc-aligned buffer."""
    def __init__(self, number, logical_sector, physical_sector):
        self.handle = None
        self.buffer = None
        self.logical_sector = logical_sector
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                             ctypes.c_ulong, ctypes.c_ulong]
        self.kernel.VirtualAlloc.restype = ctypes.c_void_p
        self.kernel.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
        self.kernel.VirtualFree.restype = ctypes.c_int
        self.kernel.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                         ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
        self.kernel.ReadFile.restype = ctypes.c_int
        try:
            self.buffer = self.kernel.VirtualAlloc(None, CHUNK, 0x3000, 0x04)
            if not self.buffer:
                raise ctypes.WinError(ctypes.get_last_error())
            if self.buffer % physical_sector:
                raise ValueError('Direct-read buffer is not physically sector aligned')
            self.handle = win32file.CreateFile(
                r'\\.\PhysicalDrive' + str(number), win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_NO_BUFFERING, None)
        except Exception:
            self.close()
            raise

    def read(self, size):
        if not 0 < size <= CHUNK or size % self.logical_sector:
            raise ValueError('Direct-read length is not logically sector aligned')
        count = ctypes.c_ulong()
        if not self.kernel.ReadFile(int(self.handle), self.buffer, size, ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if count.value != size:
            raise IOError(f'Disk kısa okuma döndürdü: {count.value}/{size} bayt.')
        return ctypes.string_at(self.buffer, size)

    def seek(self, offset):
        win32file.SetFilePointer(self.handle, offset, win32con.FILE_BEGIN)

    def close(self):
        try:
            if self.handle is not None:
                self.handle.Close()
                self.handle = None
        finally:
            if self.buffer:
                self.kernel.VirtualFree(self.buffer, 0, 0x8000)
                self.buffer = None


def verify_image(disk, number, image_path, expanded_bytes, selected, progress, first_block):
    """Verify the body before publishing the MBR, then commit/read back the prefix."""
    logical = int(selected.get('LogicalSectorSize') or 0)
    physical = int(selected.get('PhysicalSectorSize') or 0)
    aligned = (logical in (512, 1024, 2048, 4096) and
               physical in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536) and
               physical >= logical and CHUNK % logical == 0 and expanded_bytes % logical == 0)
    reader = None
    checked = 0
    direct_reads = 0

    def read_current(size, offset):
        nonlocal reader, direct_reads
        if reader:
            try:
                result = reader.read(size)
                direct_reads += 1
                return result
            except (OSError, pywintypes.error) as error:
                if direct_reads or getattr(error, 'winerror', None) not in DIRECT_IO_UNSUPPORTED:
                    raise
                logger.warning('First direct read unsupported; buffered fallback: %s', error)
                reader.close()
                reader = None
                win32file.SetFilePointer(disk, offset, win32con.FILE_BEGIN)
        return win32file.ReadFile(disk, size)[1]

    try:
        if aligned:
            try:
                reader = AlignedDiskReader(number, logical, physical)
            except (OSError, pywintypes.error) as error:
                if getattr(error, 'winerror', None) not in DIRECT_IO_UNSUPPORTED:
                    raise
                logger.warning('Direct verification unsupported; using buffered reads: %s', error)
        else:
            logger.warning('Direct verification skipped: logical=%s physical=%s image_bytes=%s',
                           logical, physical, expanded_bytes)
        logger.info('Verification mode: %s; prefetch_blocks=%s block_bytes=%s',
                    'unbuffered' if reader else 'buffered', PREFETCH_BLOCKS, CHUNK)
        win32file.SetFilePointer(disk, len(first_block), win32con.FILE_BEGIN)
        if reader:
            reader.seek(len(first_block))
        logger.info('Verifying image body with partition table still withheld: deferred_bytes=%s', len(first_block))
        with image_blocks(image_path) as blocks:
            for block in blocks:
                if checked + len(block) > expanded_bytes:
                    raise IOError('Doğrulama sırasında imaj uzunluğu değişti.')
                if checked == 0:
                    if block != first_block:
                        raise IOError('İmajın ilk bloğu yazma sırasında değişti.')
                    checked = len(block)
                    continue
                result = read_current(len(block), checked)
                if len(result) != len(block) or result != block:
                    raise IOError(f'Doğrulama başarısız: byte offset {checked}.')
                checked += len(block)
                progress('Doğrulanıyor', checked - len(first_block), expanded_bytes)
        if checked != expanded_bytes:
            raise IOError('Doğrulama sırasında imaj uzunluğu değişti.')
        logger.info('Image body verification passed: bytes=%s; publishing partition table now',
                    checked - len(first_block))
        progress('İmajın bölüm tablosu yazılıyor', checked - len(first_block), expanded_bytes)
        win32file.FlushFileBuffers(disk)
        win32file.SetFilePointer(disk, 0, win32con.FILE_BEGIN)
        write_block(disk, first_block)
        win32file.FlushFileBuffers(disk)
        win32file.SetFilePointer(disk, 0, win32con.FILE_BEGIN)
        if reader:
            reader.seek(0)
        result = read_current(len(first_block), 0)
        if len(result) != len(first_block) or result != first_block:
            raise IOError('Bölüm tablosunu içeren ilk blok doğrulanamadı: byte offset 0.')
        logger.info('Partition table committed, flushed and read-back verified: bytes=%s', len(first_block))
        progress('Doğrulanıyor', checked, expanded_bytes)
        return checked
    finally:
        if reader:
            reader.close()


def lock_volumes(number):
    handles = []
    try:
        for letter in volumes_on_disk(number):
            logger.info('Opening volume %s: on disk %s', letter, number)
            h = win32file.CreateFile('\\\\.\\' + letter + ':', win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                     win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None,
                                     win32con.OPEN_EXISTING, 0, None)
            handles.append(h)
            logger.info('Locking volume %s:', letter)
            win32file.DeviceIoControl(h, FSCTL_LOCK_VOLUME, None, 0)
            logger.info('Dismounting volume %s:', letter)
            win32file.DeviceIoControl(h, FSCTL_DISMOUNT_VOLUME, None, 0)
        logger.info('Volume preparation complete: disk=%s locked_volumes=%s', number, len(handles))
        return handles
    except Exception:
        for h in handles:
            h.Close()
        raise


def write_image(number, image_path, expanded_bytes, progress, expected_device):
    logger.info('Rechecking target identity: disk=%s expected=%s', number, disk_identity(expected_device))
    # Check device identity immediately before opening it, not just when the UI refreshes.
    current = scan_disks()
    selected = next((device for device in current if int(device['Number']) == number), None)
    if selected is None or disk_identity(selected) != disk_identity(expected_device):
        raise RuntimeError('Seçilen aygıt çıkarıldı, değişti veya artık yazmaya uygun değil.')
    if expanded_bytes > int(selected['Size']):
        raise RuntimeError('İmaj hedef aygıt kapasitesinden büyük.')
    if expanded_bytes < 512:
        raise RuntimeError('İmaj bir disk bölüm tablosu içeremeyecek kadar küçük.')
    logger.info('Identity and capacity passed: disk=%s capacity=%s image_bytes=%s',
                number, selected['Size'], expanded_bytes)
    locks = lock_volumes(number)
    disk = None
    try:
        logger.info('Opening physical disk %s for writing', number)
        disk = win32file.CreateFile(r'\\.\PhysicalDrive' + str(number),
                                   win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                   win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                   None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_WRITE_THROUGH, None)
        progress('Eski disk bölümleri temizleniyor', 0, expanded_bytes)
        # Native equivalent of diskpart clean, also used by Raspberry Pi Imager.
        # Fail closed: never continue writing after a failed layout deletion.
        try:
            logger.info('Deleting drive layout: disk=%s ioctl=0x%X', number, IOCTL_DISK_DELETE_DRIVE_LAYOUT)
            win32file.DeviceIoControl(disk, IOCTL_DISK_DELETE_DRIVE_LAYOUT, None, 0)
            logger.info('Drive layout deleted: disk=%s', number)
        except pywintypes.error as error:
            # RAW media may have no layout to delete.
            if error.winerror not in (1, 2):
                raise RuntimeError('Disk bölümleri temizlenemedi: ' + str(error)) from error
            logger.info('No existing drive layout: disk=%s winerror=%s', number, error.winerror)
        win32file.SetFilePointer(disk, 0, win32con.FILE_BEGIN)
        written = 0
        logger.info('Safe I/O: block_bytes=%s prefetch_blocks=%s outstanding_disk_requests=1 write_through=True',
                    CHUNK, PREFETCH_BLOCKS)
        with image_blocks(image_path) as blocks:
            # Keep the partition table unpublished until all image data is down.
            # The image itself defines the new partitions; no temporary format.
            first_block = next(blocks, b'')
            if not first_block:
                raise IOError('İmaj boş veya uzunluğu değişti.')
            logger.info('Writing image body; first %s bytes held for final partition table write', len(first_block))
            win32file.SetFilePointer(disk, len(first_block), win32con.FILE_BEGIN)
            written = len(first_block)
            for block in blocks:
                if written + len(block) > expanded_bytes:
                    raise IOError('İmaj uzunluğu değişti.')
                write_block(disk, block)
                written += len(block)
                progress('Yazılıyor', written, expanded_bytes)
        if written != expanded_bytes:
            raise IOError('İmaj uzunluğu değişti.')
        logger.info('Flushing image body: bytes=%s', written)
        win32file.FlushFileBuffers(disk)
        logger.info('Image body flushed; verifying before committing partition table')
        checked = verify_image(disk, number, image_path, expanded_bytes, selected, progress, first_block)
        # Release old volume locks before publishing the new layout to Windows.
        for h in locks:
            h.Close()
        locks.clear()
        logger.info('Verification passed: bytes=%s; volume locks released', checked)
        progress('Windows disk görünümü yenileniyor', checked, expanded_bytes)
        win32file.DeviceIoControl(disk, IOCTL_DISK_UPDATE_PROPERTIES, None, 0)
        logger.info('Windows disk properties refreshed: disk=%s', number)
    finally:
        if disk is not None:
            disk.Close()
        for h in locks:
            h.Close()
        logger.info('Disk and volume handles closed: disk=%s', number)


class Main(wx.Frame):
    def __init__(self, admin):
        super().__init__(None, title=APP, size=(980, 640))
        self.SetIcons(wx.IconBundle(str(ICON_PATH), wx.BITMAP_TYPE_ICO))
        self.SetMinSize((820, 580))
        self.busy = False
        self.scanning = False
        self.closed = False
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label='Kestrel Disk Imager')
        font = title.GetFont()
        font.PointSize = 17
        font = font.Bold()
        title.SetFont(font)
        root.Add(title, 0, wx.ALL, 20)
        image_row = wx.BoxSizer(wx.HORIZONTAL)
        self.image_field = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self.browse = wx.Button(panel, label='Gözat…')
        image_row.Add(self.image_field, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 10)
        image_row.Add(self.browse, 0)
        root.Add(wx.StaticText(panel, label='İmaj dosyası (.img.xz)'), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        root.Add(image_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        self.image_path = None
        self.device = wx.StaticText(panel, label='İmaj dosyasını seçin; ardından hedef aygıtlar taranacak.')
        root.Add(self.device, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        self.disk_summary = wx.StaticText(panel, label='Aygıtlar henüz taranmadı.')
        root.Add(self.disk_summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        self.disk_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((('Disk', 50), ('Windows aygıt adı', 210),
                                               ('Bağlantı', 75), ('Kapasite', 90),
                                               ('Durum', 110), ('Yazma uygunluğu', 320))):
            self.disk_list.InsertColumn(index, label, width=width)
        root.Add(self.disk_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        progress_row = wx.BoxSizer(wx.HORIZONTAL)
        self.status = wx.StaticText(panel, label='Yazılacak .img.xz dosyasını seçin.')
        self.percent = wx.StaticText(panel, label='%0', style=wx.ALIGN_RIGHT)
        percent_font = self.percent.GetFont()
        percent_font.PointSize = 28
        self.percent.SetFont(percent_font.Bold())
        self.percent.SetForegroundColour(wx.Colour(28, 96, 163))
        self.percent.SetMinSize(self.FromDIP((125, -1)))
        progress_row.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        progress_row.Add(self.percent, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(progress_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        self.gauge = wx.Gauge(panel, range=100)
        self.gauge.SetMinSize((-1, self.FromDIP(32)))
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh = wx.Button(panel, label='Aygıtları Tara')
        self.start = wx.Button(panel, label='SD Karta Yaz ve Doğrula')
        row.Add(self.refresh, 0, wx.RIGHT, 10)
        row.Add(self.start, 0)
        row.AddStretchSpacer()
        row.Add(github_link(panel, 'GitHub', REPO_URL, self.FromDIP(16)), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        self.about = wx.Button(panel, label='Hakkında')
        row.Add(self.about, 0)
        root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        panel.SetSizer(root)
        self.browse.Bind(wx.EVT_BUTTON, self.choose_image)
        self.refresh.Bind(wx.EVT_BUTTON, self.rescan)
        self.start.Bind(wx.EVT_BUTTON, self.begin)
        self.about.Bind(wx.EVT_BUTTON, self.show_about)
        self.disk_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select_device)
        self.disk_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.deselect_device)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.candidate = None
        self.admin = admin
        self.selection_identity = None
        self.eligible_disks = {}
        self.image_available = False
        self.scan_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.pulse_scan, self.scan_timer)
        self.update_ready_state()
        self.Centre()

    def choose_image(self, event):
        if self.busy or self.scanning:
            return
        initial_dir = str(DEFAULT_IMAGE_DIR) if DEFAULT_IMAGE_DIR.is_dir() else str(Path.home())
        with wx.FileDialog(self, 'Yazılacak disk imajını seçin',
                           defaultDir=initial_dir,
                           wildcard='XZ sıkıştırılmış disk imajı (*.img.xz)|*.img.xz',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            selected = Path(dialog.GetPath())
            if not selected.name.lower().endswith('.img.xz') or not selected.is_file():
                wx.MessageBox('Yalnızca mevcut .img.xz dosyaları seçilebilir.', APP,
                              wx.OK | wx.ICON_ERROR)
                return
            self.image_path = selected
            logger.info('Source image selected: %s', selected)
            self.image_field.SetValue(str(selected))
            self.rescan()

    def rescan(self, event=None):
        if self.busy or self.scanning or self.closed:
            return
        self.scanning = True
        self.selection_identity = disk_identity(self.candidate) if self.candidate else None
        self.candidate = None
        self.start.Disable()
        self.refresh.Disable()
        self.browse.Disable()
        self.disk_list.Disable()
        self.device.SetLabel('Depolama aygıtları taranıyor…')
        self.disk_list.DeleteAllItems()
        self.disk_summary.SetLabel('Algılanan diskler: taranıyor…')
        self.show_indeterminate('Aygıt bilgileri alınıyor…')
        threading.Thread(target=self.scan_worker, args=(self.image_path,), daemon=True).start()

    def pulse_scan(self, event):
        self.gauge.Pulse()

    def show_indeterminate(self, stage):
        if self.closed:
            return
        self.gauge.SetValue(0)
        self.percent.SetLabel('…')
        self.status.SetLabel(stage)
        self.scan_timer.Start(100)

    def scan_worker(self, image_path):
        try:
            disks, readers, visible = scan_devices(include_diagnostics=True)
            image_available = image_path is not None and image_path.is_file()
            error = None
        except Exception as exc:
            logger.exception('Device rescan failed')
            disks, readers, visible, error, image_available = [], [], [], str(exc), False
        wx.CallAfter(self.apply_scan, disks, readers, visible, error, image_available)

    def apply_scan(self, disks, readers, visible, error, image_available):
        if self.closed:
            return
        self.scan_timer.Stop()
        self.scanning = False
        self.candidate = None
        self.eligible_disks = {int(device['Number']): device for device in disks}
        self.image_available = image_available
        self.gauge.SetValue(0)
        self.percent.SetLabel('%0')
        self.refresh.Enable()
        self.browse.Enable()
        self.disk_list.Enable()
        self.start.Disable()
        self.disk_list.DeleteAllItems()
        self.disk_summary.SetLabel(f'Algılanan diskler: {len(visible)} (Windows boot/sistem diskleri gizlidir)')
        if error:
            self.disk_summary.SetLabel('Algılanan diskler: tarama başarısız')
            self.device.SetLabel('Disk tarama hatası: ' + error)
            self.status.SetLabel('Aygıtlar alınamadı. Aygıtları Tara düğmesiyle tekrar deneyin.')
            return
        for device in visible:
            row = self.disk_list.InsertItem(self.disk_list.GetItemCount(), str(device['Number']))
            self.disk_list.SetItemData(row, int(device['Number']))
            size = int(device.get('Size') or 0)
            state = 'Çevrimdışı' if device.get('IsOffline') else 'Çevrimiçi'
            if device.get('IsReadOnly'):
                state += ' / salt okunur'
            reasons = disk_rejection_reasons(device)
            eligibility = '; '.join(reasons) if reasons else 'Uygun'
            values = (device.get('FriendlyName') or '', str(device.get('BusType') or ''),
                      f'{size / 1024**3:.1f} GiB' if size else '0 / kart yok', state, eligibility)
            for column, value in enumerate(values, 1):
                self.disk_list.SetItem(row, column, value)
        if not disks:
            if visible:
                self.device.SetLabel('Yazmaya uygun aygıt bulunamadı. Listede nedenini kontrol edin.')
            elif readers:
                self.device.SetLabel('USB kart okuyucu bulundu. Kartı takıp tekrar tarayın.')
            else:
                self.device.SetLabel('SD/MMC veya USB depolama aygıtı bulunamadı.')
        else:
            self.device.SetLabel('Yazılacak hedef aygıtı aşağıdaki listeden seçin.')
        self.update_ready_state()
        # Preserve an explicit choice only if the same device survived the scan.
        for row, device in enumerate(visible):
            if (self.selection_identity is not None and
                    disk_identity(device) == self.selection_identity and
                    int(device['Number']) in self.eligible_disks):
                self.disk_list.Select(row)
                self.set_candidate(device)
                break

    def select_device(self, event):
        if self.busy or self.scanning or self.closed:
            return
        number = self.disk_list.GetItemData(event.GetIndex())
        self.set_candidate(self.eligible_disks.get(number))

    def set_candidate(self, device):
        self.candidate = device
        if device:
            self.selection_identity = disk_identity(device)
            self.device.SetLabel(f"Hedef ({device['BusType']}): Disk {device['Number']} — {device['FriendlyName']} — {int(device['Size']) / 1024**3:.1f} GiB")
        else:
            self.selection_identity = None
            self.device.SetLabel('Seçilen aygıt yazmaya uygun değil. Listedeki nedeni kontrol edin.')
        self.update_ready_state()

    def deselect_device(self, event):
        if self.busy or self.scanning or self.closed or self.candidate is None:
            return
        if self.disk_list.GetItemData(event.GetIndex()) == int(self.candidate['Number']):
            self.candidate = None
            self.selection_identity = None
            self.device.SetLabel('Yazılacak hedef aygıtı aşağıdaki listeden seçin.')
            self.update_ready_state()

    def update_ready_state(self):
        self.start.Disable()
        if not self.image_available:
            self.status.SetLabel('Yazılacak .img.xz dosyasını seçin.')
        elif not self.admin:
            self.status.SetLabel('Yönetici yetkisi gerekiyor.')
        elif self.candidate is None:
            self.status.SetLabel('Listeden yazmaya uygun bir hedef aygıt seçin.')
        else:
            self.status.SetLabel('Hazır. Yazmadan önce dosya bütünlüğü kontrol edilecek.')
            self.start.Enable()

    def begin(self, event):
        if self.busy or self.scanning or not self.candidate or not self.admin:
            return
        if self.image_path is None or not self.image_path.is_file() or not self.image_path.name.lower().endswith('.img.xz'):
            return
        d = self.candidate
        msg = (f"Disk {d['Number']} — {d['FriendlyName']} ({int(d['Size']) / 1024**3:.1f} GiB)\n\n"
               'BU DİSKTEKİ TÜM VERİLER VE BÖLÜMLER SİLİNECEK.\n'
               'Yeni bölümler imajdan oluşturulacak. Devam edilsin mi?')
        if wx.MessageBox(msg, 'Son onay', wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING) != wx.YES:
            return
        self.busy = True
        self.disk_list.Disable()
        self.refresh.Disable()
        self.browse.Disable()
        self.start.Disable()
        threading.Thread(target=self.worker, args=(dict(d), self.image_path), daemon=True).start()

    def progress(self, stage, count, total):
        percent = min(100, int(count * 100 / max(1, total)))
        now = time.monotonic()
        previous = getattr(self, '_log_progress', None)
        if (previous is None or previous[0] != stage or
                percent // 5 != previous[1] // 5 or now - previous[2] >= 10):
            logger.info('Progress: stage=%s bytes=%s/%s percent=%s', stage, count, total, percent)
            self._log_progress = (stage, percent, now)
        previous_ui = getattr(self, '_ui_progress', None)
        if (previous_ui is None or previous_ui[0] != stage or
                now - previous_ui[1] >= 0.2 or count >= total):
            self._ui_progress = (stage, now)
            wx.CallAfter(self.show_progress, stage, count, total)

    def show_progress(self, stage, count, total):
        if self.closed:
            return
        self.scan_timer.Stop()
        value = min(100, max(0, count * 100 / max(1, total)))
        self.gauge.SetValue(int(value))
        self.percent.SetLabel(f'%{value:.1f}')
        self.status.SetLabel(stage)

    def worker(self, device, image_path):
        self._log_progress = None
        self._ui_progress = None
        started = time.monotonic()
        logger.info('WRITE START: image=%s target=%s', image_path, device)
        try:
            expected = sidecar_sha256(image_path)
            logger.info('Checking source SHA-256 (read-only): sidecar=%s', expected or 'none')
            wx.CallAfter(self.status.SetLabel, 'SHA-256 doğrulanıyor…')
            digest = digest_file(image_path, lambda count, total:
                                 self.progress('SHA-256 doğrulanıyor', count, total))
            logger.info('Source SHA-256: actual=%s', digest)
            if expected and digest != expected:
                raise RuntimeError('İmaj SHA-256 değeri .sha256 dosyasıyla eşleşmiyor. Yazma engellendi.')
            note = image_check_note(digest, expected)
            logger.info('Image check: %s', note)
            wx.CallAfter(self.show_indeterminate, note + ' Sıkıştırılmış imaj ve kapasite kontrol ediliyor…')
            logger.info('Checking compressed image integrity and expanded size (read-only)')
            size = compressed_size(image_path)
            write_image(int(device['Number']), image_path, size, self.progress, device)
            logger.info('WRITE SUCCESS: elapsed_seconds=%.1f', time.monotonic() - started)
            wx.CallAfter(self.finish, 'İşlem tamamlandı: yazma ve birebir doğrulama başarılı.\n' + note, False)
        except Exception as e:
            logger.exception('WRITE FAILED: image=%s disk=%s elapsed_seconds=%.1f',
                             image_path, device['Number'], time.monotonic() - started)
            wx.CallAfter(self.finish, 'İşlem başarısız: ' + str(e) + '\n\nHata kaydı: ' + str(LOG_PATH), True)

    def finish(self, message, error):
        self.scan_timer.Stop()
        self.busy = False
        self.status.SetLabel(message)
        wx.MessageBox(message, APP, wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION))
        self.refresh.Enable()
        self.browse.Enable()
        self.rescan()

    def show_about(self, event):
        with AboutDialog(self, APP, APP_VERSION, ICON_PATH) as dialog:
            dialog.ShowModal()

    def on_close(self, event):
        if self.busy:
            wx.MessageBox('Yazma veya doğrulama devam ederken uygulama kapatılamaz.', APP, wx.OK | wx.ICON_WARNING)
            event.Veto()
        else:
            self.closed = True
            self.scan_timer.Stop()
            event.Skip()


if __name__ == '__main__':
    configure_logging()
    if sys.platform != 'win32':
        raise SystemExit('Bu program yalnızca Windows üzerinde çalışır.')
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Kestrel.DiskImager')
    app = wx.App(False)
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    logger.info('Administrator privileges active: %s; opening main window without startup device scan', admin)
    window = Main(admin)
    app.SetTopWindow(window)
    window.Show()
    app.MainLoop()
    logger.info('Program closed')
