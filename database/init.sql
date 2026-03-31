-- ============================================================
--  FILE    : database/init.sql
--  FUNGSI  : Inisialisasi database untuk Sistem Monitoring
--            Arus Listrik Mesin Pabrik
--  CARA    : Jalankan di pgAdmin (Query Tool) atau psql
-- ============================================================

-- 1. Buat database (skip jika sudah ada, buat manual di pgAdmin)
-- CREATE DATABASE monitoring_pabrik;

-- 2. Pastikan kamu sudah connect ke database yang benar
--    Di pgAdmin: klik kanan database → Query Tool

-- ============================================================
-- TABEL UTAMA: logs_mesin
-- Menyimpan setiap pembacaan arus dari mesin pabrik
-- ============================================================
CREATE TABLE IF NOT EXISTS logs_mesin (
    -- Primary key auto-increment
    id              SERIAL PRIMARY KEY,

    -- Nama atau ID mesin (contoh: "Mesin_CNC_01", "Conveyor_A")
    nama_mesin      VARCHAR(100) NOT NULL,

    -- Nilai arus listrik dalam satuan Ampere
    nilai_arus      NUMERIC(10, 3) NOT NULL,

    -- Status mesin berdasarkan nilai arus
    -- 'NORMAL'   : arus dalam batas wajar
    -- 'WARNING'  : arus mendekati batas maksimum
    -- 'CRITICAL' : arus melebihi batas aman (potensi kerusakan)
    -- 'OFFLINE'  : mesin tidak mengirim data
    status_mesin    VARCHAR(20) NOT NULL DEFAULT 'NORMAL'
                    CHECK (status_mesin IN ('NORMAL', 'WARNING', 'CRITICAL', 'OFFLINE')),

    -- Batas arus maksimum yang dikonfigurasi untuk mesin ini (Ampere)
    batas_arus_max  NUMERIC(10, 3),

    -- Lokasi mesin di pabrik (contoh: "Lantai 1 - Zona A")
    lokasi          VARCHAR(150),

    -- Pesan tambahan atau catatan dari sistem
    keterangan      TEXT,

    -- Timestamp saat data diterima oleh sistem (otomatis oleh DB)
    waktu_simpan    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Timestamp dari perangkat/sensor IoT (bisa berbeda dengan waktu_simpan)
    waktu_sensor    TIMESTAMPTZ
);

-- ============================================================
-- INDEX: Mempercepat query berdasarkan kolom yang sering difilter
-- ============================================================

-- Index untuk filter berdasarkan nama mesin (query paling umum)
CREATE INDEX IF NOT EXISTS idx_logs_nama_mesin
    ON logs_mesin (nama_mesin);

-- Index untuk filter berdasarkan rentang waktu (audit & laporan)
CREATE INDEX IF NOT EXISTS idx_logs_waktu_simpan
    ON logs_mesin (waktu_simpan DESC);

-- Index komposit: nama mesin + waktu (untuk dashboard per mesin)
CREATE INDEX IF NOT EXISTS idx_logs_mesin_waktu
    ON logs_mesin (nama_mesin, waktu_simpan DESC);

-- Index untuk filter berdasarkan status (alert monitoring)
CREATE INDEX IF NOT EXISTS idx_logs_status
    ON logs_mesin (status_mesin);

-- ============================================================
-- TABEL REFERENSI: daftar_mesin
-- Konfigurasi mesin yang terdaftar di sistem
-- ============================================================
CREATE TABLE IF NOT EXISTS daftar_mesin (
    id              SERIAL PRIMARY KEY,
    nama_mesin      VARCHAR(100) UNIQUE NOT NULL,
    tipe_mesin      VARCHAR(100),
    lokasi          VARCHAR(150),
    batas_arus_max  NUMERIC(10, 3) NOT NULL DEFAULT 20.0,  -- Ampere
    batas_arus_warning NUMERIC(10, 3) NOT NULL DEFAULT 15.0, -- Ampere
    aktif           BOOLEAN DEFAULT TRUE,
    dibuat_pada     TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- DATA AWAL: Daftar mesin yang akan dimonitor
-- ============================================================
INSERT INTO daftar_mesin (nama_mesin, tipe_mesin, lokasi, batas_arus_max, batas_arus_warning)
VALUES
    ('Mesin_CNC_01',     'CNC Milling',      'Lantai 1 - Zona A', 25.0, 20.0),
    ('Mesin_CNC_02',     'CNC Turning',      'Lantai 1 - Zona A', 25.0, 20.0),
    ('Conveyor_A',       'Belt Conveyor',    'Lantai 1 - Zona B', 15.0, 12.0),
    ('Conveyor_B',       'Belt Conveyor',    'Lantai 2 - Zona A', 15.0, 12.0),
    ('Kompresor_01',     'Air Compressor',   'Ruang Utilitas',    30.0, 25.0),
    ('Pompa_Hidrolik_01','Hydraulic Pump',   'Lantai 2 - Zona B', 20.0, 16.0)
ON CONFLICT (nama_mesin) DO NOTHING;

-- ============================================================
-- VIEW: Ringkasan status terkini setiap mesin
-- Berguna untuk dashboard monitoring
-- ============================================================
CREATE OR REPLACE VIEW v_status_terkini AS
SELECT DISTINCT ON (nama_mesin)
    nama_mesin,
    nilai_arus,
    status_mesin,
    lokasi,
    waktu_simpan AS terakhir_update
FROM logs_mesin
ORDER BY nama_mesin, waktu_simpan DESC;

-- ============================================================
-- VIEW: Statistik harian per mesin
-- ============================================================
CREATE OR REPLACE VIEW v_statistik_harian AS
SELECT
    nama_mesin,
    DATE(waktu_simpan) AS tanggal,
    COUNT(*)                        AS total_pembacaan,
    ROUND(AVG(nilai_arus)::NUMERIC, 3) AS rata_rata_arus,
    ROUND(MAX(nilai_arus)::NUMERIC, 3) AS puncak_arus,
    ROUND(MIN(nilai_arus)::NUMERIC, 3) AS arus_minimum,
    COUNT(*) FILTER (WHERE status_mesin = 'WARNING')  AS total_warning,
    COUNT(*) FILTER (WHERE status_mesin = 'CRITICAL') AS total_critical
FROM logs_mesin
GROUP BY nama_mesin, DATE(waktu_simpan)
ORDER BY tanggal DESC, nama_mesin;

-- ============================================================
-- VERIFIKASI: Cek tabel yang berhasil dibuat
-- ============================================================
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- Tampilkan daftar mesin yang sudah diinput
SELECT * FROM daftar_mesin;