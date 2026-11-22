# MEXC AI Setup Scanner

Aplikasi lokal berbasis Python untuk memindai peluang trading **Crypto Futures di MEXC** (menggunakan **public market data only**, tanpa MEXC API key dan tanpa auto-order), menghitung indikator teknikal secara deterministik, mengevaluasi setup menggunakan LLM berformat JSON tervalidasi, menyimpannya ke database **MySQL**, melacak outcome secara berkala, serta menampilkan dashboard lokal lengkap dengan **Candlestick Chart, Volume, & DSS Bressert** untuk eksekusi manual.

---

## Fitur Utama

- **Public Market Data Only:** Mengambil kontrak USDT-M aktif, ticker 24 jam (`lastPrice`, `fairPrice`, `indexPrice`, `fundingRate`, `holdVol`, dll.), dan candlestick multi-timeframe (`HTF` & `LTF`) dari `https://contract.mexc.com/api/v1/contract/...`. *(Catatan: MEXC public REST tidak menyediakan feed likuidasi; crowding/potensi squeeze dievaluasi dari `funding_rate` + `open_interest_hold_vol`.)*
- **Deterministic Feature Builder:** Menghitung EMA 21, EMA 50, EMA 200, RSI 14, `prev_rsi14`, ATR 14, Volume MA20 & volume ratio, compression ratio, **DSS Bressert (`10 9 5`, meliputi `dss`, `prev_dss`, `dss_signal`)**, ringkasan 3 candle terakhir (`recent_candles`: `open`, `high`, `low`, `close`, `volume`, `is_bullish`, `direction`, `body_pct`, `upper_wick_pct`, `lower_wick_pct`), serta deteksi `recent_swing_high`, `recent_swing_low`, `nearest_support`, dan `nearest_resistance`.
- **Per-Strategy Timeframe, Candles & Expiry:** Setiap strategi aktif (baik 1 maupun multi-strategi) otomatis memakai `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, dan `suggested_expiry_hours` masing-masing dari tabel `strategies` (penarikan kline MEXC terdeduplikasi per `(symbol, interval)` agar hemat request). Setting global hanya mengatur **Mode Auto/Manual**, **Scan/Tracker Interval**, **Top N Pairs**, filter **Volume/ATR%/Confidence**, serta runtime **MEXC/LLM**.
- **Strategy Registry di MySQL (`strategies`):**
  - Menyimpan nama/kode strategi (bisa diedit mis. akhiran `_SWING`, `_INTRADAY`, `_SCALP`), tipe trading (`trade_style`), estimasi lama trade (`holding_period`), konfigurasi scan per strategi (`suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, `suggested_expiry_hours`), minimum R:R (`min_rr`), toggle aktif/nonaktif (`is_active`), dan isi `prompt_text`.
  - Bawaan awal (auto-seeded dari `prompts/*.txt`):
    - `TREND_PULLBACK` (`INTRADAY`, 4–24 Jam, HTF `Min60` / LTF `Min15`, min R:R `1.8`)
    - `BREAKOUT_MOMENTUM` (`INTRADAY_SWING`, 4–48 Jam, HTF `Min60` / LTF `Min15`, min R:R `2.0`)
    - `MEAN_REVERSION_SCALP` (`SCALP`, 1–6 Jam, HTF `Min30` / LTF `Min5`, min R:R `1.5`)
- **Deterministic Risk & Math Guard:** Menolak confidence di bawah threshold (`min_confidence`), memvalidasi geometri harga `LONG`/`SHORT`, menghitung ulang R:R secara matematis terhadap `min_rr` strategi terkait di database, dan mencegah duplikasi setup aktif (`OPEN`, `ENTRY_HIT`, `MANUAL_TAKEN`) untuk pair & arah yang sama.
- **Outcome Tracker Adaptif & Manajemen Status Lengkap:**
  - Mendukung 9 status: `OPEN`, `ENTRY_HIT`, `MANUAL_TAKEN`, `MANUAL_SKIPPED`, `HIT_TP`, `HIT_SL`, `EXPIRED`, `CLOSED_MANUAL_TP`, `CLOSED_MANUAL_CL`.
  - Tracker menggunakan interval adaptif (`Min1` / `Min5` / `Min15`) dan live ticker `lastPrice` sehingga perubahan Entry, SL, dan TP pada posisi `LONG` maupun `SHORT` tetap akurat bahkan saat harga bergerak cepat antar siklus cek (min 15 detik).
