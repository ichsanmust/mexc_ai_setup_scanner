# MEXC AI Setup Scanner

Aplikasi lokal berbasis Python untuk memindai peluang trading **Crypto Futures di MEXC** (menggunakan **public market data only**, tanpa MEXC API key dan tanpa auto-order), menghitung indikator teknikal secara deterministik, mengevaluasi setup menggunakan LLM berformat JSON tervalidasi, menyimpannya ke database **MySQL**, melacak outcome secara berkala, serta menampilkan dashboard lokal lengkap dengan **Candlestick Chart, Volume, & DSS Bressert** untuk eksekusi manual.

---

## Fitur Utama

- **Public Market Data Only:** Mengambil kontrak USDT-M aktif, ticker 24 jam (`lastPrice`, `fairPrice`, `indexPrice`, `fundingRate`, `holdVol`, dll.), dan candlestick multi-timeframe (`HTF` & `LTF`) dari `https://contract.mexc.com/api/v1/contract/...`. *(Catatan: MEXC public REST tidak menyediakan feed likuidasi; crowding/potensi squeeze dievaluasi dari `funding_rate` + `open_interest_hold_vol`.)*
- **Deterministic Feature Builder:** Menghitung indikator murni dari **candle yang sudah close** (`forming_candle` dipisah sebagai konteks berjalan): EMA 21/50/200 (`ema21_slope_pct`, `ema50_slope_pct`), RSI 14, `prev_rsi14`, ATR 14, Volume MA20 & `volume_ratio`, `compression_ratio`, **DSS Bressert (`10 9 5`, meliputi `dss`, `prev_dss`, `dss_signal`, `prev_dss_signal`, `dss_cross_up`, `dss_cross_down`)**, 3 candle terakhir detail (`recent_candles`) + 15 candle ringkas (`compact_candles_15`), pivot & struktur (`recent_swing_high/low`, `prior_swing_high/low`, `swept_prior_high/low`, `structure_bias`, `nearest_support/resistance`, `support_is_fallback`/`resistance_is_fallback`), normalisasi OI (`open_interest_usdt`, `oi_to_volume_ratio`, `funding_rate_pct`, `funding_extreme`), **`level_candidates`** (kandidat SL/TP & R:R deterministik), serta konteks pasar global **`market_context.btc`**.
- **Per-Strategy Timeframe, Candles & Expiry:** Setiap strategi aktif (baik 1 maupun multi-strategi) otomatis memakai `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, dan `suggested_expiry_hours` masing-masing dari tabel `strategies` (penarikan kline MEXC terdeduplikasi per `(symbol, interval)` agar hemat request). Pre-filter `Min/Max ATR (%)` memakai baseline `Min15` yang otomatis diskalakan `√(interval/15m)` sesuai LTF strategi.
- **Strategy Registry di MySQL (`strategies`):**
  - Menyimpan nama/kode strategi (bisa diedit mis. akhiran `_SWING`, `_INTRADAY`, `_SCALP`), tipe trading (`trade_style`), estimasi lama trade (`holding_period`), konfigurasi scan per strategi (`suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, `suggested_expiry_hours`), minimum R:R (`min_rr`), toggle aktif/nonaktif (`is_active`), dan isi `prompt_text` (dapat disinkronkan aman dari `prompts/` lewat `POST /api/strategies/sync-prompts` tanpa menimpa kustomisasi kecuali `?force=true`).
  - Bawaan awal (auto-seeded dari `prompts/*.txt`):
    - `TREND_PULLBACK` (`INTRADAY`, 4–24 Jam, HTF `Min60` / LTF `Min15`, min R:R `1.8`)
    - `BREAKOUT_MOMENTUM` (`INTRADAY_SWING`, 4–48 Jam, HTF `Min60` / LTF `Min15`, min R:R `2.0`)
    - `MEAN_REVERSION_SCALP` (`SCALP`, 1–6 Jam, HTF `Min30` / LTF `Min5`, min R:R `1.5`)
- **Deterministic Risk & Math Guard + Reasoning-First AI:**
  - Skema output AI (`AISetupDecision`) menempatkan `htf_analysis`, `ltf_trigger_analysis`, dan `checklist` konfluensi sebelum `decision` & level harga, dilengkapi 1× retry otomatis bila JSON/validasi gagal, serta pelacakan `prompt_version` & endpoint kalibrasi `GET /api/analytics/calibration`.
  - Validator menolak `confidence < min_confidence`, memverifikasi konsistensi `checklist`, memvalidasi jarak SL (`0.35x–5.0x ATR14 LTF`) dan kewajaran jarak `LIMIT`/`MARKET` (entry `MARKET` di-re-anchor ke `last_price` aktual), menghitung ulang R:R (termasuk buffer fee round-trip `0.04%`) terhadap `min_rr` strategi (disesuaikan oleh **Risk Profile**: `CONSERVATIVE` standar, `MODERATE` `-0.2` min `1.3`, `AGGRESSIVE` `-0.3` min `1.2`), serta mencegah duplikasi maupun konflik arah berlawanan (`LONG` vs `SHORT`) pada pair yang sama.
