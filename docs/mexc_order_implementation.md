# Rencana Implementasi Action Order via MEXC Futures API

Dokumen ini merangkum gambaran alur, persiapan teknis, rancangan arsitektur, dan checklist pengamanan untuk fitur **eksekusi order langsung ke MEXC Futures** dari Trade Setup di **MEXC AI Setup Scanner**.

---

## 1. Tujuan & Konsep Action Order

Menambahkan tombol aksi langsung pada setiap setup yang aktif agar eksekusi order tidak perlu input manual di aplikasi MEXC:

- **Status `OPEN` (harga belum menyentuh Entry)** → Tombol **`Limit Order MEXC`**
  - Memasang **Limit Order** pada `entry_price` setup (atau `manual_entry_price` jika ada) beserta `stopLossPrice` dan `takeProfitPrice`.
- **Status `ENTRY_HIT` (harga sudah menyentuh zona Entry)** → Tombol **`Market Order MEXC`**
  - Mengeksekusi **Market Order** pada harga pasar saat itu disertai **Slippage Guard** agar tidak masuk jika harga sudah bergerak terlalu jauh dari rencana.
- **Status `EXTENDED`** → Mengikuti kondisi harga saat itu (Limit jika belum tersentuh, Market jika sudah di zona entry).
- **Order Pending (`LIMIT` belum terisi)** → Tombol **`Cancel Order MEXC`** untuk membatalkan order di MEXC.

---

## 2. Persiapan Sebelum Implementasi

### A. Kredensial & Keamanan API Key MEXC
1. Buat API Key di akun MEXC dengan izin:
   - **Read / Account** (cek saldo & posisi)
   - **Futures Trade** (submit & cancel order)
   - **Jangan aktifkan Withdraw**.
2. **IP Whitelist:**
   - Dari `localhost` (IP rumah dinamis), API Key tanpa whitelist tetap bisa digunakan (perhatikan masa berlaku key dari MEXC).
   - Untuk keamanan lebih tinggi, arahkan request melalui `mexc_proxy_url` / VPS ber-IP statis dan whitelist IP tersebut di MEXC.
3. **Simpan Kredensial:**
   - Tambahkan `MEXC_API_KEY` dan `MEXC_API_SECRET` di `.env` (atau terenkripsi di `app_settings`). Jangan pernah kirim `api_secret` ke frontend atau log.

### B. Uji Koneksi Private API Terlebih Dahulu
Karena MEXC Futures API sempat memberlakukan pembatasan akses order pada akun/region tertentu, lakukan verifikasi awal sebelum membangun UI:
1. Tes endpoint baca saldo: `GET /api/v1/private/account/assets`
2. Tes endpoint detail kontrak (public): `GET /api/v1/contract/detail`
3. Tes 1× submit + cancel Limit Order ukuran minimum pada pair likuid (misal jauh dari harga pasar) untuk memastikan akun mendapat izin order API.

### C. Konfigurasi Jaringan (ISP Indonesia)
- Gunakan `mexc_base_url` (`https://contract.mexc.fm` atau `https://contract.mexc.com`) dan `mexc_proxy_url` yang sudah tersedia di menu **Settings** agar request private API juga melewati jalur yang sama.

---

## 3. Alur Eksekusi Order (End-to-End Flow)

```mermaid
flowchart TD
    A["Setup di Dashboard"] --> B{"Cek Status Setup"}
    B -- "OPEN" --> C["Tombol: Limit Order MEXC"]
    B -- "ENTRY_HIT" --> D["Tombol: Market Order MEXC"]
    C --> E["Modal Konfirmasi Order"]
    D --> E
    E --> F["Input: Margin/Risk USDT, Leverage, Isolated/Cross"]
    F --> G["Backend: Preview Sizing & Slippage Guard"]
    G --> H{"Valid & User Klik Konfirmasi?"}
    H -- "Tidak" --> I["Batal / Tampilkan Peringatan"]
    H -- "Ya" --> J["Cek Anti-Double-Order di DB"]
    J --> K["Set Leverage & Submit Order ke MEXC Private API"]
    K --> L{"Order Sukses?"}
    L -- "Gagal" --> M["Catat Error & Tampilkan Pesan MEXC"]
    L -- "Sukses" --> N["Simpan mexc_order_id + Update Status ke MANUAL_TAKEN"]
```

### Aturan Guard per Tipe Order
1. **Limit Order (Setup `OPEN`):**
   - Pastikan harga saat ini (`last_price`) masih di sisi yang valid:
     - `LONG`: `last_price > stop_loss` dan `entry_price <= last_price` (jika harga sudah tembus ke bawah entry dan masih valid, sarankan Market atau Limit sesuai kondisi).
     - `SHORT`: `last_price < stop_loss` dan `entry_price >= last_price`.
2. **Market Order (Setup `ENTRY_HIT`):**
   - **Slippage Guard:** hitung deviasi `abs(last_price - entry_price) / entry_price`. Jika melebihi batas maksimal (misal `> 0.5%` atau `> 0.5x ATR14`) atau R:R aktual turun di bawah `1.2`, tampilkan peringatan keras / blokir eksekusi.

---

## 4. Perhitungan Position Sizing & Presisi Kontrak MEXC

MEXC Futures menggunakan satuan **jumlah kontrak (`vol`)**, bukan langsung USDT. Sebelum mengirim order, backend wajib membaca metadata kontrak dari `/api/v1/contract/detail`:
- `contractSize` (nilai 1 kontrak dalam koin dasar, misal `0.0001` BTC atau `1` DOGE)
- `priceUnit` / `priceScale` (kelipatan pembulatan harga untuk Entry, SL, TP)
- `volUnit`, `minVol`, `maxVol` (kelipatan & batas jumlah kontrak)
- `maxLeverage` (batas leverage maksimal pair)