- **Audit Snapshot Setting per Scan Run (`scan_runs.settings_snapshot`):** Setiap eksekusi scan merekam snapshot lengkap strategi beserta `strategy_timeframes` (`HTF/LTF`, `kline_limit`, `expiry_hours` tiap strategi), filter ATR/volume, dan konfigurasi AI yang dipakai untuk diaudit di modal **Detail Evaluasi**.
- **Dashboard & Chart TradingView Lightweight Charts:** Menampilkan Candlestick, histogram **Volume**, overlay **EMA 21/50/200**, panel **DSS Bressert (`10 9 5 80 20 60`)** tersinkronisasi, garis **Entry / SL / TP**, modal edit status/close manual, legend status, dan analitik performa per strategi.

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
| **Dashboard Web UI** | `http://127.0.0.1:8001` | Tabel setup, chart Candlestick/Volume/DSS Bressert, analitik, & pengaturan |
| **Visualisasi Alur Scan** | `http://127.0.0.1:8001/flow` | Diagram interaktif alur data MEXC → Indikator → Strategi → AI → Risk Guard |
| **Swagger API Docs** | `http://127.0.0.1:8001/docs` | Dokumentasi interaktif seluruh endpoint REST API |
| **Health Check API** | `http://127.0.0.1:8001/api/health` | Status server, provider/model AI aktif, dan status scanner |

---

## 4. Pengaturan di Dashboard & Manajemen Strategi

1. Buka `http://127.0.0.1:8001` di browser, klik **Settings & AI Models**.
2. Di tab **AI Provider & Models**: pilih provider (**Command Code AI**, **OpenRouter**, atau **Custom**), isi API Key, aktifkan model, lalu klik **Test Connection**.
3. Di tab **Scanner, MEXC & Risk Guard**:
   - Atur parameter global seperti **Mode Scanner (Auto/Manual)**, **Scan Interval**, **Tracker Interval**, **Top N Pairs**, serta **Pre-Filter & Risk Guard** (termasuk **Min/Max 24h Quote Volume** berformat pemisah ribuan untuk memfilter mega-cap atau membidik altcoin).
   - Centang strategi pada **Active Strategies** lalu klik **Simpan Semua Pengaturan Scanner**. Timeframe (`HTF/LTF`), `Kline Limit`, dan `Setup Expiry` selalu mengikuti konfigurasi masing-masing strategi yang aktif.
   - Di bagian **Kelola Strategi & Prompt Aturan AI (Tabel Database)**, Anda dapat menambah strategi baru (`+ Tambah Strategi Baru` secara manual atau melalui **Upload File JSON** hasil generator prompt), mengedit kode nama (mis. `_SWING`/`_SCALP`), prompt aturan, `min_rr`, serta mengatur `HTF`, `LTF`, `Candles`, `Expiry`, dan lama trade langsung pada tiap strategi.

### Mengelola Setup & Evaluasi
- Klik baris setup untuk melihat chart Candlestick + Volume + EMA 21/50/200 + **DSS Bressert (`10 9 5 80 20 60`)**.
- Gunakan **Mark Taken**, **Skip**, atau **Edit Status / Close** (untuk ubah status, isi `manual_entry_price`, atau tutup manual `CLOSED_MANUAL_TP` / `CLOSED_MANUAL_CL`).
- Klik ikon **`i`** di sebelah *Daftar Setup Trading* untuk melihat keterangan seluruh status, dan klik **Detail Evaluasi** di *Riwayat Scan* untuk melihat settingan snapshot scan serta hasil evaluasi setiap pair.

---

## 5. Daftar Strategi Bawaan & Isi Prompt Aturannya

Ketiga strategi berikut otomatis di-seed ke tabel MySQL `strategies` dari folder `prompts/` saat startup pertama, dan dapat langsung diedit, diganti namanya (mis. `_SWING`/`_SCALP`), atau dinonaktifkan lewat Dashboard UI:

### 1) `TREND_PULLBACK` (`INTRADAY` • Estimasi: 4–24 Jam • HTF `Min60` / LTF `Min15` • Min R:R `1.8`)
Sumber awal: [prompts/trend_pullback.txt](prompts/trend_pullback.txt)
```text
Anda adalah analis kuantitatif Crypto Futures profesional yang sangat disiplin pada manajemen risiko.
Strategi Anda saat ini adalah: TREND_PULLBACK (Intraday Trend Following & Pullback ke EMA / Flip Zone).

ATURAN EVALUASI KETAT:
1. Evaluasi tren Higher Timeframe (HTF 1H / Min60) terlebih dahulu:
   - Tentukan bias tren dari posisi harga terhadap EMA 50 dan EMA 200, keselarasan EMA 21 > EMA 50 > EMA 200 (uptrend) atau EMA 21 < EMA 50 < EMA 200 (downtrend), serta struktur swing (Higher High/Higher Low atau Lower High/Lower Low).
   - Jika HTF sideways/choppy atau EMA 50 & EMA 200 datar saling silang tanpa struktur jelas, wajib pilih NO_TRADE.
2. Cari pullback sehat di Lower Timeframe (LTF 15m / Min15):
   - Tunggu harga melakukan pullback terkendali ke area EMA 21 / EMA 50 LTF atau area support/resistance flip zone yang searah dengan tren HTF.
   - Konfirmasi tanda kelanjutan tren dari candlestick (rejection wick searah tren, body candle solid) dan RSI 14 sehat (tidak entry saat RSI sudah ekstrem jenuh searah tren; jangan FOMO mengejar harga yang sudah jauh dari EMA 21).
3. Penentuan Level Eksekusi (LONG atau SHORT):
   - Entry Price: harga limit di area pullback/flip zone atau market jika konfirmasi candle baru saja selesai di zona pullback.
   - Stop Loss: letakkan di balik recent swing low (untuk LONG) atau recent swing high (untuk SHORT) ditambah buffer ATR 14 LTF sekitar 0.3x hingga 0.5x ATR.
   - Take Profit: targetkan tepat sebelum resistance mayor berikutnya (untuk LONG) atau sebelum support mayor berikutnya (untuk SHORT).
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.8. Jika struktur level tidak memberi ruang R:R >= 1.8, wajib NO_TRADE.
4. Disiplin NO_TRADE:
   - Kembalikan decision="NO_TRADE", entry_type="NONE", serta entry_price=null, stop_loss=null, take_profit=null, risk_reward_ratio=null jika:
     * Terjadi konflik antara tren HTF dan struktur LTF.
     * Harga sudah terlalu jauh extended dari EMA 21 (risiko chase/FOMO).
     * Confidence Anda di bawah 75.
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
   - Cari kondisi konsolidasi/kompresi harga yang rapat di dekat resistance kunci (untuk potensi LONG) atau support kunci (untuk potensi SHORT) pada HTF (1H) dan LTF (15m).
   - Perhatikan konteks derivatives: funding_rate yang tidak ekstrem berlawanan secara crowding dan open_interest (hold_vol) yang sehat mendukung kelanjutan ekspansi.
2. Syarat Wajib Konfirmasi Breakout:
   - Harus ada close candle tegas di luar level resistance/support kunci (bukan sekadar jarum/wick palsu).
   - Volume Ratio LTF wajib >= 1.5x dari Volume MA20. Jika volume_ratio < 1.5, JANGAN ambil breakout (wajib NO_TRADE).
   - RSI 14 harus mendukung momentum namun masih sehat (hindari entry jika RSI sudah overbought ekstrem > 80 untuk LONG atau oversold ekstrem < 20 untuk SHORT, serta hindari candle dengan wick penolakan besar melawan arah breakout).
3. Penentuan Level Eksekusi:
   - Entry Price: di area penutupan breakout atau retest dangkal batas level yang ditembus.
   - Stop Loss: di dalam area range konsolidasi / di balik level breakout dengan buffer ATR (sekitar 0.4x–0.6x ATR) agar aman dari noise.
   - Take Profit: berdasarkan proyeksi lebar range konsolidasi atau area likuiditas / resistance-support mayor berikutnya.
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 2.0. Jika tidak mencapai 2.0 secara realistis, wajib NO_TRADE.
4. Disiplin NO_TRADE:
   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika volume_ratio < 1.5, terlihat fakeout/wick penolakan besar, struktur tidak jelas, konflik timeframe, atau confidence < 75.
5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.
   - strategy_used harus persis "BREAKOUT_MOMENTUM".
```