- **Outcome Tracker Adaptif & Manajemen Status Lengkap:**
  - Mendukung **10 status**: `OPEN`, `ENTRY_HIT`, `EXTENDED`, `MANUAL_TAKEN`, `MANUAL_SKIPPED`, `HIT_TP`, `HIT_SL`, `EXPIRED`, `CLOSED_MANUAL_TP`, `CLOSED_MANUAL_CL`.
  - Tracker menggunakan interval adaptif (`Min1` / `Min5` / `Min15`) dan live ticker `lastPrice` sehingga perubahan Entry, SL, dan TP pada posisi `LONG` maupun `SHORT` tetap akurat bahkan saat harga bergerak cepat antar siklus cek (min 15 detik). Status `EXTENDED` mempertahankan statusnya walaupun Entry tersentuh (`entry_hit_at` tetap dicatat + badge `ENTRY`) dan memprioritaskan `expiry_hours` dari snapshot scan run terkait.
- **Audit Snapshot Setting per Scan Run (`scan_runs.settings_snapshot`):** Setiap eksekusi scan merekam snapshot lengkap strategi beserta `strategy_timeframes` (`HTF/LTF`, `kline_limit`, `expiry_hours` tiap strategi), filter ATR/volume, dan konfigurasi AI yang dipakai untuk diaudit di modal **Detail Evaluasi** dan sebagai referensi perpanjangan expiry setup terkait.
- **Navigasi Halaman Terpisah, Filter Date Range, & Chart TradingView Lightweight Charts (WIB):**
  - Topbar 1 baris konsisten menampilkan info **Provider & Model AI aktif** tepat di sebelah kanan judul, serta auto-overflow **`Menu ▾`** untuk 4 halaman terpisah (**`Scanner`**, **`Dashboard`**, **`Riwayat Scan`**, dan **`Settings & AI`**) plus tautan **`Alur Scan ↗`** (`/flow`).
  - **Daftar Setup Trading** diurutkan default berdasarkan **Perubahan Terbaru (`updated_at`)**, dilengkapi tab **`AKTIF`** (`OPEN + ENTRY_HIT + EXTENDED + MANUAL_TAKEN`) dengan penghitung jumlah per tab, strip **`Perubahan Terbaru`** yang dapat diklik untuk fokus langsung ke setup, serta **Date Range Picker 2 bulan** (default *7 Hari Terakhir*).
  - **Dashboard** & **Riwayat Scan** dilengkapi **Date Range Picker 2 bulan** (default *Bulan Ini*) dengan preset cepat (`Bulan Ini`, `Hari Ini`, `7 Hari Terakhir`, `Sebulan Lalu`, `3 Bulan Lalu`, `Semua Waktu`). Win Rate Dashboard hanya menghitung trade yang **Sudah Entry** (termasuk `CLOSED_MANUAL_TP` & `CLOSED_MANUAL_CL`) dan memisahkan `SL No Entry` serta `TP No Entry`.
  - Chart Candlestick + histogram **Volume** + overlay **EMA 21/50/200** + panel **DSS Bressert (`10 9 5 80 20 60`)** tersinkronisasi, **drag bebas** vertikal/horizontal (`Auto Fit` untuk reset), **zona waktu `Asia/Jakarta` (WIB)** di seluruh chart & UI, **badge LONG/SHORT berwarna** pada judul chart, serta **presisi harga otomatis hingga `10` desimal** untuk koin bernilai kecil (`0.00000xxx`).
  - Mendukung 3 mode visualisasi level: **`Mode Biasa`** (garis horizontal penuh), **`Kotak Setup`** (*view-only* kotak posisi Long/Short langsung dari Entry AI/Manual + SL + TP dengan *hover* R:R), dan **`Mode Gambar`** (gambar 1 kotak posisi kustom otomatis mengikuti arah setup, tombol `Dari Setup`, `Terapkan ke Taken`, dan hapus via tombol / `Delete`).
  - Setiap setup menyimpan riwayat awal **`CREATED`** (acuan awal Entry/SL/TP dari sistem AI), estimasi **lama trade**, serta referensi **`Scan Run #...`** (klik nomor Run ID di tabel, riwayat scan, atau detail untuk membuka popup detail & *settings snapshot*).

---

## 1. Instalasi & Persiapan

### A. Siapkan Database MySQL
Buat database kosong bernama `mexc_scanner` (atau jalankan skrip `init_database.sql`):
```sql
CREATE DATABASE IF NOT EXISTS mexc_scanner CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
> **Catatan:** Saat aplikasi dijalankan, seluruh tabel (`ai_models`, `app_settings`, `strategies`, `scan_runs`, `trade_setups`, `scan_evaluations`), migrasi kolom baru, dan seed data awal otomatis dibuat/diperbarui jika belum ada.

### B. Virtual Environment & Dependencies (Python 3.11+)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### C. Konfigurasi `.env`
Jika belum ada file `.env`, salin dari `.env.example`:
```bash
cp .env.example .env
```
Sesuaikan `DATABASE_URL` pada `.env` sesuai kredensial MySQL Anda:
```env
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/mexc_scanner?charset=utf8mb4
```
*(Pengaturan provider LLM, API key, model aktif, interval scanner, serta strategi disimpan di database MySQL dan diatur melalui Dashboard UI. Jika ISP/jaringan memblokir `contract.mexc.com`, gunakan mirror `https://contract.mexc.fm` atau isi MEXC Proxy URL di menu Settings.)*

