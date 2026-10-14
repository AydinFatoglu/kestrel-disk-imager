"""About dialog and GitHub links; no disk or network access (links open the default browser)."""
from pathlib import Path

import wx
import wx.adv

REPO_URL = 'https://github.com/AydinFatoglu/kestrel-disk-imager'
AUTHOR = 'Aydin Fatoglu'
AUTHOR_URL = 'https://github.com/AydinFatoglu'
LINKS = (
    ('Proje sayfası', REPO_URL),
    ('Sürümler ve indirme', REPO_URL + '/releases'),
    ('Hata bildir / öneri', REPO_URL + '/issues'),
    ('Geliştirici: ' + AUTHOR, AUTHOR_URL),
)
GITHUB_ICON = Path(__file__).resolve().parent / 'assets' / 'github-mark.svg'


def github_bitmap(size):
    # A missing or unreadable icon must never block the imager window.
    if GITHUB_ICON.is_file():
        bundle = wx.BitmapBundle.FromSVGFile(str(GITHUB_ICON), wx.Size(size, size))
        if bundle.IsOk():
            return bundle
    return wx.BitmapBundle()


def github_link(parent, label, url, size=16):
    row = wx.BoxSizer(wx.HORIZONTAL)
    icon = github_bitmap(size)
    if icon.IsOk():
        row.Add(wx.StaticBitmap(parent, bitmap=icon), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
    link = wx.adv.HyperlinkCtrl(parent, label=label, url=url)
    link.SetToolTip(url)
    row.Add(link, 0, wx.ALIGN_CENTER_VERTICAL)
    return row


def icon_bitmap(icon_path, size):
    bitmap = wx.Bitmap()
    if icon_path.is_file():
        bitmap.CopyFromIcon(wx.IconBundle(str(icon_path), wx.BITMAP_TYPE_ICO).GetIcon(wx.Size(size, size)))
    return bitmap


class AboutDialog(wx.Dialog):
    def __init__(self, parent, app_name, version, icon_path):
        super().__init__(parent, title=f'{app_name} hakkında')
        root = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        logo = icon_bitmap(icon_path, self.FromDIP(48))
        if logo.IsOk():
            header.Add(wx.StaticBitmap(self, bitmap=logo), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 14)
        names = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=app_name)
        font = title.GetFont()
        font.PointSize = 15
        title.SetFont(font.Bold())
        names.Add(title)
        names.Add(wx.StaticText(self, label='Sürüm ' + version), 0, wx.TOP, 2)
        header.Add(names, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(header, 0, wx.ALL, 20)
        about = wx.StaticText(self, label=(
            '.img.xz disk imajlarını SD kartlara ve USB belleklere yazar, ardından her baytı '
            'geri okuyarak doğrular. Bölüm tablosu en son, imajın geri kalanı doğrulandıktan '
            'sonra yazılır. Program ağ bağlantısı kurmaz.'))
        about.Wrap(self.FromDIP(420))
        root.Add(about, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        for label, url in LINKS:
            root.Add(github_link(self, label, url, self.FromDIP(16)), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.AddSpacer(12)
        root.Add(wx.StaticText(self, label=f'© 2026 {AUTHOR} — MIT Lisansı'), 0, wx.LEFT | wx.RIGHT, 20)
        close = wx.Button(self, wx.ID_OK, 'Kapat')
        close.SetDefault()
        root.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 20)
        self.SetSizerAndFit(root)
        self.CentreOnParent()
