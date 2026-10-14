# Kestrel Disk Imager — durum

2026-10-14: Repo https://github.com/AydinFatoglu/kestrel-disk-imager (public).
Commit kimliği yalnız bu repoda 86136084+AydinFatoglu@users.noreply.github.com.
gh 2.102.0 kullanıcı klasöründe (%LOCALAPPDATA%\Programs\gh\bin, PATH'te değil),
AydinFatoglu olarak oturum açık (repo+workflow). İlk CI build başarılı.
Uyarı: actions v4/v5 Node 20 deprecation; ileride sürümler yükseltilmeli.
2026-10-14: SignPath Foundation başvurusu gönderildi (HubSpot formu; bireysel,
şirket adı boş, Reputation: yeni proje olduğu açıkça yazıldı). Yanıt bekleniyor.
Onay gelince: secret SIGNPATH_API_TOKEN + variables (org id, project/policy slug)
gh ile girilir, version_info.txt sürümü kontrol edilir, `v1.0.0` etiketi itilir.
README Download bölümüne SignPath ibaresi ve Releases bağlantısı eklendi
(formdaki Download URL = README#download şartı).

2026-10-14: Açık kaynak (SignPath Foundation) hazırlığı. Ad "Kestrel Disk
Imager": ana dosya `kestrel_disk_imager.py`, spec `KestrelDiskImager.spec`,
EXE `KestrelDiskImager.exe`, ikon `assets/kestrel.ico`. Kodda yalnız marka
metinleri değişti (APP, başlık, dosya diyaloğu, AppUserModelID, logger adı);
akış değişmedi. Eklendi: LICENSE (MIT), README.md (EN), CODE_SIGNING_POLICY.md,
SECURITY.md, version_info.txt (EXE sürüm bilgisi), .github/workflows/build.yml.
Kullanıcı kararıyla imaj kısıtı kalktı: her .img.xz yazılabilir. Yanında
`<imaj>.sha256` varsa eşleşmeli (okunamazsa da engeller); yoksa yazılır.
`FSDS_IMAGE_SHA256` (eski APPROVED_SHA256) eşleşirse yalnız "FSDS imajı
doğrulandı." notu durum satırında ve bitiş mesajında gösterilir.
test_image_checksum.py: 7 test; toplam 39 test geçti. `DEFAULT_IMAGE_DIR`
`C:\FS_Digital_Signage` kaldı (yoksa kullanıcı klasörü). SignPath başvurusu, GitHub repo ve
`CODE_SIGNING_POLICY.md` içindeki `OWNER` bekliyor. Ayrıntı: docs/signing.md.

2026-10-14: İmzalama workspace hazırlığı tamamlandı; ana program kaynağı
değişmedi (SHA256 2CB5B8BD68312FCF322720511F055A77943681BF0B3FF72A648963605035B507).
.venv system-site-packages kullanır; requirements-build.txt mevcut sürümleri
sabitler. Microsoft SDK NuGet 10.0.26100.9169 x64 SignTool ve SSL.com
CodeSignTool1.3.3/Java tools/vendor altında indirildi ve help komutları çalıştı.
CKA1.1.2 installer indirildi, SSL Corp Authenticode Valid; KURULMADI.
SignTool Microsoft imzası Valid. Araç URL/hashları tools/downloads/manifest.json.
tools/release.py doctor/build/sign/verify/esigner-help hazır. Sign unsigned
EXE'yi koruyup dist/signed kopyasını imzalar, timestamp/Windows trust doğrular;
signed çıktı overwrite edilmez. 4 güvenlik regresyon testi geçti. Native verify
RPI official EXE'de başarılı. Sertifika/hesap yok, gerçek signing yapılmadı.
CKA kurulumu/hesap bağlama ve sertifika edinme adımları kullanıcı bekliyor.
Kullanım docs/signing.md dosyasında. .gitignore venv/vendor/downloads/özel
anahtar uzantılarını dışlar. GUI, yazma akışı ve mevcut EXE değiştirilmedi.

2026-10-14: Sıkıştırılmış imaj kontrolü artık show_indeterminate ile scan_timer
Pulse kullanır; yüzde yerine … gösterilir. SHA hash'in %100 değeri bu aşamada
kalmaz. show_progress gerçek ilerleme başlayınca timer'ı durdurur; finish ve
on_close da durdurur. Native wx smoke hash100 → pulse → write25 geçişi başarılı.
Açık eski GUI bu değişikliği yeniden başlatılana kadar kullanmaz.

2026-10-14: SON fiziksel test BAŞARILI: pid21676,21:27:30 WRITE SUCCESS,
1101.2 saniye. Gövde4803076608 bayt MBR görünür olmadan doğrulandı; ardından
4194304 bayt ilk blok yazılıp geri okundu. Toplam4807270912 bayt doğrulandı,
refresh/kilit bırakma tamamlandı. Önceki SVI uyuşmazlığı tekrarlanmadı.

2026-10-14: GUI isteği uygulandı: Loading ve startup disk scan kaldırıldı.
Main(admin) doğrudan açılır; boş liste ve yazma disabled. İmaj seçiminde tek
background scan yapılır; manual refresh, yazma öncesi identity recheck ve
yazma sonrası scan korunur. Gauge32DIP, ayrı bold28pt mavi yüzde etiketi,
show_progress wx ana thread'de günceller. Canlı wx smoke: başlangıç0scan,
imaj seçimi1scan, %42.5/gauge42 eşleşmesi ve güvenli disabled state doğrulandı.
Ekran görüntüsüyle layout kontrol edildi; fiziksel diske yazılmadı.

2026-10-14: ÖNEMLİ SON BULGU/DÜZELTME. Son başarısız full write denemesinde
verify blok411041792'de durdu. Salt okunur FAT incelemesi 228 farklı baytı
System Volume Information/WPSettings.dat/IndexerVolumeGuid olarak belirledi:
kaynakta sıfır ve FAT'te free cluster196610–196612. Root cluster527'de kaynakta
olmayan SVI girdisi var. FAT oluşturulma20:47:28/modification20:47:32, yani
MBRcommit20:47:17 sonrası verify sürerken Windows yazmış. Bu, rastgele donanım
bozulması olarak yorumlanmamalı. Direct/buffered okumalar aynı farkları verdi.
RPI kaynağı tekrar kontrol edildi: _verify() BEFORE _firstBlock commit.
Bizdeki sıra yanlıştı ve düzeltildi: gövde write/flush → gövde verify (ilk blok
hâlâ saklı) → first_block write/flush → first_block readback verify → refresh.
verify_image artık first_block parametresi alır ve final commit/readback yapar.
32 test geçti, gerçek Windows geçici dosya direct-read finalization testi dahil.
Bu turda SD karta yazılmadı; güncel düzeltmeyle full write testi bekliyor.
Açık eski uygulama kodu kullanıyor olabilir; yeni deneme için güncel sürüm
başlatılmalıdır. Ayrıntılar docs/rpi-imager-windows.md dosyasında.

2026-10-14: Kullanıcı ek disk alanı kullanmayan üç iyileştirmeyi uyumluluk
sınırlarıyla istedi. 4 MiB sabit blok, iki blok RAM prefetch (yazma ve verify),
tek senkron disk isteği, WRITE_THROUGH/flush korunur. memoryview kısmi yazma
kopyalarını azaltır, UI 5 Hz ile sınırlandı. Verify fiziksel/mantıksal sektör
uygunsa VirtualAlloc + yalnızca okumalı NO_BUFFERING handle kullanır; yalnız
açma/ilk okuma 1/50/87 hatalarında buffered geri dönüş var ve loglanır.
Gerçek I/O hataları/uyuşmazlıklar işi durdurur. Geçici .img oluşturulmaz.
27 test geçti; gerçek Windows dosya API'si geçici dosyalarla test edildi.
Disk 1'de yalnız okuma ile ilk4MiB/son sektör buffered/direct eşleşti.
Yeni sürümde tam yazma/doğrulama hız ölçümü henüz yapılmadı. Ayrıntılar docs'ta.

2026-10-14: Kullanıcı isteğiyle Raspberry Pi Imager Windows yaklaşımına uygun
yazma öncesi bölüm tablosu temizliği eklendi (`IOCTL_DISK_DELETE_DRIVE_LAYOUT`,
diskpart clean eşdeğeri). Geçici partition/format yok; yeni bölümler imajdan
gelir. İlk blok veri flush edildikten sonra yazılır, birebir doğrulama sonrası
volume kilitleri bırakılır ve `IOCTL_DISK_UPDATE_PROPERTIES` çağrılır.
Temizleme hatasında yazma durur; RAW disk için hata 1/2 kabul edilir.
13 test ve Python sözdizimi kontrolü başarılı. Gerçek diske yazılmadı.
Ayrıntı: `docs/rpi-imager-windows.md`. Açık eski uygulama yeni kod için yeniden
başlatılmalıdır.

2026-10-14: Kullanıcı isteğiyle USB okuyucu kimliği izin listesi kaldırıldı.
Vendor, model veya VID/PID kısıtı yok. USB okuyucular yalnız Windows'un
bildirdiği kart okuyucu açıklamasına göre seçilir; genel USB depolama aygıtları
başlangıçta gizleniyordu. Bağlı okuyucu yalnız `Mass Storage Device` bildirdiğinden bu yöntemle
tanınamaz; belirli birime özel istisna yoktur. Kart yokken yazma engellenir.
Teknik davranış: `docs/usb-readers.md`.

2026-10-14: Yükleme penceresi eklendi. İlk hazırlık ve sonraki tüm aygıt
taramaları arka planda çalışır; wx kontrolleri ana iş parçacığında güncellenir.
Başlangıç sonucuyla ana pencere açılır, ikinci tarama yapılmaz. Kapatılmış
pencereye geç gelen tarama sonucu uygulanmaz. Ayrıntı: `docs/startup-threading.md`.
Python sözdizimi kontrolü başarılı; ek test veya fiziksel yazma yapılmadı.

2026-10-14: Tanılama için Windows boot/sistem diskleri dışındaki tüm diskler
ana pencerede gösterilir; kapasite, durum ve dışlama nedenleri görünür.
Canlı Windows sorgusu: takılı kart Disk 1, USB, 15931539456 byte, çevrimiçi,
salt okunur değil; adı `Mass Storage Device`. Yazmayı engelleyen neden
kart okuyucu açıklaması filtresidir. Görünürlük yazma izni vermez.
Python sözdizimi kontrol edildi; ek test çalıştırılmadı.

2026-10-14: Resmi Raspberry Pi Imager Windows kaynağı incelendi.
SetupDi + DeviceIoControl ile disk ve USB bus/sürücü sınıflandırması yapıyor;
kart okuyucu adı veya okuyucu VID/PID izin listesi aramıyor. USB flash
bellekleri de kabul ediyor; USB okuyucu/bellek için evrensel ayrım uygulamıyor.
Bizim genel adlı okuyucuyu engelleyen açıklama filtresi onların yaklaşımında
yok. Kaynak bağlantıları: `docs/rpi-imager-windows.md`.

2026-10-14: Kullanıcı araştırma sonucunun uygulanmasını istedi. USB/SD/MMC
bus temelli kabul eklendi; kart okuyucu adı yazma şartı olmaktan çıkarıldı.
Genel USB depolama ve flash bellekler de uygunsa seçilebilir. Hedef otomatik
seçilmez; kullanıcı listeden seçer. Birden fazla uygun cihaz yazmayı engellemez.
Yazma öncesi seçilen hedefin kimliği ve uygunluğu yeniden denetlenir. Sistem,
salt okunur, offline ve yetersiz kapasiteli disk korumaları korunur.
Canlı salt-okunur algılama: Disk 1 `Mass Storage Device`, USB, 14.8 GiB artık
uygun hedef olarak bulundu; görünen 1 / uygun 1. Python sözdizimi başarılı.
Ek test paketi veya fiziksel yazma çalıştırılmadı.

Mevcut testler izin listesi olmadan çalışacak şekilde uyarlandı; kullanıcı
isteğiyle ek test çalıştırılmadı. Takılı SD kartla
algılama ve fiziksel yazma testi bekliyor. Sistem Python'unda GUI bağımlılıkları
kurulu değil; bağımlılık kurulumu yapılmadı.
