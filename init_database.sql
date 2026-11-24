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
-- Status valid: OPEN, ENTRY_HIT, EXTENDED, HIT_TP, HIT_SL, EXPIRED,
--               MANUAL_TAKEN, MANUAL_SKIPPED, CLOSED_MANUAL_TP, CLOSED_MANUAL_CL
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
  `entry_hit_at` DATETIME NULL,
  `missed_tp_at` DATETIME NULL,
  `missed_tp_price` DECIMAL(20, 8) NULL,
  `manual_action_at` DATETIME NULL,
  `manual_entry_price` DECIMAL(20, 8) NULL,
  `sl_bep_price` DECIMAL(20, 8) NULL,
  `sl_bep_at` DATETIME NULL,
  `manual_notes` TEXT NULL,
  `resolved_price` DECIMAL(20, 8) NULL,
  `resolved_at` DATETIME NULL,
  `status_history` JSON NULL,
  `expires_at` DATETIME NOT NULL,
  `features_snapshot` JSON NOT NULL,
  `ai_payload` JSON NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trade_setups_symbol_status` (`symbol`, `status`),
  KEY `idx_trade_setups_created_at` (`created_at`),
  KEY `idx_trade_setups_updated_at` (`updated_at`),
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
('llm_max_tokens', '1500', 'Maksimum output token AI per panggilan (512-8192; mengontrol reservasi kredit OpenRouter)'),
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
('min_confidence', '75', 'Minimal confidence AI untuk lolos Risk Guard'),
('risk_profile', 'CONSERVATIVE', 'Profil risiko AI & R:R: CONSERVATIVE, MODERATE, atau AGGRESSIVE');

-- Seed awal strategi bawaan & kustom (sinkron dengan database saat ini)
-- Catatan Snapshot AI: Setiap strategi selalu memakai `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, & `suggested_expiry_hours` masing-masing,
-- `htf_1h` & `ltf_15m` mengikuti `interval` aktual strategi (closed candles only), mencakup `dss_cross_up/down`, `swept_prior_low/high`, `compact_candles_15`, `level_candidates`, & `market_context.btc`.
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
  'Anda adalah analis kuantitatif Crypto Futures profesional yang sangat disiplin pada manajemen risiko.\nStrategi Anda saat ini adalah: TREND_PULLBACK (Intraday Trend Following & Pullback ke EMA / Flip Zone).\n\nATURAN EVALUASI KETAT:\n1. Evaluasi tren Higher Timeframe (HTF sesuai field `interval` di `htf_1h`) terlebih dahulu:\n   - Tentukan bias tren dari `ema_bias` (`BULLISH_ALIGNED` / `BEARISH_ALIGNED` / `MIXED`), posisi harga terhadap EMA 50 & EMA 200, serta struktur swing (`recent_swing_high` / `recent_swing_low`).\n   - Kondisi `BULLISH_ALIGNED` / `BEARISH_ALIGNED` bernilai konfluensi tinggi (A-Grade). Kondisi `MIXED` tetap bisa dipertimbangkan (B-Grade) selama harga tegas di atas EMA 50/200 (LONG) atau di bawah EMA 50/200 (SHORT). Hanya wajib `NO_TRADE` bila HTF sangat choppy (`FLAT_RANGING` datar berimpit tanpa arah jelas).\n2. Cari pullback sehat di Lower Timeframe (LTF sesuai field `interval` di `ltf_15m`):\n   - Tunggu harga melakukan pullback terkendali ke area EMA 21 / EMA 50 LTF atau area support/resistance flip zone yang searah dengan tren HTF.\n   - Konfluensi tambahan (menaikkan confidence ke 80+): candle rejection/rebound searah tren di `recent_candles`, DSS Bressert (`dss_cross_up` / `dss_cross_down` dari area jenuh), dan RSI 14 sehat (tidak overextended jauh dari EMA 21).\n3. Penentuan Level Eksekusi (LONG atau SHORT):\n   - Entry Price: harga limit di area pullback/flip zone atau market jika konfirmasi candle baru saja selesai di zona pullback.\n   - Stop Loss: letakkan di balik recent swing low (untuk LONG) atau recent swing high (untuk SHORT) ditambah buffer ATR 14 LTF sekitar 0.3x hingga 0.5x ATR.\n   - Take Profit: targetkan tepat sebelum resistance mayor berikutnya (untuk LONG) atau sebelum support mayor berikutnya (untuk SHORT).\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.8. Jika struktur level tidak memberi ruang R:R >= 1.8, wajib NO_TRADE.\n4. Disiplin NO_TRADE & Skala Confidence Objektif:\n   - Gunakan skala objektif: `80–95` (A-Grade: HTF aligned kuat + pullback tepat + rejection/volume/DSS mendukung), `70–79` (B-Grade: tren & pullback + R:R valid namun 1 faktor tambahan kurang sempurna), `< 70` (lemah/konflik -> wajib `NO_TRADE`).\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", serta entry_price=null, stop_loss=null, take_profit=null, risk_reward_ratio=null jika:\n     * Terjadi konflik langsung antara arah tren HTF dan struktur LTF.\n     * Harga sudah terlalu jauh extended dari EMA 21 sehingga R:R < 1.8.\n     * Struktur terlalu choppy / confidence objektif < 70.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "TREND_PULLBACK".\n',
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
  'Anda adalah analis kuantitatif Crypto Futures profesional yang spesialis membaca ekspansi volatilitas dan volume.\nStrategi Anda saat ini adalah: BREAKOUT_MOMENTUM (Breakout Konsolidasi dengan Konfirmasi Volume >= 1.5x).\n\nATURAN EVALUASI KETAT:\n1. Deteksi Kompresi & Level Kunci:\n   - Cari kondisi konsolidasi/harga yang mendekati resistance kunci (untuk potensi LONG) atau support kunci (untuk potensi SHORT) pada HTF dan LTF (sesuai field `interval`). Kompresi ketat (`compression_ratio` rendah) menjadi bonus konfluensi kuat.\n   - Perhatikan konteks derivatives: funding_rate yang tidak ekstrem berlawanan secara crowding dan open_interest (hold_vol) yang sehat mendukung kelanjutan ekspansi.\n2. Syarat Konfirmasi Breakout (Wajib vs Konfluensi):\n   - Syarat Wajib: Harus ada close candle tegas di luar level resistance/support kunci (bukan sekadar jarum/wick palsu), serta Volume Ratio LTF >= 1.2x (bila < 1.2x anggap lemah -> NO_TRADE).\n   - Konfluensi A-Grade (confidence 80+): `volume_ratio >= 1.5`, RSI 14 sehat (tidak > 82 LONG atau < 18 SHORT), serta body candle dominan tanpa wick penolakan besar.\n   - Setup B-Grade (confidence 70–79): Breakout valid dengan `volume_ratio` antara `1.20–1.49` atau retest dangkal di level yang ditembus selama R:R tetap >= 2.0.\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area penutupan breakout atau retest dangkal batas level yang ditembus.\n   - Stop Loss: di dalam area range konsolidasi / di balik level breakout dengan buffer ATR (sekitar 0.4x–0.6x ATR) agar aman dari noise.\n   - Take Profit: berdasarkan proyeksi lebar range konsolidasi atau area likuiditas / resistance-support mayor berikutnya.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 2.0. Jika tidak mencapai 2.0 secara realistis, wajib NO_TRADE.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika volume_ratio < 1.2, terlihat fakeout/wick penolakan besar, struktur tidak jelas, konflik HTF ekstrem, atau confidence objektif < 70.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "BREAKOUT_MOMENTUM".\n',
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
  'Anda adalah analis kuantitatif Crypto Futures profesional yang berfokus pada perdagangan range dan ekstrem momentum.\nStrategi Anda saat ini adalah: MEAN_REVERSION_SCALP (Pantulan Support/Resistance saat Kondisi Ranging).\n\nATURAN EVALUASI KETAT:\n1. Syarat Kondisi Pasar (Range / Non-Trending Kuat):\n   - Strategi ini optimal saat `market_regime` adalah `"RANGING"` (`FLAT_RANGING` atau `MIXED` dengan range jelas dan harga memantul di antara batas S/R).\n   - Jika pasar sedang trending searah sangat kuat atau `HIGH_VOLATILITY_CHOP` liar tanpa batas range jelas, wajib pilih NO_TRADE.\n2. Syarat Sinyal Pantulan:\n   - LONG: Harga berada di dekat `nearest_support` / lower range dengan tanda perlambatan jual (rejection wick bawah / `swept_prior_low = true`, candle berbalik bullish) DAN RSI 14 / DSS LTF (`dss_cross_up = true`) mulai jenuh jual (ekstrem `< 30` bernilai A-Grade 80+; atau `30–38` yang mulai berbalik naik `rsi14 > prev_rsi14` untuk B-Grade 70–79).\n   - SHORT: Harga berada di dekat `nearest_resistance` / upper range dengan tanda perlambatan beli (rejection wick atas / `swept_prior_high = true`, candle berbalik bearish) DAN RSI 14 / DSS LTF (`dss_cross_down = true`) mulai jenuh beli (ekstrem `> 70` bernilai A-Grade 80+; atau `62–70` yang mulai berbalik turun `rsi14 < prev_rsi14` untuk B-Grade 70–79).\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area pantulan support/resistance saat ini.\n   - Stop Loss: letakkan ketat di luar batas range (sekitar 0.5x–0.8x ATR 14 LTF di luar swing support/resistance).\n   - Take Profit: target konservatif ke area mid-range (EMA 21/50) atau sisi range yang berlawanan.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.5.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika market sedang trending kuat melawan arah, belum ada tanda pantulan/pembalikan RSI maupun wick di batas S/R, terdapat breakdown/breakout bervolume besar (`volume_ratio >= 1.8`), atau confidence objektif < 70.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "MEAN_REVERSION_SCALP".\n',
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
  'Anda adalah AI Crypto Futures Scalping Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe sesuai field interval, dan ltf_15m sebagai konteks Lower Timeframe eksekusi sesuai field interval) menggunakan strategi SCALP_LIQUIDITY_SWEEP_REVERSAL (Stop Hunt Reversal).\n\nEvaluasi setup mengikuti aturan bernomor berikut (pisahkan syarat WAJIB dari bonus konfluensi A-Grade agar setup B-Grade tetap mendapat skor objektif 70-79):\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas memadai dari quote_volume_24h dan open_interest_hold_vol.\n- Periksa selisih last_price terhadap fair_price dan index_price; hindari eksekusi jika terjadi anomali spread ekstrem.\n- Perhatikan funding_rate dan posisi last_price terhadap high_24h dan low_24h sebagai area likuiditas harian potensial.\n\n2. ANALISIS KONTEKS & STRUKTUR HTF (htf_1h):\n- Identifikasi bias makro dari ema_bias (BULLISH_ALIGNED, BEARISH_ALIGNED, FLAT_RANGING, MIXED) serta jarak harga terhadap EMA (dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct).\n- Setup LONG optimal saat HTF berada di FLAT_RANGING, BULLISH_ALIGNED (pullback menyapu likuiditas bawah), atau BEARISH_ALIGNED yang sudah overextended (dist_to_ema21_pct negatif dan rsi14/dss rendah di dekat nearest_support / recent_swing_low).\n- Setup SHORT optimal saat HTF berada di FLAT_RANGING, BEARISH_ALIGNED (rally menyapu likuiditas atas), atau BULLISH_ALIGNED yang sudah overextended (dist_to_ema21_pct positif dan rsi14/dss tinggi di dekat nearest_resistance / recent_swing_high).\n- Periksa atr_pct dan compression_ratio untuk memastikan volatilitas cukup untuk scalping namun tidak dalam kondisi choppy ekstrem tanpa arah.\n\n3. SYARAT PEMICU LIQUIDITY SWEEP DI LTF (ltf_15m):\n- Untuk LONG (Bullish Sweep / Stop Hunt Bawah):\n  a. Flag swept_prior_low = true (atau salah satu candle terbaru pada recent_candles memiliki low yang menyapu/menguji di bawah atau tepat pada prior_swing_low / recent_swing_low / nearest_support), lalu GAGAL breakdown dan close kembali di atas level tersebut.\n  b. Candle sweep memiliki ekor bawah signifikan dengan lower_wick_pct >= 35% (>= 45% bernilai A-Grade) atau penutupan bullish (is_bullish = true) di atas area sweep.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (>= 1.5 bernilai A-Grade sebagai bukti absorption kuat).\n  d. Konfirmasi momentum: rsi14 <= 42 atau berbalik naik (rsi14 > prev_rsi14) atau dss_cross_up = true (<= 35 bernilai A-Grade).\n- Untuk SHORT (Bearish Sweep / Stop Hunt Atas):\n  a. Flag swept_prior_high = true (atau salah satu candle terbaru pada recent_candles memiliki high yang menyapu/menguji di atas atau tepat pada prior_swing_high / recent_swing_high / nearest_resistance), lalu GAGAL breakout dan close kembali di bawah level tersebut.\n  b. Candle sweep memiliki ekor atas signifikan dengan upper_wick_pct >= 35% (>= 45% bernilai A-Grade) atau penutupan bearish (is_bullish = false) di bawah area sweep.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (>= 1.5 bernilai A-Grade).\n  d. Konfirmasi momentum: rsi14 >= 58 atau berbalik turun (rsi14 < prev_rsi14) atau dss_cross_down = true (>= 65 bernilai A-Grade).\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle konfirmasi sweep baru saja close di dalam range dengan momentum kuat dan harga saat ini (close / last_price) masih dekat dengan area sweep.\n- Gunakan entry_type = "LIMIT" di area retest 30%-50% dari ekor candle sweep (atau tepat di level nearest_support untuk LONG / nearest_resistance untuk SHORT) jika harga sudah bergerak terlalu jauh dari titik sweep agar Risk-to-Reward tetap terjaga.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah titik terendah (low) candle sweep / recent_swing_low ditambah buffer volatilitas sebesar 0.3x hingga 0.5x atr14 LTF.\n- SHORT: Tempatkan SL di atas titik tertinggi (high) candle sweep / recent_swing_high ditambah buffer volatilitas sebesar 0.3x hingga 0.5x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada level likuiditas berlawanan yang realistis untuk scalping 15 menit - 2 jam: nearest_resistance / recent_swing_high (untuk LONG) atau nearest_support / recent_swing_low (untuk SHORT), atau level dinamis ema21 / ema50 jika melawan tren mikro.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.0 (min_rr = 2.0). Jika jarak ke target terdekat menghasilkan R:R < 2.0, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE & SKALA CONFIDENCE:\n- Gunakan skala objektif: 80-95 (A-Grade: sweep jelas + wick >=45% + volume >=1.5x + RSI ekstrem), 70-79 (B-Grade: sweep/rejection S/R valid + volume >=1.2x + R:R >=2.0 walau 1 konfluensi tidak ekstrem), < 70 (lemah).\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. Tidak ada sweep/rejection yang jelas (candle close body penuh menembus support/resistance menandakan breakout valid, bukan stop hunt).\n  b. Volume sangat lemah (volume_ratio < 1.1) saat sweep terjadi.\n  c. Terjadi konflik berat antara struktur HTF dan LTF (melawan tren HTF agresif tanpa tanda kelelahan RSI/DSS).\n  d. R:R kurang dari 2.0.\n  e. Penilaian confidence objektif Anda < 70.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SCALP_LIQUIDITY_SWEEP_REVERSAL".',
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
  'Anda adalah AI Crypto Futures Intraday Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe sesuai field interval, dan ltf_15m sebagai konteks Lower Timeframe eksekusi sesuai field interval) menggunakan strategi INTRADAY_BREAKOUT_RETEST.\n\nEvaluasi setup mengikuti aturan bernomor berikut (pisahkan syarat WAJIB dari bonus konfluensi A-Grade agar setup B-Grade tetap mendapat skor objektif 70-79):\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas kuat berdasarkan quote_volume_24h dan open_interest_hold_vol agar breakout tidak mudah dimanipulasi.\n- Periksa kewajaran last_price terhadap fair_price dan index_price; hindari eksekusi jika terjadi deviasi ekstrem.\n- Catat level high_24h dan low_24h sebagai level kunci likuiditas intraday, serta periksa change_24h_pct dan funding_rate untuk memastikan tidak terlalu ekstrem melawan arah breakout.\n\n2. ANALISIS TREN & KOMPRESI VOLATILITAS HTF (htf_1h):\n- Setup LONG valid jika ema_bias HTF adalah BULLISH_ALIGNED (atau transisi dari FLAT_RANGING/MIXED dengan close di atas ema50/ema200) serta dist_to_ema21_pct tidak terlalu overextended.\n- Setup SHORT valid jika ema_bias HTF adalah BEARISH_ALIGNED (atau transisi dari FLAT_RANGING/MIXED dengan close di bawah ema50/ema200) serta dist_to_ema21_pct tidak terlalu overextended.\n- Kompresi volatilitas (compression_ratio rendah) sebelum ekspansi bernilai bonus konfluensi kuat A-Grade (80+), bukan syarat gugur bila breakout S/R dan volume solid.\n- Konfirmasi momentum HTF: rsi14 searah tren (> 48 untuk LONG dan belum > 80; < 52 untuk SHORT dan belum < 20) serta atr_pct memadai untuk target intraday.\n\n3. SYARAT PEMICU BREAKOUT & RETEST DI LTF (ltf_15m):\n- Untuk LONG (Bullish Breakout & Retest):\n  a. Candle pemicu pada recent_candles menembus dan close di atas level kunci (nearest_resistance, recent_swing_high, atau high_24h) dengan is_bullish = true, body_pct minimal >= 50% (>= 60% bernilai A-Grade), dan upper_wick_pct <= 35% (<= 25% bernilai A-Grade).\n  b. Konfirmasi volume: volume_ratio >= 1.25 (>= 1.5 bernilai A-Grade).\n  c. Konfirmasi momentum: rsi14 > prev_rsi14 (atau dss_cross_up = true) di zona momentum sehat (50 - 78).\n  d. Jika harga sedang melakukan retest ke bekas level breakout (nearest_support / high_24h), candle retest bertahan di atas level tersebut dengan ekor bawah (lower_wick_pct) mendukung.\n- Untuk SHORT (Bearish Breakdown & Retest):\n  a. Candle pemicu pada recent_candles menembus dan close di bawah level kunci (nearest_support, recent_swing_low, atau low_24h) dengan is_bullish = false, body_pct minimal >= 50% (>= 60% bernilai A-Grade), dan lower_wick_pct <= 35% (<= 25% bernilai A-Grade).\n  b. Konfirmasi volume: volume_ratio >= 1.25 (>= 1.5 bernilai A-Grade).\n  c. Konfirmasi momentum: rsi14 < prev_rsi14 (atau dss_cross_down = true) di zona momentum sehat (22 - 50).\n  d. Jika harga sedang melakukan retest ke bekas level breakdown (nearest_resistance / low_24h), candle retest tertahan di bawah level tersebut.\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "LIMIT" tepat di area retest level kunci yang baru ditembus (bekas nearest_resistance / high_24h untuk LONG, atau bekas nearest_support / low_24h untuk SHORT) jika candle breakout sudah bergerak menjauh agar Risk-to-Reward optimal.\n- Gunakan entry_type = "MARKET" jika harga sudah menyelesaikan retest yang valid atau baru saja close breakout dekat level kunci dengan momentum volume tinggi.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF atau di bawah low candle breakout/retest ditambah buffer volatilitas sebesar 0.5x hingga 1.0x atr14 LTF.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF atau di atas high candle breakout/retest ditambah buffer volatilitas sebesar 0.5x hingga 1.0x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada level struktur HTF berikutnya (nearest_resistance / recent_swing_high HTF untuk LONG; nearest_support / recent_swing_low HTF untuk SHORT) atau proyeksi 2x - 3x atr14 HTF yang realistis dicapai dalam 2 - 12 jam.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.0 (min_rr = 2.0). Jika ruang gerak menuju rintangan terdekat menghasilkan R:R < 2.0, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE & SKALA CONFIDENCE:\n- Gunakan skala objektif: 80-95 (A-Grade: kompresi + breakout body >=60% + volume >=1.5x + HTF aligned), 70-79 (B-Grade: breakout/retest S/R valid + volume >=1.25x + R:R >=2.0), < 70 (lemah).\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. Struktur breakout lemah (body_pct kecil atau wick penolakan berlawanan dominan menandakan fakeout).\n  b. Breakout tidak didukung volume (volume_ratio < 1.15).\n  c. Konflik langsung antara arah breakout LTF dan tren HTF ekstrem berlawanan.\n  d. Harga terlalu overextended sehingga R:R kurang dari 2.0.\n  e. Penilaian confidence objektif Anda < 70.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "INTRADAY_BREAKOUT_RETEST".',
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
  'Anda adalah AI Crypto Futures Swing Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe sesuai field interval, dan ltf_15m sebagai konteks Lower Timeframe eksekusi sesuai field interval) menggunakan strategi SWING_CONTRARIAN_SQUEEZE (Short/Long Squeeze Reversal).\n\nEvaluasi setup mengikuti aturan bernomor berikut (pisahkan syarat WAJIB dari bonus konfluensi A-Grade agar setup B-Grade tetap mendapat skor objektif 70-79):\n\n1. FILTER LIKUIDITAS, FUNDING RATE & OPEN INTEREST (market_ticker):\n- Pastikan likuiditas sangat memadai dari quote_volume_24h dan open_interest_hold_vol yang tinggi (sebagai proksi potensi likuidasi/squeeze bersama funding_rate tanpa feed likuidasi terpisah).\n- Periksa deviasi last_price terhadap fair_price dan index_price; pastikan tidak ada anomali spread ekstrem yang mengganggu eksekusi.\n- Syarat Contrarian Squeeze:\n  a. Untuk LONG (Potensi Short Squeeze): funding_rate bernilai negatif (negatif ekstrem bernilai A-Grade 80+) sementara harga mulai tertahan di dekat low_24h atau area support kunci.\n  b. Untuk SHORT (Potensi Long Squeeze): funding_rate bernilai positif cukup tinggi (positif ekstrem bernilai A-Grade 80+) sementara harga mulai tertahan di dekat high_24h atau area resistance kunci.\n- Perhatikan change_24h_pct untuk menilai apakah pergerakan harian sudah terlalu overextended sehingga rawan terjadi pembalikan tajam.\n\n2. ANALISIS STRUKTUR & KONDISI HTF (htf_1h):\n- Evaluasi posisi close terhadap level kunci nearest_support, nearest_resistance, recent_swing_low, dan recent_swing_high:\n  a. Setup LONG: Harga berada dekat dengan nearest_support atau recent_swing_low (dist_to_support_pct kecil/ketat), menunjukkan area demand kuat yang mampu memicu short covering.\n  b. Setup SHORT: Harga berada dekat dengan nearest_resistance atau recent_swing_high (dist_to_resistance_pct kecil/ketat), menunjukkan area supply kuat yang mampu memicu long squeeze.\n- Analisis ema_bias serta jarak ke EMA (dist_to_ema21_pct, dist_to_ema50_pct, dist_to_ema200_pct). Setup contrarian valid saat FLAT_RANGING, MIXED, atau saat tren HTF overextended jauh dari ema21/ema50 dan mulai kehilangan tenaga.\n- Konfluensi tambahan: rsi14/dss HTF di zona jenuh (<= 38 LONG / >= 62 SHORT; ekstrem <= 35 / >= 65 bernilai A-Grade).\n\n3. SYARAT PEMICU REVERSAL & MOMENTUM DI LTF (ltf_15m):\n- Untuk LONG (Konfirmasi Short Squeeze):\n  a. Pada recent_candles, muncul candle konfirmasi reversal bullish di area nearest_support / recent_swing_low: is_bullish = true dengan body_pct >= 45% (>= 55% A-Grade) atau rejection lower_wick_pct >= 35% (>= 45% A-Grade) yang close di atas support.\n  b. Konfirmasi momentum: rsi14 > prev_rsi14 atau dss_cross_up = true.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (>= 1.4 bernilai A-Grade).\n- Untuk SHORT (Konfirmasi Long Squeeze):\n  a. Pada recent_candles, muncul candle konfirmasi reversal bearish di area nearest_resistance / recent_swing_high: is_bullish = false dengan body_pct >= 45% (>= 55% A-Grade) atau rejection upper_wick_pct >= 35% (>= 45% A-Grade) yang close di bawah resistance.\n  b. Konfirmasi momentum: rsi14 < prev_rsi14 atau dss_cross_down = true.\n  c. Konfirmasi volume: volume_ratio >= 1.2 (>= 1.4 bernilai A-Grade).\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle konfirmasi reversal LTF baru saja close dengan momentum volume tinggi dan harga saat ini (close / last_price) masih berada di dekat area support/resistance kunci sehingga R:R tetap ideal.\n- Gunakan entry_type = "LIMIT" di area pullback/retest 30%-50% dari body/ekor candle konfirmasi LTF (atau di sekitar nearest_support untuk LONG / nearest_resistance untuk SHORT) jika harga sudah memantul cukup jauh dari titik reversal.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF/HTF atau di bawah low candle reversal ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF agar tahan terhadap noise swing.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF/HTF atau di atas high candle reversal ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP pada area likuiditas utama HTF yang realistis untuk holding 1 - 4 hari: nearest_resistance / recent_swing_high HTF atau area mean reversion ema50 / ema200 HTF (untuk LONG), serta nearest_support / recent_swing_low HTF atau ema50 / ema200 HTF (untuk SHORT), atau proyeksi 3x - 5x atr14 HTF.\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.5 (min_rr = 2.5). Jika jarak ke target terdekat menghasilkan R:R < 2.5, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE & SKALA CONFIDENCE:\n- Gunakan skala objektif: 80-95 (A-Grade: funding ekstrem + S/R ketat + reversal kuat + vol >=1.4x), 70-79 (B-Grade: bias funding contrarian + pantulan S/R LTF + R:R >=2.5), < 70 (lemah).\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. funding_rate netral atau terlalu crowded searah dengan rencana posisi.\n  b. Harga masih berada di tengah range (jauh dari nearest_support maupun nearest_resistance).\n  c. Belum ada candle konfirmasi reversal yang jelas di LTF (menangkap pisau jatuh tanpa rejection maupun pembalikan RSI/DSS).\n  d. Konflik ekstrem antara struktur HTF dan LTF (breakdown/breakout impulsif bervolume besar mematahkan S/R kunci).\n  e. R:R kurang dari 2.5 atau penilaian confidence objektif Anda < 70.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SWING_CONTRARIAN_SQUEEZE".',
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
  'Anda adalah AI Crypto Futures Swing Analyst untuk sistem MEXC AI Setup Scanner. Tugas Anda adalah menganalisis data MARKET SNAPSHOT (market_ticker, htf_1h sebagai konteks Higher Timeframe sesuai field interval, dan ltf_15m sebagai konteks Lower Timeframe eksekusi sesuai field interval) menggunakan strategi SWING_TREND_PULLBACK (Trend Following Pullback).\n\nEvaluasi setup mengikuti aturan bernomor berikut (pisahkan syarat WAJIB dari bonus konfluensi A-Grade agar setup B-Grade tetap mendapat skor objektif 70-79):\n\n1. FILTER LIKUIDITAS & KONDISI PASAR (market_ticker):\n- Pastikan likuiditas kuat dari quote_volume_24h dan open_interest_hold_vol agar pergerakan swing 2 - 5 hari berjalan sehat.\n- Periksa deviasi last_price terhadap fair_price dan index_price; hindari eksekusi jika terdapat selisih/spread ekstrem.\n- Evaluasi funding_rate dan change_24h_pct: idealnya funding_rate tidak terlalu ekstrem searah tren (menghindari posisi yang terlalu ramai/crowded) dan posisi last_price terhadap high_24h serta low_24h masih menyisakan ruang gerak searah tren.\n\n2. ANALISIS TREN BERSIH & ZONA PULLBACK HTF (htf_1h):\n- Setup LONG: Prioritaskan ema_bias = BULLISH_ALIGNED (A-Grade), atau kondisi MIXED yang konstruktif di atas ema50/ema200 (B-Grade).\n- Setup SHORT: Prioritaskan ema_bias = BEARISH_ALIGNED (A-Grade), atau kondisi MIXED yang konstruktif di bawah ema50/ema200 (B-Grade).\n- Syarat Pullback Sehat di Area Dinamis EMA21–EMA50:\n  a. Harga telah terkoreksi mendekati zona dinamis ema21 hingga ema50 (tidak overextended jauh dari EMA), sementara struktur makro ema200 tetap terjaga.\n  b. Momentum rsi14 HTF mendingin dari area ekstrem tanpa mematahkan tren utama (kisaran netral-sehat sekitar 38 - 62).\n- Nilai bonus konfluensi jika zona EMA21–EMA50 HTF berdekatan dengan nearest_support (LONG) atau nearest_resistance (SHORT).\n\n3. SYARAT PEMICU CANDLE REJECTION SEARAH TREN DI LTF (ltf_15m):\n- Untuk LONG (Bullish Continuation Rejection):\n  a. Harga di LTF menguji area dinamis ema21/ema50 atau nearest_support / recent_swing_low, lalu pada recent_candles muncul candle rebound/rejection bullish: lower_wick_pct >= 30% atau candle bullish dengan is_bullish = true dan body_pct >= 45% (>= 50% & wick >= 40% bernilai A-Grade).\n  b. Konfirmasi momentum: rsi14 > prev_rsi14 atau dss_cross_up = true.\n  c. Konfirmasi volume: volume_ratio >= 1.05 (>= 1.25 bernilai A-Grade).\n- Untuk SHORT (Bearish Continuation Rejection):\n  a. Harga di LTF menguji area dinamis ema21/ema50 atau nearest_resistance / recent_swing_high, lalu pada recent_candles muncul candle rebound/rejection bearish: upper_wick_pct >= 30% atau candle bearish dengan is_bullish = false dan body_pct >= 45% (>= 50% & wick >= 40% bernilai A-Grade).\n  b. Konfirmasi momentum: rsi14 < prev_rsi14 atau dss_cross_down = true.\n  c. Konfirmasi volume: volume_ratio >= 1.05 (>= 1.25 bernilai A-Grade).\n\n4. ATURAN PENENTUAN ENTRY:\n- Gunakan entry_type = "MARKET" jika candle rejection LTF baru saja close searah tren HTF dengan momentum jelas dan harga saat ini (close / last_price) masih sangat dekat dengan zona EMA21–EMA50.\n- Gunakan entry_type = "LIMIT" di area retest 30%-50% dari ekor/body candle rejection LTF atau tepat di sekitar ema21 / nearest_support (LONG) maupun ema21 / nearest_resistance (SHORT) jika harga sudah bergerak menjauh agar Risk-to-Reward tetap optimal.\n\n5. ATURAN STOP LOSS (SL):\n- LONG: Tempatkan SL di bawah struktur recent_swing_low LTF (atau di bawah low candle rejection & ema50) ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF agar tidak mudah terkena noise pullback.\n- SHORT: Tempatkan SL di atas struktur recent_swing_high LTF (atau di atas high candle rejection & ema50) ditambah buffer volatilitas sebesar 0.75x hingga 1.25x atr14 LTF.\n\n6. ATURAN TAKE PROFIT (TP) & MINIMUM R:R:\n- Targetkan TP secara realistis untuk holding 2 - 5 hari pada ekstensi struktur tren HTF: menembus recent_swing_high / nearest_resistance HTF menuju proyeksi range swing sebelumnya atau kelipatan 3x - 5x atr14 HTF (untuk LONG); serta menembus recent_swing_low / nearest_support HTF menuju proyeksi range atau 3x - 5x atr14 HTF (untuk SHORT).\n- Rasio Risk-to-Reward (R:R) WAJIB minimal 2.5 (min_rr = 2.5). Jika jarak ke target realistis menghasilkan R:R < 2.5, batalkan setup.\n\n7. ATURAN DISIPLIN NO_TRADE & SKALA CONFIDENCE:\n- Gunakan skala objektif: 80-95 (A-Grade: HTF aligned bersih + pullback EMA21-50 + rejection >=40% + volume >=1.25x), 70-79 (B-Grade: tren & pullback + R:R >=2.5 valid walau 1 konfluensi tambahan moderat), < 70 (lemah).\n- WAJIB memilih decision = "NO_TRADE" dan entry_type = "NONE" jika salah satu kondisi berikut terjadi:\n  a. HTF FLAT_RANGING datar tanpa tren maupun struktur swing yang jelas.\n  b. Harga terlalu overextended jauh dari EMA21-EMA50 atau pullback sudah mematahkan struktur utama (menembus jauh melewati ema200 dengan momentum berlawanan).\n  c. Belum ada tanda pantulan/rejection LTF maupun pembalikan RSI/DSS.\n  d. Konflik berat HTF dan LTF, R:R kurang dari 2.5, atau penilaian confidence objektif Anda < 70.\n\nINSTRUKSI OUTPUT WAJIB:\n- Output WAJIB berupa JSON valid tanpa teks tambahan di luar JSON.\n- market_regime harus salah satu dari: "TRENDING_UP", "TRENDING_DOWN", "RANGING", "HIGH_VOLATILITY_CHOP".\n- decision harus salah satu dari: "LONG", "SHORT", "NO_TRADE".\n- entry_type harus salah satu dari: "MARKET", "LIMIT", "NONE".\n- strategy_used HARUS persis sama dengan "SWING_TREND_PULLBACK".',
  2.50,
  0,
  0
);