---

## 2. Cara Menjalankan Aplikasi

### Mode 1: Dashboard Web + Background Scheduler (Rekomendasi)
Jalankan server FastAPI beserta scheduler scan & outcome tracker otomatis:
```bash
.venv/bin/python main.py
```
Atau dengan auto-reload saat development:
```bash
.venv/bin/python main.py --reload
```
Atau langsung menggunakan `uvicorn`:
```bash
.venv/bin/uvicorn app.web.dashboard:app --host 0.0.0.0 --port 8001
```
Opsi CLI untuk `main.py`:
- `--host` : Bind host server (default dari `APP_HOST`, yaitu `0.0.0.0`)
- `--port` : Port server (default dari `APP_PORT`, yaitu `8001`)
- `--reload` : Aktifkan uvicorn auto-reload

### Mode 2: Jalankan Scan 1x via CLI (Tanpa Web Server)
```bash
# Scan untuk semua strategi aktif di database
.venv/bin/python main.py --scan-once

# Scan top 15 pair hanya untuk strategi tertentu
.venv/bin/python main.py --scan-once --top-n 15 --strategies TREND_PULLBACK BREAKOUT_MOMENTUM
```

---

## 3. URL Akses

Setelah aplikasi berjalan pada port default `8001`:

| Layanan | URL Lokal | Keterangan |
|---|---|---|
| **Scanner & Dashboard UI** | `http://127.0.0.1:8001` | Navigasi halaman terpisah: **`#scanner`** (Setup & Chart), **`#dashboard`** (KPI & Analitik), **`#runs`** (Riwayat Scan), dan **`#settings`** (Pengaturan & AI Models) |
| **Visualisasi Alur Scan** | `http://127.0.0.1:8001/flow` | Halaman terpisah (**`Alur Scan ↗`**): diagram interaktif alur data MEXC → Indikator → Strategi → AI → Risk Guard |
| **Swagger API Docs** | `http://127.0.0.1:8001/docs` | Dokumentasi interaktif seluruh endpoint REST API |
| **Health Check API** | `http://127.0.0.1:8001/api/health` | Status server, provider/model AI aktif, dan status scanner |

---

## 4. Pengaturan di Dashboard, Navigasi Menu, & Manajemen Strategi

### A. Navigasi Menu Utama
- **`Scanner`** *(tampilan default)*: menampilkan **Daftar Setup Trading** (urutan default **Perubahan Terbaru** `updated_at`, **Date Range Picker** default *7 Hari Terakhir*, filter pair/strategi, tab status **`AKTIF`** beserta badge jumlah live di setiap tab, strip **`Perubahan Terbaru`** yang dapat diklik, estimasi **lama trade**, `HTF/LTF`, `Candles`, `Expiry`, dan tombol **`Run #...`**), **Chart Interaktif** (dengan badge LONG/SHORT di judul, `Mode Biasa`, `Kotak Setup`, `Mode Gambar`), serta **Detail Setup** (`Scan Run #...`, *settings snapshot*, dan **Riwayat Kejadian & Status Setup** sejak `CREATED`).
- **`Dashboard`**: dilengkapi **Date Range Picker 2 bulan** di bagian atas (default **Bulan Ini**, dengan sugesti **`Bulan Ini`**, **`Hari Ini`**, **`7 Hari Terakhir`**, **`Sebulan Lalu`**, **`3 Bulan Lalu`**, **`Semua Waktu`**), 4 kartu KPI simetris (**Setup Aktif** = `OPEN + ENTRY_HIT + EXTENDED + MANUAL_TAKEN`, **Win Rate (Sudah Entry)** menampilkan rincian `HIT_TP`/`Closed TP` & `HIT_SL`/`Closed CL`, **Tidak Tersentuh Entry** = `SL No Entry / TP No Entry`, **Total Setup AI & Avg R:R**), grafik per strategi, panel **Rincian Setup Aktif** (plus tombol **`Lihat di Scanner →`**), serta tabel **Ringkasan Performa per Strategi**.
- **`Riwayat Scan`**: halaman terpisah untuk seluruh siklus scan, dilengkapi **Date Range Picker 2 bulan** (default **Bulan Ini** dengan urutan preset yang sama dengan Dashboard), pencarian **Run ID (`#...`)**, filter **Status** (`COMPLETED` / `FAILED` / `RUNNING`), pagination, dan popup **Detail Evaluasi & Snapshot Setting**.
- **`Settings & AI`**: halaman terpisah (bukan popup) berisi tab **AI Provider & Models** serta **Scanner, MEXC & Risk Guard** + **Kelola Strategi**.
- **`Alur Scan ↗`** *(di paling ujung kanan topbar)*: membuka halaman lain `/flow` untuk melihat alur scan dan audit prompt strategi.

