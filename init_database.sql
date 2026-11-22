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
  `strategy_used` VARCHAR(40) NOT NULL,
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
  KEY `fk_trade_setups_scan_run_id` (`scan_run_id`),
  CONSTRAINT `fk_trade_setups_scan_run_id` FOREIGN KEY (`scan_run_id`) REFERENCES `scan_runs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Audit Evaluasi Pair (NO_TRADE / Rejected by Risk & Math Guard)
CREATE TABLE IF NOT EXISTS `scan_evaluations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `scan_run_id` BIGINT NOT NULL,
  `symbol` VARCHAR(32) NOT NULL,
  `strategy_used` VARCHAR(40) NOT NULL,
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
('htf_interval', 'Min60', 'Higher Timeframe kline interval'),
('ltf_interval', 'Min15', 'Lower Timeframe kline interval'),
('kline_limit', '250', 'Jumlah candle historis per timeframe'),
('scan_interval_minutes', '15', 'Interval auto-scan dalam menit'),
('tracker_interval_seconds', '60', 'Interval pengecekan outcome setup OPEN (detik)'),
('setup_expiry_hours', '12', 'Masa berlaku setup OPEN sebelum EXPIRED (jam)'),
('active_strategies', 'TREND_PULLBACK,BREAKOUT_MOMENTUM,MEAN_REVERSION_SCALP', 'Daftar strategi aktif'),
('min_24h_quote_volume', '5000000', 'Filter minimal volume quote 24 jam (USDT)'),
('max_24h_quote_volume', '0', 'Filter maksimal volume quote 24 jam (USDT, 0 = tanpa batas)'),
('min_atr_pct', '0.25', 'Pre-filter minimal ATR% LTF'),
('max_atr_pct', '8.0', 'Pre-filter maksimal ATR% LTF'),
('min_confidence', '75', 'Minimal confidence AI untuk lolos Risk Guard');

