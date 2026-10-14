# EXE derleme ve imzalama

## Açık kaynak yayın: SignPath Foundation

Herkese açık sürümler yerelde değil, GitHub Actions'ta imzalanır
(`.github/workflows/build.yml`). Her push/PR'da testler + PyInstaller build
çalışır. `v*` etiketi itildiğinde imzasız EXE SignPath'e gönderilir, elle
onaylandıktan sonra imzalı EXE doğrulanır ve GitHub Release'e eklenir.
Yayıncı olarak "SignPath Foundation" görünür. Politika: `CODE_SIGNING_POLICY.md`.

Tek seferlik kurulum:
1. Repo: https://github.com/AydinFatoglu/kestrel-disk-imager (public, `main`).
   Commit kimliği yalnız bu repoda noreply adresidir (`git config user.email`).
2. https://signpath.org/apply üzerinden başvur; onaydan sonra SignPath'te
   proje (`kestrel-disk-imager`) ve `release-signing` politikası oluşur.
3. Repo ayarları: secret `SIGNPATH_API_TOKEN`; variables
   `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`.

Sürüm çıkarırken `version_info.txt` içindeki dört sürüm alanı güncellenir,
ardından `git tag v1.0.0 && git push --tags`.

Aşağıdaki yerel araçlar kurum içi/ticari sertifika ile imzalama içindir.

Mevcut programın kodu değiştirilmedi. Bu hazırlık sertifika satın almaz,
hesap oluşturmaz, Windows güven depolarını/politikalarını değiştirmez.
Mevcut EXE henüz imzasızdır.

## Hazır araçlar

- `.venv`: mevcut Python 3.11 ve sistem paketlerini kullanan workspace ortamı.
  Sürümler `requirements-build.txt` içinde sabitlendi; global paketler yükseltilmedi.
- PyInstaller 6.22.3, wxPython 4.3.2, pywin32 312.
- Microsoft SignTool: `tools/vendor/windows-sdk/bin/10.0.26100.0/x64/signtool.exe`.
- SSL.com CodeSignTool 1.3.3 ve beraberindeki Java: `tools/vendor/codesigntool`.
- SSL.com eSigner CKA 1.1.2 kurulum dosyası: `tools/vendor/esigner-cka`.
  Kurulum dosyası indirildi; Windows kriptografi sağlayıcısı henüz kurulmadı.
- İndirme adresleri ve SHA-256 değerleri: `tools/downloads/manifest.json`.

## Şimdi kullanılabilen komutlar

Workspace kökünde PowerShell ile:

```powershell
.\.venv\Scripts\python.exe tools/release.py doctor
.\.venv\Scripts\python.exe tools/release.py esigner-help
```

Yalnızca yeni bir unsigned EXE üretmek gerektiğinde:

```powershell
.\.venv\Scripts\python.exe tools/release.py build
```

Build komutu mevcut `KestrelDiskImager.spec` dosyasını kullanır. Var olan EXE'de
imza varsa onu ezmeyi reddeder.

## Sertifika/hizmet hesabı sağlandığında

SSL.com tercih edilirse sağlayıcının kılavuzuna göre eSigner CKA kurulup
sertifika hesabına bağlanmalıdır. Tek EXE için manuel OTP modu yeterlidir.
Hesap parolası, OTP, TOTP sırrı veya özel anahtar bu workspace'e ya da sohbete
yazılmaz. Kimlik bilgileri sağlayıcının uygulamasına girilir.

Sertifika Windows CurrentUser/My deposunda göründüğünde `doctor` komutu
Subject ve Thumbprint bilgisini listeler. Kurumsal CA sertifikaları ve
SignTool uyumlu tokenlar için de aynı imzalama komutu kullanılabilir.

```powershell
.\.venv\Scripts\python.exe tools/release.py sign --thumbprint SERTIFIKANIN_40_HANELI_THUMBPRINT_DEGERI
```

LocalMachine/My deposu için `--machine-store` eklenir. Varsayılan zaman damgası
adresi SSL.com'un `http://ts.ssl.com` servisidir; kurum/sağlayıcı gerektiriyorsa
`--timestamp-url` ile değiştirilir.

Komut orijinal `dist/KestrelDiskImager.exe` dosyasını korur. Bir kopyayı
`dist/signed/KestrelDiskImager.exe` olarak imzalar; SHA-256, RFC3161 zaman damgası,
Windows Authenticode güveni ve zaman damgası varlığı doğrulanır.
Başarısız imzalama/doğrulamada yalnızca yeni oluşturulan aday dosya kaldırılır.
Var olan signed çıktı üzerine yazılmaz.

Son kontrol:

```powershell
.\.venv\Scripts\python.exe tools/release.py verify
```

Başka bir EXE'nin imzasını incelemek için `verify` sonuna dosya yolu verilebilir.
`doctor` ve CLI yardım komutları bulut imzalama çağrısı yapmaz. `sign` komutu
gerçek sertifika/hizmet yetkisiyle imza kotası tüketebilir; hesap hazır olmadan
çalıştırılması gerekmez.

## Resmî kaynaklar

- Microsoft SDK araçları: https://www.nuget.org/packages/Microsoft.Windows.SDK.BuildTools/10.0.26100.9169
- SignTool: https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool
- SSL.com indirmeleri: https://www.ssl.com/downloads/
- CKA kurulumu: https://www.ssl.com/how-to/how-to-install-ssl-com-esigner-cloud-key-adapter-cka/
- CKA + SignTool: https://www.ssl.com/how-to/automate-ev-code-signing-with-signtool-or-certutil-esigner/
- CodeSignTool: https://www.ssl.com/guide/esigner-codesigntool-command-guide/