### B. Pengaturan Aplikasi (`Settings & AI`)
1. Buka `http://127.0.0.1:8001` di browser, klik tab **`Settings & AI`** di menu atas.
2. Di tab **AI Provider & Models**: pilih provider (**Command Code AI**, **OpenRouter**, atau **Custom**), isi API Key, aktifkan model, lalu klik **Test Connection**.
3. Di tab **Scanner, MEXC & Risk Guard**:
   > **Perubahan Parameter Global → Per-Strategi:** Parameter global **HTF Interval**, **LTF Interval**, **Kline Limit (Candles)**, dan **Setup Expiry (Jam)** telah **dihilangkan dari pengaturan global** karena tiap strategi punya kebutuhan timeframe, panjang candle indikator, dan durasi trade berbeda. Keempatnya kini diatur **per strategi** di tabel **Kelola Strategi & Prompt Aturan AI**.

   **Parameter Global yang Aktif di `app_settings`:**
   - **Mode Scanner & Jadwal:** `Mode Scanner` (`Auto` / `Manual`), `Scan Interval (Menit)`, dan `Tracker Interval (Detik)` *(minimal `15` detik; background tracker berjalan otomatis di backend selama server hidup)*.
   - **Market Scanner & Strategi:** `Top N Pairs` (`1–100`) dan checklist `Active Strategies` (diambil dari tabel `strategies` di MySQL).
   - **MEXC Futures API & LLM Runtime:** `MEXC Base URL`, `MEXC Proxy URL (Opsional)`, `MEXC Concurrency`, `LLM Timeout (s)`, `LLM Concurrency`, dan `LLM Max Tokens` (`512–8192`, mencegah reservasi kredit berlebih di OpenRouter).
   - **Pre-Filter & Risk Guard:** `Min 24h Quote Volume (USDT)`, `Max 24h Quote Volume (USDT)` (`0 = tanpa batas atas`), `Min ATR (%) — Baseline Min15` & `Max ATR (%) — Baseline Min15` *(otomatis diskalakan `√(interval/15m)` per LTF strategi)*, **`Risk Profile (Gaya AI & R:R)`** (`CONSERVATIVE` ketat / `MODERATE` B/C-Grade & R:R `-0.2` / `AGGRESSIVE` taktis & R:R `-0.3`), dan **`Min AI Confidence (%)`** *(gerbang skor minimal yang berlaku langsung di prompt AI dan Risk Guard; otomatis terisi saran `70`/`60`/`55` saat ganti profil namun tetap bebas diubah manual)*.

   **Pengaturan Per-Strategi (Tabel Database `strategies`):**
   - Melalui **Kelola Strategi & Prompt Aturan AI**, Anda dapat menambah strategi baru (`+ Tambah Strategi Baru` atau **Import JSON**), mengubah kode nama (mis. `_SWING`/`_SCALP`), `trade_style`, estimasi **lama trade (`holding_period`)**, `HTF`, `LTF`, `Candles (suggested_kline_limit)`, `Setup Expiry (suggested_expiry_hours)`, `min_rr`, serta `prompt_text`.

### C. Kontrol Chart, Mengelola Setup & Evaluasi
- Klik baris setup di tabel untuk melihat chart Candlestick + Volume + EMA 21/50/200 + **DSS Bressert (`10 9 5 80 20 60`)** dalam waktu **WIB (`Asia/Jakarta`)** dan presisi harga otomatis hingga `10` desimal:
  - **`Mode Biasa`**: drag bebas chart atas/bawah/kiri/kanan + garis horizontal penuh `ENTRY`, `STOP LOSS`, `TAKE PROFIT` (klik **`Auto Fit`** untuk pas-kan ulang skala).
  - **`Kotak Setup`**: tampilan *view-only* kotak posisi Long/Short langsung dari Entry (AI/Manual), SL, dan TP setup (menggantikan garis penuh; arahkan kursor ke kotak untuk melihat **rasio R:R**).
  - **`Mode Gambar`**: klik/drag di chart (atau klik **`↺ Dari Setup`**) untuk membuat 1 kotak posisi yang bisa digeser level Entry/SL/TP-nya (otomatis mengikuti arah LONG/SHORT setup), lalu klik **Terapkan ke Taken** untuk menyalin nilainya ke modal status, atau hapus lewat **`× Hapus (Del)`** / tombol keyboard **`Delete`**.
- Gunakan **Mark Taken**, **Skip**, atau **Edit Status / Close** (untuk ubah status, isi `manual_entry_price`, sesuaikan SL/TP baru, atau tutup manual `CLOSED_MANUAL_TP` / `CLOSED_MANUAL_CL`).
- Klik ikon **`i`** di sebelah *Daftar Setup Trading* untuk melihat Legend status, dan klik **Run ID (`Run #...` / `#...`)** atau **Detail Evaluasi** untuk membuka popup settingan snapshot scan & evaluasi tiap pair.

### Cara Kerja Outcome Tracker & Daftar 10 Status Setup
Background tracker ([app/core/tracker.py](app/core/tracker.py)) berjalan otomatis setiap `tracker_interval_seconds` (default `60` detik, minimum `15` detik; tetap berjalan walau mode Auto Scan diset ke Manual), dan bisa dijalankan kapan saja lewat tombol **Check Outcomes** (`POST /api/tracker/run`).

