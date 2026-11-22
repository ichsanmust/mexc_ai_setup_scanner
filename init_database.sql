-- ====================================================================
-- Script Inisialisasi Database MySQL untuk mexc-ai-setup-scanner
-- Database target: mexc_scanner
-- ====================================================================

CREATE DATABASE IF NOT EXISTS `mexc_scanner`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `mexc_scanner`;

-- 1. Daftar Model AI yang bisa dikelola & dipilih aktif
CREATE TABLE IF NOT EXISTS `ai_models` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL,
  `model_id` VARCHAR(150) NOT NULL,
  `provider` VARCHAR(32) NOT NULL DEFAULT 'commandcode',
  `description` VARCHAR(255) NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 0,
  `is_custom` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ai_models_provider_model_id` (`provider`, `model_id`),
  KEY `ix_ai_models_model_id` (`model_id`),
  KEY `ix_ai_models_provider` (`provider`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Pengaturan Aplikasi & Konfigurasi Provider LLM (Command Code AI / OpenRouter / Custom)
CREATE TABLE IF NOT EXISTS `app_settings` (
  `key` VARCHAR(100) NOT NULL,
  `value` TEXT NULL,
  `description` VARCHAR(255) NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Daftar Strategi Trading, Prompt Aturan AI, & Sugesti Setting
CREATE TABLE IF NOT EXISTS `strategies` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(64) NOT NULL,
  `display_name` VARCHAR(120) NOT NULL,
  `description` VARCHAR(255) NULL,
  `trade_style` VARCHAR(40) NULL,
  `holding_period` VARCHAR(80) NULL,
  `suggested_htf` VARCHAR(20) NULL,
  `suggested_ltf` VARCHAR(20) NULL,
  `suggested_kline_limit` INT NULL,
  `suggested_expiry_hours` INT NULL,
  `prompt_text` TEXT NOT NULL,
  `min_rr` DECIMAL(6, 2) NOT NULL DEFAULT 1.50,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `is_builtin` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_strategies_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Riwayat Eksekusi Scanner
CREATE TABLE IF NOT EXISTS `scan_runs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `strategy` VARCHAR(80) NOT NULL DEFAULT 'ALL',
  `llm_provider` VARCHAR(32) NULL,
  `llm_model` VARCHAR(150) NULL,
  `total_contracts` INT NOT NULL DEFAULT 0,
  `top_pairs_count` INT NOT NULL DEFAULT 0,
  `prefiltered_count` INT NOT NULL DEFAULT 0,
  `ai_analyzed_count` INT NOT NULL DEFAULT 0,
  `setups_created_count` INT NOT NULL DEFAULT 0,
  `status` VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
  `error_message` TEXT NULL,
  `settings_snapshot` JSON NULL,
  `started_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `finished_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_scan_runs_status` (`status`),
  KEY `ix_scan_runs_started_at` (`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Setup Trading Valid (Manual Execution & Outcome Tracker)
CREATE TABLE IF NOT EXISTS `trade_setups` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `scan_run_id` BIGINT NULL,
  `symbol` VARCHAR(32) NOT NULL,
  `strategy_used` VARCHAR(64) NOT NULL,
  `decision` VARCHAR(16) NOT NULL,
  `market_regime` VARCHAR(32) NOT NULL,
  `entry_type` VARCHAR(16) NOT NULL,
  `entry_price` DECIMAL(20, 8) NOT NULL,
  `stop_loss` DECIMAL(20, 8) NOT NULL,
  `take_profit` DECIMAL(20, 8) NOT NULL,
  `risk_reward_ratio` DECIMAL(10, 4) NOT NULL,
  `confidence` INT NOT NULL,
  `llm_provider` VARCHAR(32) NULL,
  `llm_model` VARCHAR(150) NULL,
  `invalidation_reason` TEXT NOT NULL,
  `rationale` TEXT NOT NULL,
  `status` VARCHAR(24) NOT NULL DEFAULT 'OPEN',
  `manual_action_at` DATETIME NULL,
  `manual_entry_price` DECIMAL(20, 8) NULL,
  `manual_notes` TEXT NULL,
  `resolved_price` DECIMAL(20, 8) NULL,
  `resolved_at` DATETIME NULL,
  `expires_at` DATETIME NOT NULL,
  `features_snapshot` JSON NOT NULL,
  `ai_payload` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trade_setups_symbol_status` (`symbol`, `status`),
  KEY `idx_trade_setups_created_at` (`created_at`),
  KEY `idx_trade_setups_strategy_status` (`strategy_used`, `status`),
  KEY `idx_trade_setups_dup_lookup` (`symbol`, `decision`, `strategy_used`, `status`),
  KEY `fk_trade_setups_scan_run_id` (`scan_run_id`),
  CONSTRAINT `fk_trade_setups_scan_run_id` FOREIGN KEY (`scan_run_id`) REFERENCES `scan_runs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Audit Evaluasi Pair (NO_TRADE / Rejected by Risk & Math Guard)