-- Seed awal strategi bawaan (otomatis juga di-seed oleh aplikasi dari prompts/*.txt)
INSERT IGNORE INTO `strategies` (
  `name`, `display_name`, `description`, `trade_style`, `holding_period`,
  `suggested_htf`, `suggested_ltf`, `suggested_kline_limit`, `suggested_expiry_hours`,
  `prompt_text`, `min_rr`, `is_active`, `is_builtin`
) VALUES
(
  'TREND_PULLBACK',
  'Trend Pullback (Intraday)',
  'Intraday trend following & pullback ke EMA 21/50 / flip zone searah tren HTF (min R:R 1.8).',
  'INTRADAY',
  '4 - 24 Jam (Intraday)',
  'Min60',
  'Min15',
  250,
  12,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang sangat disiplin pada manajemen risiko.\nStrategi Anda saat ini adalah: TREND_PULLBACK (Intraday Trend Following & Pullback ke EMA / Flip Zone).\n\nATURAN EVALUASI KETAT:\n1. Evaluasi tren Higher Timeframe (HTF 1H / Min60) terlebih dahulu:\n   - Tentukan bias tren dari posisi harga terhadap EMA 50 dan EMA 200, keselarasan EMA 21 > EMA 50 > EMA 200 (uptrend) atau EMA 21 < EMA 50 < EMA 200 (downtrend), serta struktur swing (Higher High/Higher Low atau Lower High/Lower Low).\n   - Jika HTF sideways/choppy atau EMA 50 & EMA 200 datar saling silang tanpa struktur jelas, wajib pilih NO_TRADE.\n2. Cari pullback sehat di Lower Timeframe (LTF 15m / Min15):\n   - Tunggu harga melakukan pullback terkendali ke area EMA 21 / EMA 50 LTF atau area support/resistance flip zone yang searah dengan tren HTF.\n   - Konfirmasi tanda kelanjutan tren dari candlestick (rejection wick searah tren, body candle solid) dan RSI 14 sehat (tidak entry saat RSI sudah ekstrem jenuh searah tren; jangan FOMO mengejar harga yang sudah jauh dari EMA 21).\n3. Penentuan Level Eksekusi (LONG atau SHORT):\n   - Entry Price: harga limit di area pullback/flip zone atau market jika konfirmasi candle baru saja selesai di zona pullback.\n   - Stop Loss: letakkan di balik recent swing low (untuk LONG) atau recent swing high (untuk SHORT) ditambah buffer ATR 14 LTF sekitar 0.3x hingga 0.5x ATR.\n   - Take Profit: targetkan tepat sebelum resistance mayor berikutnya (untuk LONG) atau sebelum support mayor berikutnya (untuk SHORT).\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.8. Jika struktur level tidak memberi ruang R:R >= 1.8, wajib NO_TRADE.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", serta entry_price=null, stop_loss=null, take_profit=null, risk_reward_ratio=null jika:\n     * Terjadi konflik antara tren HTF dan struktur LTF.\n     * Harga sudah terlalu jauh extended dari EMA 21 (risiko chase/FOMO).\n     * Confidence Anda di bawah 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "TREND_PULLBACK".',
  1.80,
  1,
  1
),
(
  'BREAKOUT_MOMENTUM',
  'Breakout Momentum (Intraday / Short-Swing)',
  'Breakout konsolidasi level kunci dengan konfirmasi volume >= 1.5x MA20 (min R:R 2.0).',
  'INTRADAY_SWING',
  '4 - 48 Jam (1 - 2 Hari)',
  'Min60',
  'Min15',
  250,
  24,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang spesialis membaca ekspansi volatilitas dan volume.\nStrategi Anda saat ini adalah: BREAKOUT_MOMENTUM (Breakout Konsolidasi dengan Konfirmasi Volume >= 1.5x).\n\nATURAN EVALUASI KETAT:\n1. Deteksi Kompresi & Level Kunci:\n   - Cari kondisi konsolidasi/kompresi harga yang rapat di dekat resistance kunci (untuk potensi LONG) atau support kunci (untuk potensi SHORT) pada HTF (1H) dan LTF (15m).\n   - Perhatikan konteks derivatives: funding_rate yang tidak ekstrem berlawanan secara crowding dan open_interest (hold_vol) yang sehat mendukung kelanjutan ekspansi.\n2. Syarat Wajib Konfirmasi Breakout:\n   - Harus ada close candle tegas di luar level resistance/support kunci (bukan sekadar jarum/wick palsu).\n   - Volume Ratio LTF wajib >= 1.5x dari Volume MA20. Jika volume_ratio < 1.5, JANGAN ambil breakout (wajib NO_TRADE).\n   - RSI 14 harus mendukung momentum namun masih sehat (hindari entry jika RSI sudah overbought ekstrem > 80 untuk LONG atau oversold ekstrem < 20 untuk SHORT, serta hindari candle dengan wick penolakan besar melawan arah breakout).\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area penutupan breakout atau retest dangkal batas level yang ditembus.\n   - Stop Loss: di dalam area range konsolidasi / di balik level breakout dengan buffer ATR (sekitar 0.4x-0.6x ATR) agar aman dari noise.\n   - Take Profit: berdasarkan proyeksi lebar range konsolidasi atau area likuiditas / resistance-support mayor berikutnya.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 2.0. Jika tidak mencapai 2.0 secara realistis, wajib NO_TRADE.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika volume_ratio < 1.5, terlihat fakeout/wick penolakan besar, struktur tidak jelas, konflik timeframe, atau confidence < 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "BREAKOUT_MOMENTUM".',
  2.00,
  1,
  1
),
(
  'MEAN_REVERSION_SCALP',
  'Mean Reversion (Scalp)',
  'Pantulan Support/Resistance + RSI ekstrem khusus saat market RANGING (min R:R 1.5).',
  'SCALP',
  '1 - 6 Jam (Scalp)',
  'Min30',
  'Min5',
  250,
  6,
  'Anda adalah analis kuantitatif Crypto Futures profesional yang berfokus pada perdagangan range dan ekstrem momentum.\nStrategi Anda saat ini adalah: MEAN_REVERSION_SCALP (Pantulan Support/Resistance saat Kondisi Ranging).\n\nATURAN EVALUASI KETAT:\n1. Syarat Wajib Kondisi Pasar (RANGING Only):\n   - Strategi ini HANYA boleh aktif jika market_regime adalah "RANGING" (HTF & LTF tidak sedang trending kuat searah, EMA 21/50 relatif datar/berdekatan dan harga memantul di antara batas range yang jelas).\n   - Jika pasar sedang TRENDING_UP, TRENDING_DOWN, atau HIGH_VOLATILITY_CHOP ekstrem, wajib pilih NO_TRADE.\n2. Syarat Sinyal Pantulan:\n   - LONG: Harga berada di dekat nearest_support / lower range dengan tanda pelemahan tekanan jual (rejection wick bawah, candle berbalik positif) DAN RSI 14 LTF berada di area oversold (< 30) atau baru berbalik naik dari bawah 30.\n   - SHORT: Harga berada di dekat nearest_resistance / upper range dengan tanda pelemahan tekanan beli (rejection wick atas, candle berbalik negatif) DAN RSI 14 LTF berada di area overbought (> 70) atau baru berbalik turun dari atas 70.\n3. Penentuan Level Eksekusi:\n   - Entry Price: di area pantulan support/resistance saat ini.\n   - Stop Loss: letakkan ketat di luar batas range (sekitar 0.5x-0.8x ATR 14 LTF di luar swing support/resistance).\n   - Take Profit: target konservatif ke area mid-range (EMA 21/50) atau sisi range yang berlawanan.\n   - Minimum Risk-to-Reward Ratio (R:R) wajib >= 1.5.\n4. Disiplin NO_TRADE:\n   - Kembalikan decision="NO_TRADE", entry_type="NONE", dan kosongkan level harga (null) jika market bukan RANGING, RSI belum masuk area ekstrem yang terkonfirmasi berbalik, terdapat ancaman breakdown/breakout bervolume besar, atau confidence < 75.\n5. Output WAJIB berupa JSON valid sesuai schema yang diminta tanpa teks tambahan di luar JSON.\n   - strategy_used harus persis "MEAN_REVERSION_SCALP".',
  1.50,
  1,
  1
);