- **Mekanisme Pengecekan Otomatis:** Tracker mengevaluasi seluruh setup berstatus `OPEN`, `ENTRY_HIT`, `EXTENDED`, dan `MANUAL_TAKEN` menggunakan candle historis adaptif (`Min1` / `Min5` / `Min15`) sejak waktu dibuat (atau sejak waktu `MANUAL_TAKEN`, `EXTENDED`, maupun `RESET_OPEN` untuk setup yang direaktivasi) plus harga ticker live (`lastPrice`):
  - Order `LIMIT` menunggu harga menyentuh `entry_price` (`low <= entry` untuk `LONG`, `high >= entry` untuk `SHORT`) → bila masih berstatus `OPEN` dan belum menyentuh `TP`/`SL`, berubah menjadi `ENTRY_HIT`. Order `MARKET` otomatis dianggap tersentuh sejak awal.
  - Setup berstatus **`EXTENDED`** tetap mempertahankan status `EXTENDED`-nya (tidak ditimpa menjadi `ENTRY_HIT` saat Entry tersentuh — `entry_hit_at` tetap dicatat + badge `ENTRY` tampil, dan tetap dipantau sampai `HIT_TP`, `HIT_SL`, atau melewati `expires_at` baru).
  - Jika `SL` dan `TP` tersentuh dalam 1 candle yang sama, **`HIT_SL` diprioritaskan**.
  - Jika melewati `expires_at` (diatur per strategi lewat `suggested_expiry_hours`) tanpa menyentuh `TP`/`SL` → berubah menjadi `EXPIRED`.
  - Setup yang akan/sudah `EXPIRED` dapat diperpanjang menggunakan status **`EXTENDED`** (memprioritaskan nilai `expiry_hours` dari **snapshot `ScanRun`** saat scan dijalankan, lalu fallback ke `suggested_expiry_hours` di tabel `strategies`, atau `12` jam; seluruh perubahan tercatat lengkap di `status_history`).

| Status | Tab di UI | Dipantau Tracker? | Pengaruh di Analytics | Keterangan |
|---|---|---|---|---|
| `OPEN` | `AKTIF` / `OPEN` | ✅ Ya | `Setup Aktif` | Setup valid baru yang menunggu harga menyentuh `Entry`, `TP`, `SL`, atau `EXPIRED`. |
| `ENTRY_HIT` | `AKTIF` / `ENTRY_HIT` | ✅ Ya | `Setup Aktif` | Otomatis dari Tracker: harga sudah menyentuh level `Entry` dan sedang berjalan menuju `TP`/`SL`. |
| `EXTENDED` | `AKTIF` / `EXTENDED` | ✅ Ya | `Setup Aktif` | Perpanjangan manual batas `expires_at` mengikuti snapshot strategi saat scan run (atau jam kustom); tetap dipantau Tracker dan tidak tertimpa balik ke `ENTRY_HIT`. |
| `HIT_TP` | `HIT_TP` | ❌ Final | **Win (Executed)** | Otomatis dari Tracker: harga menyentuh `Take Profit` terlebih dahulu setelah `Entry` tersentuh. |
| `HIT_SL` | `HIT_SL` | ❌ Final | **Loss (Executed)** / `SL No Entry` | Hanya dihitung **Loss** pada Win Rate jika sudah pernah Entry (`ENTRY_HIT`/`MANUAL_TAKEN`/`MARKET`); jika belum pernah Entry dicatat sebagai **`SL No Entry`**. |
| `EXPIRED` | `EXPIRED` | ❌ Final | `Expired` | Otomatis dari Tracker: melewati `expires_at` sebelum mengenai `TP` maupun `SL`. |
| `MANUAL_TAKEN` | `AKTIF` / `TAKEN` | ✅ Ya | `Setup Aktif` & `Taken` | Ditandai manual oleh user sudah dieksekusi di MEXC (bisa isi `manual_entry_price`); tetap dipantau Tracker sampai `TP`/`SL`/`EXPIRED`. |
| `MANUAL_SKIPPED` | `SKIPPED` | ❌ Final | `Skipped` | Ditandai manual (*Skip*) bahwa setup ini dilewati dan tidak dieksekusi. |
| `CLOSED_MANUAL_TP` | `CLOSED_TP` | ❌ Final | **Win (Executed)** | Ditutup manual oleh user sebagai profit (*Close TP*, dengan harga close tercatat; masuk hitungan Win Rate). |
| `CLOSED_MANUAL_CL` | `CLOSED_CL` | ❌ Final | **Loss (Executed)** | Ditutup manual oleh user sebagai *Cut Loss* (*Close CL*, dengan harga close tercatat; masuk hitungan Loss di Win Rate). |