### Dua Mode Sizing yang Disarankan
1. **Berdasarkan Risk per Trade (Direkomendasikan):**
   - User isi `Risk USDT` (misal `$10` jika kena SL).
   - `jarak_sl = abs(entry_price - stop_loss)`
   - `qty_coin = risk_usdt / jarak_sl`
   - `vol = floor_to_step(qty_coin / contractSize, volUnit)`
2. **Berdasarkan Margin & Leverage:**
   - User isi `Margin USDT` (misal `$20`) dan `Leverage` (misal `10x`).
   - `notional_usdt = margin_usdt * leverage`
   - `qty_coin = notional_usdt / entry_price`
   - `vol = floor_to_step(qty_coin / contractSize, volUnit)`

Semua harga (`entry_price`, `stop_loss`, `take_profit`) wajib dibulatkan ke kelipatan `priceUnit` kontrak sebelum dikirim ke MEXC agar tidak ditolak oleh API.

---

## 5. Rancangan Perubahan Kode & Database

### A. Database (`app/models.py` & `init_database.sql`)
Tambahkan tabel baru **`order_executions`** (relasi ke `trade_setups.id`) untuk audit dan anti-double-order:
- `id`, `setup_id` (FK ke `trade_setups.id`)
- `symbol`, `side` (`OPEN_LONG` / `OPEN_SHORT`)
- `order_type` (`LIMIT` / `MARKET`)
- `open_type` (`ISOLATED` / `CROSS`)
- `leverage`, `vol`, `margin_usdt`, `risk_usdt`
- `entry_price`, `stop_loss`, `take_profit`
- `mexc_order_id` (String, indexed)
- `status` (`SUBMITTED`, `FILLED`, `PARTIAL`, `CANCELED`, `FAILED`)
- `error_message`, `raw_response` (JSON)
- `created_at`, `updated_at`

### B. Backend Private Client (`app/scanner/mexc_private.py`)
Modul baru khusus endpoint terautentikasi MEXC Futures:
- Signing **HMAC-SHA256** (`ApiKey`, `Request-Time`, `Signature`, `Recv-Window`)
- `get_account_assets()` → cek saldo USDT tersedia
- `get_contract_detail(symbol)` → cache metadata `contractSize`, `priceUnit`, `volUnit`, `maxLeverage`
- `change_leverage(symbol, leverage, open_type)`
- `submit_order(...)` → `LIMIT` / `MARKET` dengan `stopLossPrice` & `takeProfitPrice`
- `cancel_order(order_id)` & `get_order(order_id)`

### C. Backend Endpoints (`app/web/dashboard.py` & `app/schemas.py`)
- `GET /api/mexc/account` → status koneksi API Key & saldo USDT tersedia
- `POST /api/setups/{setup_id}/order/preview` → hitung `vol`, estimasi margin, estimasi rugi SL, estimasi profit TP, dan cek slippage
- `POST /api/setups/{setup_id}/order` → validasi anti-double-order, eksekusi ke MEXC, simpan ke `order_executions`, lalu ubah status setup menjadi `MANUAL_TAKEN` (menyimpan `manual_entry_price`, `manual_sl`, `manual_tp` sesuai yang terkirim)
- `POST /api/setups/{setup_id}/order/cancel` → batalkan order `LIMIT` yang masih pending di MEXC

### D. Frontend (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`)
- **Tombol Aksi di Tabel & Detail Modal Setup:**
  - `OPEN` → tampilkan tombol **`Limit Order`**
  - `ENTRY_HIT` → tampilkan tombol **`Market Order`**
  - Jika sudah ada `order_executions` aktif (`SUBMITTED`/`FILLED`) → tampilkan badge **`LIVE MEXC`** (dan tombol **`Cancel Order`** bila `LIMIT` masih `SUBMITTED`).
- **Modal Konfirmasi Order MEXC:**
  - Pilih mode sizing (**Risk USDT** atau **Margin USDT**), **Leverage**, **Isolated / Cross**.
  - Tampilkan preview hasil hitungan backend: jumlah kontrak (`vol`), estimasi Margin terpakai, potensi rugi di SL, potensi profit di TP, R:R aktual, dan peringatan jika slippage melebihi batas.
  - Tombol **Konfirmasi & Kirim Order** hanya aktif setelah preview valid.

---

## 6. Checklist Implementasi Bertahap

- [ ] **Fase 1 (Verifikasi API):** Buat `app/scanner/mexc_private.py` dan endpoint `GET /api/mexc/account`, lalu uji saldo & izin order MEXC dari `localhost`.
- [ ] **Fase 2 (Sizing & Preview):** Implementasikan `get_contract_detail` + kalkulator `vol` & `priceUnit` + endpoint `POST /api/setups/{id}/order/preview`.
- [ ] **Fase 3 (Eksekusi & Audit):** Tambah tabel `order_executions`, endpoint `POST /api/setups/{id}/order` & `cancel`, serta guard anti-double-order + slippage guard.
- [ ] **Fase 4 (UI Modal & Tombol):** Tambah tombol `Limit Order` / `Market Order` sesuai status setup dan modal konfirmasi dengan preview sizing.
- [ ] **Fase 5 (Sinkronisasi Tracker - Opsional):** Tracker periodik mengecek status order `SUBMITTED` di MEXC untuk memantau apakah Limit Order sudah `FILLED` atau `CANCELED`.