CREATE TABLE IF NOT EXISTS `scan_evaluations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `scan_run_id` BIGINT NOT NULL,
  `symbol` VARCHAR(32) NOT NULL,
  `strategy_used` VARCHAR(64) NOT NULL,
  `raw_decision` VARCHAR(16) NOT NULL,
  `rejection_reason` VARCHAR(255) NOT NULL,
  `confidence` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_scan_evaluations_created_at` (`created_at`),
  KEY `fk_scan_evaluations_scan_run_id` (`scan_run_id`),
  CONSTRAINT `fk_scan_evaluations_scan_run_id` FOREIGN KEY (`scan_run_id`) REFERENCES `scan_runs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed awal model AI & pengaturan provider
INSERT IGNORE INTO `ai_models` (`name`, `model_id`, `provider`, `description`, `is_active`, `is_custom`) VALUES
('Gemini 2.5 Flash (Command Code)', 'google/gemini-2.5-flash', 'commandcode', 'Cepat dan akurat untuk analisis JSON terstruktur multi-pair.', 1, 0),
('GPT-4o Mini (Command Code)', 'openai/gpt-4o-mini', 'commandcode', 'Model ringan dan konsisten untuk output JSON Schema ketat.', 0, 0),
('Claude 3.5 Sonnet (Command Code)', 'anthropic/claude-3.5-sonnet', 'commandcode', 'Penalaran teknikal mendalam untuk konfirmasi struktur multi-timeframe.', 0, 0),
('Google Gemini 2.5 Flash (OpenRouter)', 'google/gemini-2.5-flash', 'openrouter', 'Rekomendasi cepat & hemat token melalui OpenRouter.', 0, 0),
('OpenAI GPT-4o Mini (OpenRouter)', 'openai/gpt-4o-mini', 'openrouter', 'Model cepat OpenAI via OpenRouter dengan dukungan JSON Schema.', 0, 0),
('DeepSeek Chat V3 (OpenRouter)', 'deepseek/deepseek-chat-v3-0324', 'openrouter', 'Alternatif reasoning kuantitatif hemat biaya via OpenRouter.', 0, 0),
('Anthropic Claude 3.7 Sonnet (OpenRouter)', 'anthropic/claude-3.7-sonnet', 'openrouter', 'Model penalaran tinggi untuk filtering setup ketat.', 0, 0),
('OpenRouter Free Router [Free]', 'openrouter/free', 'openrouter', 'Free - Router otomatis ke model gratis yang tersedia (mendukung structured_outputs & response_format).', 0, 0),
('Google Gemma 4 31B [Free]', 'google/gemma-4-31b-it:free', 'openrouter', 'Free - Google Gemma 4 31B gratis, mendukung response_format & context 262k.', 0, 0),
('Google Gemma 4 26B A4B [Free]', 'google/gemma-4-26b-a4b-it:free', 'openrouter', 'Free - Google Gemma 4 26B MoE cepat & gratis, mendukung response_format.', 0, 0),
('Ling 3.2 Flash [Free]', 'inclusionai/ling-3.2-flash:free', 'openrouter', 'Free - Gratis, mendukung response_format & structured_outputs (context 1M).', 0, 0),
('NVIDIA Nemotron 3.5 Lightning [Free]', 'nvidia/nemotron-3.5-lightning:free', 'openrouter', 'Free - Gratis, inferensi cepat (fallback JSON prompt).', 0, 0),
('NVIDIA Nemotron 3 Ultra [Free]', 'nvidia/nemotron-3-ultra-550b-a55b:free', 'openrouter', 'Free - Gratis, model reasoning besar (fallback JSON prompt).', 0, 0);

INSERT IGNORE INTO `app_settings` (`key`, `value`, `description`) VALUES
('llm_active_provider', 'commandcode', 'Provider LLM aktif: commandcode, openrouter, atau custom'),
('commandcode_base_url', 'https://api.commandcode.ai/provider/v1/chat/completions', 'Endpoint Chat Completions untuk Command Code AI'),
('commandcode_api_key', '', 'API Key Command Code AI'),
('openrouter_base_url', 'https://openrouter.ai/api/v1/chat/completions', 'Endpoint Chat Completions untuk OpenRouter'),
('openrouter_api_key', '', 'API Key OpenRouter'),
('custom_llm_base_url', '', 'Endpoint Chat Completions custom OpenAI-compatible'),
('custom_llm_api_key', '', 'API Key untuk endpoint custom'),
('active_model_id', 'google/gemini-2.5-flash', 'Model ID AI aktif yang digunakan untuk analisis setup'),
('llm_timeout_seconds', '45', 'Timeout request LLM dalam detik'),
('llm_max_concurrency', '3', 'Maksimum request paralel ke LLM'),
('mexc_base_url', 'https://contract.mexc.com', 'Base URL public REST MEXC Futures'),
('mexc_proxy_url', '', 'Proxy opsional untuk request MEXC'),
('mexc_max_concurrency', '5', 'Maksimum request paralel ke MEXC'),
('auto_scan_enabled', 'true', 'Mode auto-scan terjadwal (true=AUTO, false=MANUAL)'),
('top_n_pairs', '30', 'Jumlah Top N pair berdasarkan volume 24 jam'),
('scan_interval_minutes', '15', 'Interval auto-scan dalam menit'),
('tracker_interval_seconds', '60', 'Interval pengecekan outcome setup OPEN (detik)'),
('active_strategies', 'INTRADAY_BREAKOUT_RETEST', 'Daftar strategi aktif'),
('min_24h_quote_volume', '5000000', 'Filter minimal volume quote 24 jam (USDT)'),
('max_24h_quote_volume', '0', 'Filter maksimal volume quote 24 jam (USDT, 0 = tanpa batas)'),
('min_atr_pct', '0.25', 'Pre-filter minimal ATR% LTF'),
('max_atr_pct', '8.0', 'Pre-filter maksimal ATR% LTF'),
('min_confidence', '75', 'Minimal confidence AI untuk lolos Risk Guard');

-- Seed awal strategi bawaan & kustom (sinkron dengan database saat ini)
-- Catatan Snapshot AI: Setiap strategi selalu memakai `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, & `suggested_expiry_hours` masing-masing,
-- `htf_1h` & `ltf_15m` mengikuti `interval` aktual strategi, `recent_candles` menyediakan `volume`, `is_bullish`, & `direction`, serta indikator mencakup `dss`, `prev_dss`, & `dss_signal`.
INSERT IGNORE INTO `strategies` (
  `name`, `display_name`, `description`, `trade_style`, `holding_period`,
  `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, `suggested_expiry_hours`,
  `prompt_text`, `min_rr`, `is_active`, `is_builtin`
) VALUES
(
  'TREND_PULLBACK',
  'Trend Pullback',
  'Intraday trend following & pullback ke EMA 21/50 / flip zone searah tren HTF (min R:R 1.8).',
  'INTRADAY',
  '4 - 24 Jam (Intraday)',
  'Min60',
  'Min15',
  250,
  12,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang sangat disiplin pada manajemen risiko.\nStrategi Anda saat ini adalah: TREND_PULLBACK (Intraday Trend Following & Pullback ke EMA / Flip Zone).\n\nATURAN EVALUASI KETAT:\n1. Evaluasi tren Higher Timeframe (HTF 1H / Min60) terlebih dahulu:\n   - Tentukan bias tren dari posisi harga terhadap EMA 50 dan EMA 200, keselarasan EMA 21 > EMA 50 > EMA 200 (uptrend) atau EMA 21 < EMA 50 < EMA 200 (downtrend), serta struktur swing (Higher High/Higher Low atau Lower High/Lower Low).\n   - Jika HTF sideways/choppy atau EMA 50 & EMA 200 datar saling silang tanpa struktur jelas, wajib pilih NO_TRADE.\n2. Cari pullback sehat di Lower Timeframe (LTF 15m / Min15):\n   - Tunggu harga melakukan pullback terkendali ke area EMA 21 / EMA 50 LTF atau area support/resistance flip zone yang searah dengan tren HTF.\n   - Konfirmasi tanda kelanjutan tren dari candlestick (rejection wick searah tren, body candle solid) dan RSI 14 sehat (tidak entry saat RSI sudah ekstrem jenuh searah tren; jangan FOMO mengejar harga yang sudah jauh dari EMA 21).\n3. Penentuan Level Eksekusi (LONG atau SHORT):\n   - Entry Price: harga limit di area pullback/flip zone atau market jika konfirmasi candle baru saja selesai di zona pullback.\n   - Stop Loss: letakkan di balik recent swing low (untuk LONG) atau recent swing high (untuk SHORT) ditambah buffer ATR 14 LTF sekitar 0.3x hingga 0.5x ATR.\n   - Take Profit: targetkan tepat sebelum resistance mayor berikutnya (untuk LONG) atau sebelum support mayor berikutnya (untuk SHORT).\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.8. Jika struktur level tidak memberi ruang R:R >= 1.8, wajib NO_TRADE.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", serta entry_price=null, stop_loss=null, take_profit=null, risk_reward_ratio=null jika:\n     * Terjadi konflik antara tren HTF dan struktur LTF.\n     * Harga sudah terlalu jauh extended dari EMA 21 (risiko chase/FOMO).\n     * Confidence Anda di bawah 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "TREND_PULLBACK".\n',
  1.80,
  0,
  1
),
(
  'BREAKOUT_MOMENTUM',
  'Breakout Momentum',
  'Breakout konsolidasi level kunci dengan konfirmasi volume >= 1.5x MA20 (min R:R 2.0).',
  'INTRADAY_SWING',
  '4 - 48 Jam (1 - 2 Hari)',
  'Min60',
  'Min15',
  250,
  24,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang spesialis membaca ekspansi volatilitas dan volume.\nStrategi Anda saat ini adalah: BREAKOUT_MOMENTUM (Breakout Konsolidasi dengan Konfirmasi Volume >= 1.5x).\n\nATURAN EVALUASI KETAT:\n1. Deteksi Kompresi & Level Kunci:\n   - Cari kondisi konsolidasi/kompresi harga yang rapat di dekat resistance kunci (untuk potensi LONG) atau support kunci (untuk potensi SHORT) pada HTF (1H) dan LTF (15m).\n   - Perhatikan konteks derivatives: funding_rate yang tidak ekstrem berlawanan secara crowding dan open_interest (hold_vol) yang sehat mendukung kelanjutan ekspansi.\n2. Syarat Wajib Konfirmasi Breakout:\n   - Harus ada close candle tegas di luar level resistance/support kunci (bukan sekadar jarum/wick palsu).\n   - Volume Ratio LTF wajib >= 1.5x dari Volume MA20. Jika volume_ratio < 1.5, JANGAN ambil breakout (wajib NO_TRADE).\n   - RSI 14 harus mendukung momentum namun masih sehat (hindari entry jika RSI sudah overbought ekstrem > 80 untuk LONG atau oversold ekstrem < 20 untuk SHORT, serta hindari candle dengan wick penolakan besar melawan arah breakout).\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area penutupan breakout atau retest dangkal batas level yang ditembus.\n   - Stop Loss: di dalam area range konsolidasi / di balik level breakout dengan buffer ATR (sekitar 0.4x–0.6x ATR) agar aman dari noise.\n   - Take Profit: berdasarkan proyeksi lebar range konsolidasi atau area likuiditas / resistance-support mayor berikutnya.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 2.0. Jika tidak mencapai 2.0 secara realistis, wajib NO_TRADE.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika volume_ratio < 1.5, terlihat fakeout/wick penolakan besar, struktur tidak jelas, konflik timeframe, atau confidence < 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "BREAKOUT_MOMENTUM".',
  2.00,
  0,
  1
),
(
  'MEAN_REVERSION_SCALP',
  'Mean Reversion Scalp',
  'Pantulan Support/Resistance + RSI ekstrem khusus saat market RANGING (min R:R 1.5).',
  'SCALP',
  '1 - 6 Jam (Scalp)',
  'Min30',
  'Min5',
  250,
  6,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang berfokus pada perdagangan range dan ekstrem momentum.\nStrategi Anda saat ini adalah: MEAN_REVERSION_SCALP (Pantulan Support/Resistance saat Kondisi Ranging).\n\nATURAN EVALUASI KETAT:\n1. Syarat Wajib Kondisi Pasar (RANGING Only):\n   - Strategi ini HANYA boleh aktif jika market_regime adalah "RANGING" (HTF & LTF tidak sedang trending kuat searah, EMA 21/50 relatif datar/berdekatan dan harga memantul di antara batas range yang jelas).\n   - Jika pasar sedang TRENDING_UP, TRENDING_DOWN, atau HIGH_VOLATILITY_CHOP ekstrem, wajib pilih NO_TRADE.\n2. Syarat Sinyal Pantulan:\n   - LONG: Harga berada di dekat nearest_support / lower range dengan tanda pelemahan tekanan jual (rejection wick bawah, candle berbalik positif) DAN RSI 14 LTF berada di area oversold (< 30) atau baru berbalik naik dari bawah 30.\n   - SHORT: Harga berada di dekat nearest_resistance / upper range dengan tanda pelemahan tekanan beli (rejection wick atas, candle berbalik negatif) DAN RSI 14 LTF berada di area overbought (> 70) atau baru berbalik turun dari atas 70.\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area pantulan support/resistance saat ini.\n   - Stop Loss: letakkan ketat di luar batas range (sekitar 0.5x–0.8x ATR 14 LTF di luar swing support/resistance).\n   - Take Profit: target konservatif ke area mid-range (EMA 21/50) atau sisi range yang berlawanan.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.5.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika market bukan RANGING, RSI belum masuk area ekstrem yang terkonfirmasi berbalik, terdapat ancaman breakdown/breakout bervolume besar, atau confidence < 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "MEAN_REVERSION_SCALP".\n',
  1.50,
  0,
  1
),
(
  'SCALP_LIQUIDITY_SWEEP_REVERSAL',
  'Scalping Liquidity Sweep Reversal',
  'Scalping pembalikan arah (stop hunt) saat harga menyapu swing high/low atau S/R dengan ekor panjang, gagal breakout, dan dikonfirmasi lonjakan volume serta RSI ekstrem.',
  'SCALP',
  '15 Menit - 2 Jam',
  'Min30',
  'Min5',
  250,
  4,
  'Anda adalah AI Crypto Futures Scalping Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe, dan ltf_15m sebagai konteks Lower Timeframe eksekusi) menggunakan strategi SCALP_LIQUIDITY_SWEEP_REVERSAL (Stop Hunt Reversal).\n\nEvaluasi setup secara ketat mengikuti aturan bernomor berikut:\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas memadai dari quote_volume_24h dan open_interest_hold_vol.\n- Periksa selisih last_price terhadap fair_price dan index_price; hindari eksekusi jika terjadi anomali spread ekstrem.\n- Perhatikan funding_rate dan posisi last_price terhadap high_24h dan low_24h sebagai area likuiditas harian potensial.\n\n2. ANALISIS KONTEKS & STRUKTUR HTF (htf_1h):\n- Identifikasi bias makro dari ema_bias (BULLISH_ALIGNED, BEARISH_ALIGNED, FLAT_RANGING, MIXED) serta jarak harga terhadap EMA (dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct).\n- Setup LONG optimal saat HTF berada di FLAT_RANGING, BULLISH_ALIGNED (pullback menyapu likuiditas bawah), atau BEARISH_ALIGNED yang sudah overextended (dist_to_ema21_pct sangat negatif dan rsi14 jenuh jual di dekat nearest_support / recent_swing_low).\n- Setup SHORT optimal saat HTF berada di FLAT_RANGING, BEARISH_ALIGNED (rally menyapu likuiditas atas), atau BULLISH_ALIGNED yang sudah overextended (dist_to_ema21_pct sangat positif dan rsi14 jenuh beli di dekat nearest_resistance / recent_swing_high).\n- Periksa atr_pct dan compression_ratio untuk memastikan volatilitas cukup untuk scalping namun tidak dalam kondisi choppy ekstrem tanpa arah.\n\n3. SYARAT PEMICU LIQUIDITY SWEEP DI LTF (ltf_15m):\n- Untuk LONG (Bullish Sweep / Stop Hunt Bawah):\n  a. Salah satu candle terbaru pada recent_candles harus memiliki low yang menembus/menyapu di bawah recent_swing_low atau nearest_support (dist_to_support_pct sangat kecil/negatif saat sweep), namun GAGAL breakdown dan close kembali di atas level tersebut (kembali ke dalam range).\n  b. Candle sweep wajib memiliki ekor bawah panjang dengan lower_wick_pct tinggi (minimal >= 45% dari total range candle) dan body_pct relatif kecil atau ditutup hijau (is_bullish = true).\n  c. Konfirmasi volume: volume_ratio >= 1.5 (current_volume melonjak signifikan di atas vol_ma20) sebagai bukti penyerapan likuiditas (absorption).\n  d. Konfirmasi momentum: rsi14 berada di area ekstrem rendah (<= 35) atau menunjukkan pembalikan/divergensi bullish (rsi14 > prev_rsi14 setelah menyapu low baru).\n- Untuk SHORT (Bearish Sweep / Stop Hunt Atas):\n  a. Salah satu candle terbaru pada recent_candles harus memiliki high yang menembus/menyapu di atas recent_swing_high atau nearest_resistance (dist_to_resistance_pct sangat kecil/negatif saat sweep), namun GAGAL breakout dan close kembali di bawah level tersebut (kembali ke dalam range).\n  b. Candle sweep wajib memiliki ekor atas panjang dengan upper_wick_pct tinggi (minimal >= 45% dari total range candle) dan body_pct relatif kecil atau ditutup merah (is_bullish = false).\n  c. Konfirmasi volume: volume_ratio >= 1.5 (current_volume melonjak signifikan di atas vol_ma20).\n  d. Konfirmasi momentum: rsi14 berada di area ekstrem tinggi (>= 65) atau menunjukkan pembalikan/divergensi bearish (rsi14 < prev_rsi14 setelah menyapu high baru).\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle konfirmasi sweep baru saja close di dalam range dengan momentum kuat dan harga saat ini (close / last_price) masih dekat dengan area sweep.\n- Gunakan entry_type = "LIMIT" di area retest 30%-50% dari ekor candle sweep (atau tepat di level nearest_support untuk LONG / nearest_resistance untuk SHORT) jika harga sudah bergerak terlalu jauh dari titik sweep agar Risk-to-Reward tetap terjaga.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah titik terendah (low) candle sweep / recent_swing_low ditambah buffer volatilitas sebesar 0.3x hingga 0.5x atr14 LTF.\n- SHORT: Tempatkan SL di atas titik tertinggi (high) candle sweep / recent_swing_high ditambah buffer volatilitas sebesar 0.3x hingga 0.5x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada level likuiditas berlawanan yang realistis untuk scalping 15 menit - 2 jam: nearest_resistance / recent_swing_high (untuk LONG) atau nearest_support / recent_swing_low (untuk SHORT), atau level dinamis ema21 / ema50 jika melawan tren mikro.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.0 (min_rr = 2.0). Jika jarak ke target terdekat menghasilkan R:R < 2.0, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE:\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. Tidak ada sweep yang jelas (ekor pendek / candle close dengan body penuh menembus support/resistance yang menandakan breakout valid, bukan stop hunt).\n  b. Volume lemah (volume_ratio < 1.3) saat sweep terjadi.\n  c. Terjadi konflik berat antara struktur HTF dan LTF (misalnya melawan tren HTF yang sangat kuat dengan momentum agresif tanpa tanda kelelahan RSI).\n  d. R:R kurang dari 2.0.\n  e. Tingkat keyakinan (confidence) kurang dari 75.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SCALP_LIQUIDITY_SWEEP_REVERSAL".',
  2.00,
  0,
  0
),
(
  'INTRADAY_BREAKOUT_RETEST',
  'Intraday Breakout & Retest',
  'Breakout & retest intraday di level high/low 24h atau S/R kunci pasca kompresi volatilitas searah tren HTF, dikonfirmasi lonjakan volume dan candle body kuat.',
  'INTRADAY',
  '2 - 12 Jam',
  'Min60',
  'Min15',
  250,
  12,
  'Anda adalah AI Crypto Futures Intraday Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe 1H, dan ltf_15m sebagai konteks Lower Timeframe eksekusi 15m) menggunakan strategi INTRADAY_BREAKOUT_RETEST.\n\nEvaluasi setup secara ketat mengikuti aturan bernomor berikut:\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas kuat berdasarkan quote_volume_24h dan open_interest_hold_vol agar breakout tidak mudah dimanipulasi.\n- Periksa kewajaran last_price terhadap fair_price dan index_price; hindari eksekusi jika terjadi deviasi ekstrem.\n- Catat level high_24h dan low_24h sebagai level kunci likuiditas intraday, serta periksa change_24h_pct dan funding_rate untuk memastikan tidak terlalu ekstrem melawan arah breakout.\n\n2. ANALISIS TREN & KOMPRESI VOLATILITAS HTF (htf_1h):\n- Setup LONG hanya valid jika ema_bias HTF adalah BULLISH_ALIGNED (atau transisi positif dari FLAT_RANGING dengan close di atas ema21 dan ema50) serta dist_to_ema21_pct tidak terlalu overextended.\n- Setup SHORT hanya valid jika ema_bias HTF adalah BEARISH_ALIGNED (atau transisi negatif dari FLAT_RANGING dengan close di bawah ema21 dan ema50) serta dist_to_ema21_pct tidak terlalu overextended.\n- Prioritaskan koin yang mengalami kompresi volatilitas (compression_ratio rendah) sebelum ekspansi, menandakan akumulasi/distribusi energi untuk pergerakan intraday 2 - 12 jam.\n- Konfirmasi momentum HTF: rsi14 searah tren (untuk LONG: rsi14 > 50 dan belum overbought ekstrem; untuk SHORT: rsi14 < 50 dan belum oversold ekstrem) dan atr_pct memadai untuk target intraday.\n\n3. SYARAT PEMICU BREAKOUT & RETEST DI LTF (ltf_15m):\n- Untuk LONG (Bullish Breakout & Retest):\n  a. Sebelum breakout, terlihat kompresi (compression_ratio rendah) di dekat nearest_resistance, recent_swing_high, atau high_24h.\n  b. Candle pemicu pada recent_candles harus menembus dan close tegas di atas level kunci (nearest_resistance, recent_swing_high, atau high_24h) dengan is_bullish = true, body_pct kuat (minimal >= 60%), dan upper_wick_pct kecil (<= 25%) sebagai tanda penolakan seller minimal.\n  c. Konfirmasi volume: volume_ratio >= 1.5 (current_volume melonjak signifikan di atas vol_ma20).\n  d. Konfirmasi momentum: rsi14 menguat (rsi14 > prev_rsi14 dan berada di zona momentum bullish, misal 55 - 75).\n  e. Jika harga sedang melakukan retest ke bekas level breakout (yang kini menjadi nearest_support / area high_24h), pastikan candle retest bertahan di atas level tersebut dengan volume melemah saat pullback atau muncul penolakan ekor bawah (lower_wick_pct).\n- Untuk SHORT (Bearish Breakdown & Retest):\n  a. Sebelum breakdown, terlihat kompresi (compression_ratio rendah) di dekat nearest_support, recent_swing_low, atau low_24h.\n  b. Candle pemicu pada recent_candles harus menembus dan close tegas di bawah level kunci (nearest_support, recent_swing_low, atau low_24h) dengan is_bullish = false, body_pct kuat (minimal >= 60%), dan lower_wick_pct kecil (<= 25%).\n  c. Konfirmasi volume: volume_ratio >= 1.5 (current_volume melonjak signifikan di atas vol_ma20).\n  d. Konfirmasi momentum: rsi14 melemah (rsi14 < prev_rsi14 dan berada di zona momentum bearish, misal 25 - 45).\n  e. Jika harga sedang melakukan retest ke bekas level breakdown (yang kini menjadi nearest_resistance / area low_24h), pastikan candle retest tertahan di bawah level tersebut.\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "LIMIT" (utama) tepat di area retest level kunci yang baru ditembus (bekas nearest_resistance / high_24h untuk LONG, atau bekas nearest_support / low_24h untuk SHORT) jika candle breakout sudah bergerak menjauh agar Risk-to-Reward optimal.\n- Gunakan entry_type = "MARKET" hanya jika harga sudah menyelesaikan retest yang valid atau baru saja close breakout sangat dekat dengan level kunci (dist_to_support_pct / dist_to_resistance_pct masih ketat) dengan momentum volume tinggi.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF atau di bawah low candle breakout/retest ditambah buffer volatilitas sebesar 0.5x hingga 1.0x atr14 LTF.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF atau di atas high candle breakout/retest ditambah buffer volatilitas sebesar 0.5x hingga 1.0x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada level struktur HTF berikutnya (nearest_resistance / recent_swing_high HTF untuk LONG; nearest_support / recent_swing_low HTF untuk SHORT) atau menggunakan proyeksi range konsolidasi / kelipatan atr14 HTF (2x - 3x atr14 HTF) yang realistis dicapai dalam 2 - 12 jam.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.0 (min_rr = 2.0). Jika ruang gerak menuju rintangan terdekat menghasilkan R:R < 2.0, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE:\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. Struktur breakout lemah (body_pct kecil, wick penolakan berlawanan panjang yang mengindikasikan fakeout/liquidity sweep).\n  b. Breakout tidak didukung volume (volume_ratio < 1.3).\n  c. Terjadi konflik antara arah breakout LTF dan ema_bias HTF (misalnya breakout naik di LTF saat HTF BEARISH_ALIGNED kuat atau kondisi MIXED yang choppy).\n  d. Harga sudah terlalu jauh dari level breakout/EMA (overextended) sehingga R:R kurang dari 2.0.\n  e. Tingkat keyakinan (confidence) kurang dari 75.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "INTRADAY_BREAKOUT_RETEST".',
  2.00,
  1,
  0
),
(
  'SWING_CONTRARIAN_SQUEEZE',
  'Swing Contrarian Squeeze',
  'Swing contrarian menangkap short/long squeeze di area S/R utama saat funding rate ekstrem berlawanan arah, OI tinggi, dan muncul konfirmasi reversal LTF serta momentum RSI.',
  'SWING',
  '1 - 4 Hari',
  'Hour4',
  'Min60',
  250,
  24,
  'Anda adalah AI Crypto Futures Swing Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe 4H, dan ltf_15m sebagai konteks Lower Timeframe eksekusi 1H) menggunakan strategi SWING_CONTRARIAN_SQUEEZE (Short/Long Squeeze Reversal).\n\nEvaluasi setup secara ketat mengikuti aturan bernomor berikut:\n\n1. FILTER LIKUIDITAS, FUNDING RATE & OPEN INTEREST (market_ticker):\n- Pastikan likuiditas sangat memadai dari quote_volume_24h dan open_interest_hold_vol yang tinggi (sebagai proksi potensi likuidasi/squeeze bersama funding_rate tanpa feed likuidasi terpisah).\n- Periksa deviasi last_price terhadap fair_price dan index_price; pastikan tidak ada anomali spread ekstrem yang mengganggu eksekusi.\n- Syarat Contrarian Squeeze:\n  a. Untuk LONG (Potensi Short Squeeze): funding_rate harus negatif ekstrem (pasar terlalu ramai posisi Short) sementara harga mulai tertahan di dekat low_24h atau area support kunci.\n  b. Untuk SHORT (Potensi Long Squeeze): funding_rate harus positif ekstrem (pasar terlalu ramai posisi Long) sementara harga mulai tertahan di dekat high_24h atau area resistance kunci.\n- Perhatikan change_24h_pct untuk menilai apakah pergerakan harian sudah terlalu overextended sehingga rawan terjadi pembalikan tajam.\n\n2. ANALISIS STRUKTUR & KONDISI HTF (htf_1h):\n- Evaluasi posisi close terhadap level kunci nearest_support, nearest_resistance, recent_swing_low, dan recent_swing_high:\n  a. Setup LONG: Harga harus berada sangat dekat dengan nearest_support atau recent_swing_low (dist_to_support_pct kecil/ketat), menunjukkan area demand kuat yang mampu memicu short covering.\n  b. Setup SHORT: Harga harus berada sangat dekat dengan nearest_resistance atau recent_swing_high (dist_to_resistance_pct kecil/ketat), menunjukkan area supply kuat yang mampu memicu long liquidation.\n- Analisis ema_bias (BULLISH_ALIGNED, BEARISH_ALIGNED, FLAT_RANGING, MIXED) serta jarak ke EMA (dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct). Setup contrarian valid saat kondisi FLAT_RANGING, atau saat tren HTF (BEARISH_ALIGNED untuk LONG / BULLISH_ALIGNED untuk SHORT) sudah overextended jauh dari ema21/ema50 dan mulai kehilangan tenaga.\n- Periksa rsi14 HTF (ideal di zona ekstrem <= 35 untuk LONG atau >= 65 untuk SHORT) serta atr_pct dan compression_ratio untuk menilai potensi ledakan volatilitas 1 - 4 hari.\n\n3. SYARAT PEMICU REVERSAL & MOMENTUM DI LTF (ltf_15m):\n- Untuk LONG (Konfirmasi Short Squeeze):\n  a. Pada recent_candles, muncul candle konfirmasi reversal bullish yang kuat di area nearest_support / recent_swing_low: is_bullish = true dengan body_pct kuat (>= 55%) atau pola rejection kuat dengan lower_wick_pct tinggi (>= 45%) yang ditutup kembali di atas support.\n  b. Konfirmasi momentum: rsi14 meningkat tegas dari prev_rsi14 (rsi14 > prev_rsi14), menunjukkan pergeseran momentum dari jenuh jual.\n  c. Konfirmasi volume: volume_ratio >= 1.4 (current_volume melampaui vol_ma20) sebagai tanda masuknya pembeli agresif dan awal likuidasi posisi Short.\n- Untuk SHORT (Konfirmasi Long Squeeze):\n  a. Pada recent_candles, muncul candle konfirmasi reversal bearish yang kuat di area nearest_resistance / recent_swing_high: is_bullish = false dengan body_pct kuat (>= 55%) atau pola rejection kuat dengan upper_wick_pct tinggi (>= 45%) yang ditutup kembali di bawah resistance.\n  b. Konfirmasi momentum: rsi14 menurun tegas dari prev_rsi14 (rsi14 < prev_rsi14), menunjukkan pergeseran momentum dari jenuh beli.\n  c. Konfirmasi volume: volume_ratio >= 1.4 (current_volume melampaui vol_ma20) sebagai tanda tekanan jual agresif dan awal likuidasi posisi Long.\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle konfirmasi reversal LTF baru saja close dengan momentum volume tinggi dan harga saat ini (close / last_price) masih berada di dekat area support/resistance kunci sehingga R:R tetap ideal.\n- Gunakan entry_type = "LIMIT" di area pullback/retest 30%-50% dari body/ekor candle konfirmasi LTF (atau di sekitar nearest_support untuk LONG / nearest_resistance untuk SHORT) jika harga sudah memantul cukup jauh dari titik reversal.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF/HTF atau di bawah low candle reversal ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF agar tahan terhadap noise swing.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF/HTF atau di atas high candle reversal ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada area likuiditas utama HTF yang realistis untuk holding 1 - 4 hari: nearest_resistance / recent_swing_high HTF atau area mean reversion ema50 / ema200 HTF (untuk LONG), serta nearest_support / recent_swing_low HTF atau ema50 / ema200 HTF (untuk SHORT), atau proyeksi 3x - 5x atr14 HTF.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.5 (min_rr = 2.5). Jika jarak ke target terdekat menghasilkan R:R < 2.5, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE:\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. funding_rate netral atau searah dengan rencana posisi (tidak ada bahan bakar contrarian squeeze) atau open_interest_hold_vol rendah.\n  b. Harga masih berada di tengah range (jauh dari nearest_support maupun nearest_resistance).\n  c. Belum ada candle konfirmasi reversal yang jelas di LTF (menangkap pisau jatuh tanpa rejection/volume atau rsi14 belum berbalik dari prev_rsi14).\n  d. Konflik ekstrem antara struktur HTF dan LTF (misalnya breakdown/breakout impulsif bervolume besar yang mematahkan S/R kunci).\n  e. R:R kurang dari 2.5 atau tingkat keyakinan (confidence) kurang dari 75.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SWING_CONTRARIAN_SQUEEZE".',
  2.50,
  0,
  0
),
(
  'SWING_TREND_PULLBACK',
  'Swing Trend Following Pullback',
  'Swing mengikuti tren bersih HTF (EMA aligned) dengan menunggu pullback sehat ke area dinamis EMA21-EMA50, RSI mendingin, dan konfirmasi candle rejection searah tren di LTF.',
  'SWING',
  '2 - 5 Hari',
  'Hour4',
  'Min60',
  250,
  24,
  'Anda adalah AI Crypto Futures Swing Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe 4H, dan ltf_15m sebagai konteks Lower Timeframe eksekusi 1H) menggunakan strategi SWING_TREND_PULLBACK (Trend Following Pullback).\n\nEvaluasi setup secara ketat mengikuti aturan bernomor berikut:\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas kuat dari quote_volume_24h dan open_interest_hold_vol agar pergerakan swing 2 - 5 hari berjalan sehat.\n- Periksa deviasi last_price terhadap fair_price dan index_price; hindari eksekusi jika terdapat selisih/spread ekstrem.\n- Evaluasi funding_rate dan change_24h_pct: idealnya funding_rate tidak terlalu ekstrem searah tren (menghindari posisi yang terlalu ramai/crowded) dan posisi last_price terhadap high_24h serta low_24h masih menyisakan ruang gerak searah tren.\n\n2. ANALISIS TREN BERSIH & ZONA PULLBACK HTF (htf_1h):\n- Setup LONG WAJIB memenuhi syarat tren naik bersih: ema_bias adalah BULLISH_ALIGNED (ema21 > ema50 > ema200) dan close bertahan di atas struktur utama (ema50 / ema200).\n- Setup SHORT WAJIB memenuhi syarat tren turun bersih: ema_bias adalah BEARISH_ALIGNED (ema21 < ema50 < ema200) dan close bertahan di bawah struktur utama (ema50 / ema200).\n- Syarat Pullback Sehat di Area Dinamis EMA21–EMA50:\n  a. Harga telah terkoreksi mendekati zona dinamis ema21 hingga ema50, ditandai dengan dist_to_ema21_pct dan dist_to_ema50_pct yang tipis/kecil (harga tidak sedang overextended jauh dari EMA), sementara dist_to_ema200_pct tetap menjaga struktur tren makro.\n  b. Momentum rsi14 HTF mendingin dari area ekstrem tanpa mematahkan tren utama (untuk LONG: rsi14 berada di kisaran netral-sehat sekitar 42 - 58; untuk SHORT: rsi14 berada di kisaran 42 - 58).\n- Nilai bonus konfluensi jika zona EMA21–EMA50 HTF berdekatan dengan nearest_support (untuk LONG, dist_to_support_pct kecil) atau nearest_resistance (untuk SHORT, dist_to_resistance_pct kecil), serta atr_pct memadai dan compression_ratio tidak menunjukkan chop ekstrem.\n\n3. SYARAT PEMICU CANDLE REJECTION SEARAH TREN DI LTF (ltf_15m):\n- Untuk LONG (Bullish Continuation Rejection):\n  a. Harga di LTF menguji area dinamis ema21/ema50 atau nearest_support / recent_swing_low, lalu pada recent_candles muncul candle rejection bullish yang tegas: lower_wick_pct panjang (>= 40%) dan/atau candle engulfing/rebound dengan is_bullish = true serta body_pct kuat (>= 50%) yang ditutup di atas area pullback.\n  b. Konfirmasi momentum: rsi14 mulai berbalik naik dari prev_rsi14 (rsi14 > prev_rsi14) setelah mendingin, menandakan koreksi berakhir.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (current_volume meningkat di atas vol_ma20 saat rejection terjadi, sedangkan candle koreksi sebelumnya idealnya bervolume lebih kecil).\n- Untuk SHORT (Bearish Continuation Rejection):\n  a. Harga di LTF menguji area dinamis ema21/ema50 atau nearest_resistance / recent_swing_high, lalu pada recent_candles muncul candle rejection bearish yang tegas: upper_wick_pct panjang (>= 40%) dan/atau candle engulfing/rebound turun dengan is_bullish = false serta body_pct kuat (>= 50%) yang ditutup di bawah area pullback.\n  b. Konfirmasi momentum: rsi14 mulai berbalik turun dari prev_rsi14 (rsi14 < prev_rsi14) setelah memantul.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (current_volume meningkat di atas vol_ma20 saat rejection terjadi).\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle rejection LTF baru saja close searah tren HTF dengan momentum jelas dan harga saat ini (close / last_price) masih sangat dekat dengan zona EMA21–EMA50.\n- Gunakan entry_type = "LIMIT" di area retest 30%-50% dari ekor/body candle rejection LTF atau tepat di sekitar ema21 / nearest_support (LONG) maupun ema21 / nearest_resistance (SHORT) jika harga sudah bergerak menjauh agar Risk-to-Reward tetap optimal.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF (atau di bawah low candle rejection & ema50) ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF agar tidak mudah terkena noise pullback.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF (atau di atas high candle rejection & ema50) ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP secara realistis untuk holding 2 - 5 hari pada ekstensi struktur tren HTF: menembus recent_swing_high / nearest_resistance HTF menuju proyeksi range swing sebelumnya atau kelipatan 3x - 5x atr14 HTF (untuk LONG); serta menembus recent_swing_low / nearest_support HTF menuju proyeksi range atau 3x - 5x atr14 HTF (untuk SHORT).\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.5 (min_rr = 2.5). Jika jarak ke target realistis menghasilkan R:R < 2.5, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE:\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. ema_bias HTF bukan BULLISH_ALIGNED maupun BEARISH_ALIGNED (misalnya FLAT_RANGING atau MIXED yang tidak memiliki tren bersih).\n  b. Harga terlalu jauh dari area EMA21–EMA50 (dist_to_ema21_pct dan dist_to_ema50_pct melebar/overextended sehingga rawan mengejar harga) atau pullback terlalu dalam hingga mematahkan struktur tren (close HTF menembus jauh melewati ema50/ema200 dengan momentum kuat).\n  c. Belum ada candle rejection searah tren di LTF atau rsi14 belum menunjukkan tanda pembalikan searah tren dari prev_rsi14.\n  d. Konflik berat antara struktur HTF dan LTF, R:R kurang dari 2.5, atau tingkat keyakinan (confidence) kurang dari 75.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SWING_TREND_PULLBACK".',
  2.50,
  0,
  0
);