- **Badge Riwayat & Penelitian Eksekusi AI (Tampil Otomatis Bersandingan dengan Status Utama):**
  - **`ENTRY`** *(hijau-biru)*: harga sempat menyentuh level `Entry` (`entry_hit_at`) sebelum menyentuh `TP`/`SL`.
  - **`NO ENTRY`** *(peringatan kuning)*: muncul di samping `HIT_SL` jika harga langsung menjebol `SL` sebelum sempat menjemput Limit Entry.
  - **`TP NO ENTRY`** *(hijau putus-putus)*: harga sudah menembus `TP` duluan (`missed_tp_at`, `missed_tp_price`) sebelum menyentuh Limit Entry — menandakan analisa arah AI benar, hanya level limit terlalu dalam.
  - **`TAKEN`** *(ungu)*: setup sempat ditandai `MANUAL_TAKEN` oleh user (bisa juga dipakai pada setup yang sudah `HIT_SL` atau `EXPIRED` dengan mengisi **Harga Entry Aktual**, **SL Baru**, & **TP Baru** di modal Edit Status untuk dipantau ulang oleh Tracker).

---

## 5. Daftar Strategi Bawaan & Isi Prompt Aturannya

Ketiga strategi berikut otomatis di-seed ke tabel MySQL `strategies` dari folder `prompts/` saat startup pertama, dan dapat langsung diedit, diganti namanya (mis. `_SWING`/`_SCALP`), atau dinonaktifkan lewat Dashboard UI:

### 1) `TREND_PULLBACK` (`INTRADAY` • Estimasi: 4–24 Jam • HTF `Min60` / LTF `Min15` • Min R:R `1.8`)
Sumber awal: [prompts/trend_pullback.txt](prompts/trend_pullback.txt)
```text
Anda adalah analis kuantitatif Crypto Futures profesional yang sangat disiplin pada manajemen risiko.
Strategi Anda saat ini adalah: TREND_PULLBACK (Intraday Trend Following & Pullback ke EMA / Flip Zone).

ATURAN EVALUASI KETAT:
1. Evaluasi tren Higher Timeframe (HTF sesuai field `interval` di `htf_1h`) terlebih dahulu:
   - Tentukan bias tren dari `ema_bias` (`BULLISH_ALIGNED` / `BEARISH_ALIGNED` / `MIXED`), posisi harga terhadap EMA 50 & EMA 200, serta struktur swing (`recent_swing_high` / `recent_swing_low`).
   - Kondisi `BULLISH_ALIGNED` / `BEARISH_ALIGNED` bernilai konfluensi tinggi (A-Grade). Kondisi `MIXED` tetap bisa dipertimbangkan (B-Grade) selama harga tegas di atas EMA 50/200 (LONG) atau di bawah EMA 50/200 (SHORT). Hanya wajib `NO_TRADE` bila HTF sangat choppy (`FLAT_RANGING` datar berimpit tanpa arah jelas).
2. Cari pullback sehat di Lower Timeframe (LTF sesuai field `interval` di `ltf_15m`):
   - Tunggu harga melakukan pullback terkendali ke area EMA 21 / EMA 50 LTF atau area support/resistance flip zone yang searah dengan tren HTF.
   - Konfluensi tambahan (menaikkan confidence ke 80+): candle rejection/rebound searah tren di `recent_candles`, DSS Bressert (`dss_cross_up` / `dss_cross_down` dari area jenuh), dan RSI 14 sehat (tidak overextended jauh dari EMA 21).
3. Penentuan Level Eksekusi (LONG atau SHORT):
   - Entry Price: harga limit di area pullback/flip zone atau market jika konfirmasi candle baru saja selesai di zona pullback.
   - Stop Loss: letakkan di balik recent swing low (untuk LONG) atau recent swing high (untuk SHORT) ditambah buffer ATR 14 LTF sekitar 0.3x hingga 0.5x ATR.
   - Take Profit: targetkan tepat sebelum resistance mayor berikutnya (untuk LONG) atau sebelum support mayor berikutnya (untuk SHORT).
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.8. Jika struktur level tidak memberi ruang R:R >= 1.8, wajib NO_TRADE.
4. Disiplin NO_TRADE & Skala Confidence Objektif:
   - Gunakan skala objektif: `80–95` (A-Grade: HTF aligned kuat + pullback tepat + rejection/volume/DSS mendukung), `70–79` (B-Grade: tren & pullback + R:R valid namun 1 faktor tambahan kurang sempurna), `< 70` (lemah/konflik -> wajib `NO_TRADE`).
   - Kembalikan decision="NO_TRADE", entry_type="NONE", serta entry_price=null, stop_loss=null, take_profit=null, risk_reward_ratio=null jika:
     * Terjadi konflik langsung antara arah tren HTF dan struktur LTF.
     * Harga sudah terlalu jauh extended dari EMA 21 sehingga R:R < 1.8.
     * Struktur terlalu choppy / confidence objektif < 70.
5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.
   - strategy_used harus persis "TREND_PULLBACK".
```