### 3) `MEAN_REVERSION_SCALP` (`SCALP` • Estimasi: 1–6 Jam • HTF `Min30` / LTF `Min5` • Min R:R `1.5`)
Sumber awal: [prompts/mean_reversion_scalp.txt](prompts/mean_reversion_scalp.txt)
```text
Anda adalah analis kuantitatif Crypto Futures profesional yang berfokus pada perdagangan range dan ekstrem momentum.
Strategi Anda saat ini adalah: MEAN_REVERSION_SCALP (Pantulan Support/Resistance saat Kondisi Ranging).

ATURAN EVALUASI KETAT:
1. Syarat Wajib Kondisi Pasar (RANGING Only):
   - Strategi ini HANYA boleh aktif jika market_regime adalah "RANGING" (HTF & LTF tidak sedang trending kuat searah, EMA 21/50 relatif datar/berdekatan dan harga memantul di antara batas range yang jelas).
   - Jika pasar sedang TRENDING_UP, TRENDING_DOWN, atau HIGH_VOLATILITY_CHOP ekstrem, wajib pilih NO_TRADE.
2. Syarat Sinyal Pantulan:
   - LONG: Harga berada di dekat nearest_support / lower range dengan tanda pelemahan tekanan jual (rejection wick bawah, candle berbalik positif) DAN RSI 14 LTF berada di area oversold (< 30) atau baru berbalik naik dari bawah 30.
   - SHORT: Harga berada di dekat nearest_resistance / upper range dengan tanda pelemahan tekanan beli (rejection wick atas, candle berbalik negatif) DAN RSI 14 LTF berada di area overbought (> 70) atau baru berbalik turun dari atas 70.
3. Penentuan Level Eksekusi:
   - Entry Price: di area pantulan support/resistance saat ini.
   - Stop Loss: letakkan ketat di luar batas range (sekitar 0.5x–0.8x ATR 14 LTF di luar swing support/resistance).
   - Take Profit: target konservatif ke area mid-range (EMA 21/50) atau sisi range yang berlawanan.
   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.5.
4. Disiplin NO_TRADE:
   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika market bukan RANGING, RSI belum masuk area ekstrem yang terkonfirmasi berbalik, terdapat ancaman breakdown/breakout bervolume besar, atau confidence < 75.
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
   - market_ticker: last_price, fair_price, index_price, change_24h_pct, quote_volume_24h, funding_rate, open_interest_hold_vol, high_24h, low_24h. *(Catatan: tidak ada feed likuidasi terpisah; gunakan funding_rate + open_interest_hold_vol sebagai proksi squeeze/crowding).*
   - htf_1h (container Higher Timeframe sesuai field "interval") & ltf_15m (container Lower Timeframe sesuai field "interval"): interval, bars_count, close, ema21, ema50, ema200, ema_bias (BULLISH_ALIGNED / BEARISH_ALIGNED / FLAT_RANGING / MIXED), dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct, rsi14, prev_rsi14, dss, prev_dss, dss_signal, atr14, atr_pct, vol_ma20, current_volume, volume_ratio, compression_ratio, recent_swing_high, recent_swing_low, nearest_support, nearest_resistance, dist_to_support_pct, dist_to_resistance_pct, recent_candles (open, high, low, close, volume, is_bullish, direction, body_pct, upper_wick_pct, lower_wick_pct).
2. Buat aturan evaluasi bernomor yang ketat: kondisi tren HTF, syarat pemicu di LTF, aturan penentuan Entry, Stop Loss (menggunakan struktur swing + buffer ATR), Take Profit (resistance/support atau proyeksi range), dan syarat minimum R:R sesuai field "min_rr".
3. Sertakan aturan disiplin NO_TRADE jika struktur lemah, HTF/LTF konflik, R:R kurang dari minimum, atau confidence < 75.
4. Akhiri "prompt_text" dengan instruksi wajib:
   - Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.
   - market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".
   - decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".
   - entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".
   - strategy_used HARUS persis sama dengan nilai field "name".
```

---

## 7. Menjalankan Pengujian

```bash
.venv/bin/python -m pytest -v
```