### 2) `BREAKOUT_MOMENTUM` (`INTRADAY_SWING` • Estimasi: 4–48 Jam • HTF `Min60` / LTF `Min15` • Min R:R `2.0`)
Sumber awal: [prompts/breakout_momentum.txt](prompts/breakout_momentum.txt)
```text
Anda adalah analis kuantitatif Crypto Futures profesional yang spesialis membaca ekspansi volatilitas dan volume.
Strategi Anda saat ini adalah: BREAKOUT_MOMENTUM (Breakout Konsolidasi dengan Konfirmasi Volume >= 1.5x).

ATURAN EVALUASI KETAT:
1. Deteksi Kompresi & Level Kunci:
   - Cari kondisi konsolidasi/harga yang mendekati resistance kunci (untuk potensi LONG) atau support kunci (untuk potensi SHORT) pada HTF dan LTF (sesuai field `interval`). Kompresi ketat (`compression_ratio` rendah) menjadi bonus konfluensi kuat.
   - Perhatikan konteks derivatives: funding_rate yang tidak ekstrem berlawanan secara crowding dan open_interest (hold_vol) yang sehat mendukung kelanjutan ekspansi.
2. Syarat Konfirmasi Breakout (Wajib vs Konfluensi):
   - Syarat Wajib: Harus ada close candle tegas di luar level resistance/support kunci (bukan sekadar jarum/wick palsu), serta Volume Ratio LTF >= 1.2x (bila < 1.2x anggap lemah -> NO_TRADE).
   - Konfluensi A-Grade (confidence 80+): `volume_ratio >= 1.5`, RSI 14 sehat (tidak > 82 LONG atau < 18 SHORT), serta body candle dominan tanpa wick penolakan besar.
   - Setup B-Grade (confidence 70–79): Breakout valid dengan `volume_ratio` antara `1.20–1.49` atau retest dangkal di level yang ditembus selama R:R tetap >= 2.0.
3. Penentuan Level Eksekusi:
   - Entry Price: di area penutupan breakout atau retest dangkal batas level yang ditembus.
   - Stop Loss: di dalam area range konsolidasi / di balik level breakout dengan buffer ATR (sekitar 0.4x–0.6x ATR) agar aman dari noise.
   - Take Profit: berdasarkan proyeksi lebar range konsolidasi atau area likuiditas / resistance-support mayor berikutnya.
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 2.0. Jika tidak mencapai 2.0 secara realistis, wajib NO_TRADE.
4. Disiplin NO_TRADE:
   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika volume_ratio < 1.2, terlihat fakeout/wick penolakan besar, struktur tidak jelas, konflik HTF ekstrem, atau confidence objektif < 70.
5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.
   - strategy_used harus persis "BREAKOUT_MOMENTUM".
```

### 3) `MEAN_REVERSION_SCALP` (`SCALP` • Estimasi: 1–6 Jam • HTF `Min30` / LTF `Min5` • Min R:R `1.5`)
Sumber awal: [prompts/mean_reversion_scalp.txt](prompts/mean_reversion_scalp.txt)
```text
Anda adalah analis kuantitatif Crypto Futures profesional yang berfokus pada perdagangan range dan ekstrem momentum.
Strategi Anda saat ini adalah: MEAN_REVERSION_SCALP (Pantulan Support/Resistance saat Kondisi Ranging).

ATURAN EVALUASI KETAT:
1. Syarat Kondisi Pasar (Range / Non-Trending Kuat):
   - Strategi ini optimal saat `market_regime` adalah `"RANGING"` (`FLAT_RANGING` atau `MIXED` dengan range jelas dan harga memantul di antara batas S/R).
   - Jika pasar sedang trending searah sangat kuat atau `HIGH_VOLATILITY_CHOP` liar tanpa batas range jelas, wajib pilih NO_TRADE.
2. Syarat Sinyal Pantulan:
   - LONG: Harga berada di dekat `nearest_support` / lower range dengan tanda perlambatan jual (rejection wick bawah / `swept_prior_low = true`, candle berbalik bullish) DAN RSI 14 / DSS LTF (`dss_cross_up = true`) mulai jenuh jual (ekstrem `< 30` bernilai A-Grade 80+; atau `30–38` yang mulai berbalik naik `rsi14 > prev_rsi14` untuk B-Grade 70–79).
   - SHORT: Harga berada di dekat `nearest_resistance` / upper range dengan tanda perlambatan beli (rejection wick atas / `swept_prior_high = true`, candle berbalik bearish) DAN RSI 14 / DSS LTF (`dss_cross_down = true`) mulai jenuh beli (ekstrem `> 70` bernilai A-Grade 80+; atau `62–70` yang mulai berbalik turun `rsi14 < prev_rsi14` untuk B-Grade 70–79).
3. Penentuan Level Eksekusi:
   - Entry Price: di area pantulan support/resistance saat ini.
   - Stop Loss: letakkan ketat di luar batas range (sekitar 0.5x–0.8x ATR 14 LTF di luar swing support/resistance).
   - Take Profit: target konservatif ke area mid-range (EMA 21/50) atau sisi range yang berlawanan.
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.5.
4. Disiplin NO_TRADE:
   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika market sedang trending kuat melawan arah, belum ada tanda pantulan/pembalikan RSI maupun wick di batas S/R, terdapat breakdown/breakout bervolume besar (`volume_ratio >= 1.8`), atau confidence objektif < 70.
5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.
   - strategy_used harus persis "MEAN_REVERSION_SCALP".
```

---

## 6. Template Prompt Generator untuk Membuat Strategi Baru

Jika Anda ingin meminta AI (ChatGPT / Claude / Gemini) merancang strategi baru agar formatnya **100% kompatibel** dengan tabel `strategies` dan form UI aplikasi ini (termasuk setting per strategi `HTF`/`LTF`/`Candles`/`Expiry`/Lama Trade dan indikator yang tersedia di `MARKET SNAPSHOT`), gunakan template prompt berikut dan ganti bagian `[IDE STRATEGI ANDA]`:

```text
Buatkan definisi strategi trading Crypto Futures baru untuk sistem "MEXC AI Setup Scanner" saya berdasarkan ide berikut:
[IDE STRATEGI ANDA, misal: Swing Trend Pullback di timeframe 4H/1H dengan target 2-5 hari]

Kembalikan output HANYA 1 blok JSON valid (tanpa teks tambahan di luar JSON) persis seperti format berikut:
{
  "name": "KODE_STRATEGI_HURUF_BESAR_PAKAI_UNDERSCORE",
  "display_name": "Nama Tampilan Strategi",
  "description": "Ringkasan singkat strategi (maks 200 karakter)",
  "trade_style": "PILIH SALAH SATU: SCALP | INTRADAY | INTRADAY_SWING | SWING | POSITION",
  "holding_period": "Estimasi lama trade (mis: 1 - 6 Jam / 4 - 24 Jam / 2 - 7 Hari / 1 - 4 Minggu)",
  "suggested_htf": "PILIH SALAH SATU: Min30 | Min60 | Hour4 | Day1",
  "suggested_ltf": "PILIH SALAH SATU: Min5 | Min15 | Min30 | Min60",
  "suggested_kline_limit": 250,
  "suggested_expiry_hours": 24,
  "min_rr": 2.0,
  "is_active": true,
  "prompt_text": "Tulis teks system prompt lengkap berbahasa Indonesia..."
}

ATURAN WAJIB UNTUK ISI "prompt_text":
1. Hanya gunakan data indikator yang benar-benar ada di MARKET SNAPSHOT sistem saya:
   - market_ticker: last_price, fair_price, index_price, change_24h_pct, quote_volume_24h, funding_rate, funding_rate_pct, funding_extreme, open_interest_hold_vol, open_interest_usdt, oi_to_volume_ratio, high_24h, low_24h. *(Catatan: tidak ada feed likuidasi terpisah; gunakan funding_rate + open_interest_usdt sebagai proksi squeeze/crowding).*
   - htf_1h (container Higher Timeframe sesuai field "interval") & ltf_15m (container Lower Timeframe sesuai field "interval"): interval, bars_count, close, ema21, ema50, ema200, ema_bias (BULLISH_ALIGNED / BEARISH_ALIGNED / FLAT_RANGING / MIXED), ema21_slope_pct, ema50_slope_pct, dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct, rsi14, prev_rsi14, dss, prev_dss, dss_signal, prev_dss_signal, dss_cross_up, dss_cross_down, atr14, atr_pct, vol_ma20, current_volume, volume_ratio, compression_ratio, recent_swing_high, recent_swing_low, prior_swing_high, prior_swing_low, swept_prior_high, swept_prior_low, structure_bias (HH_HL / LH_LL / MIXED_RANGE), nearest_support, nearest_resistance, support_is_fallback, resistance_is_fallback, dist_to_support_pct, dist_to_resistance_pct, recent_candles, compact_candles_15.
   - level_candidates (kandidat SL/TP & R:R terhitung) dan market_context.btc (bias BTC HTF/LTF).
2. Buat aturan evaluasi bernomor yang jelas: pisahkan syarat WAJIB (struktur tren HTF, pemicu utama LTF, level Entry/SL berbasis swing + buffer ATR, TP ke S/R berikutnya, dan minimum R:R sesuai field "min_rr") dari faktor konfluensi BONUS yang menentukan skor confidence (80-95 untuk A-Grade ideal, 70-79 untuk B-Grade solid layak eksekusi).
3. Sertakan aturan disiplin NO_TRADE jika struktur utama lemah, HTF/LTF berkonflik langsung, R:R kurang dari minimum, atau confidence objektif < 70 sebagai baseline standar (jangan mengunci larangan mutlak yang menolak penyesuaian **Risk Profile** `MODERATE`/`AGGRESSIVE` & **Min AI Confidence (%)** dari sistem saat runtime, dan jangan mem-hardcode angka batas filter Risk Guard).
4. Akhiri "prompt_text" dengan instruksi wajib:
   - Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.
   - market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".
   - decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".
   - entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".
   - strategy_used HARUS persis sama dengan nilai field "name".
```

---

## 7. Cleansing / Reset Data Scan & Setup

Untuk memulai ulang pencatatan scan & setup dari awal (`Run #1` / `Setup #1`) **tanpa** menghapus pengaturan aplikasi (`app_settings`), daftar model AI (`ai_models`), maupun strategi & prompt (`strategies`), pastikan tidak ada scan yang sedang berjalan lalu jalankan query MySQL berikut:

```sql
USE mexc_scanner;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE scan_evaluations;
TRUNCATE TABLE trade_setups;
TRUNCATE TABLE scan_runs;
SET FOREIGN_KEY_CHECKS = 1;
```

---

## 8. Menjalankan Pengujian

```bash
.venv/bin/python -m pytest -v
```
