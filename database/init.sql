-- ============================================================
--  FILE    : database/init.sql
--  FUNGSI  : Inisialisasi database untuk Sistem Monitoring Arus Listrik Mesin Pabrik
--  CARA    : Jalankan di pgAdmin (Query Tool) atau psql
-- ============================================================

-- ============================================================
-- TABEL UTAMA: logs_mesin
-- ============================================================
CREATE TABLE IF NOT EXISTS logs_mesin (
    id              SERIAL PRIMARY KEY,
    nama_mesin      VARCHAR(100) NOT NULL,
    nilai_arus      NUMERIC(10, 3) NOT NULL,
    status_mesin    VARCHAR(20) NOT NULL DEFAULT 'NORMAL'
                    CHECK (status_mesin IN ('NORMAL', 'WARNING', 'CRITICAL', 'OFFLINE')),
    batas_arus_max  NUMERIC(10, 3),
    lokasi          VARCHAR(150),
    keterangan      TEXT,
    waktu_simpan    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    waktu_sensor    TIMESTAMPTZ
);

-- INDEX
CREATE INDEX IF NOT EXISTS idx_logs_nama_mesin    ON logs_mesin (nama_mesin);
CREATE INDEX IF NOT EXISTS idx_logs_waktu_simpan  ON logs_mesin (waktu_simpan DESC);
CREATE INDEX IF NOT EXISTS idx_logs_mesin_waktu   ON logs_mesin (nama_mesin, waktu_simpan DESC);
CREATE INDEX IF NOT EXISTS idx_logs_status        ON logs_mesin (status_mesin);

-- ============================================================
-- TABEL REFERENSI: daftar_mesin
-- ============================================================
CREATE TABLE IF NOT EXISTS daftar_mesin (
    id                  SERIAL PRIMARY KEY,
    nama_mesin          VARCHAR(100) UNIQUE NOT NULL,
    -- nama tampilan bebas diubah, default dari nama_mesin
    nama_display        VARCHAR(150),
    tipe_mesin          VARCHAR(100),
    lokasi              VARCHAR(150),
    batas_arus_max      NUMERIC(10, 3) NOT NULL DEFAULT 20.0,
    batas_arus_warning  NUMERIC(10, 3) NOT NULL DEFAULT 15.0,
    -- topic MQTT khusus per mesin; NULL = pakai topic global dari .env
    mqtt_topic          VARCHAR(255),
    aktif               BOOLEAN DEFAULT TRUE,
    dibuat_pada         TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- DATA AWAL
-- ============================================================
INSERT INTO daftar_mesin (nama_mesin, nama_display, tipe_mesin, lokasi, batas_arus_max, batas_arus_warning)
VALUES
    ('Mesin_CNC_01',      'Mesin CNC 01',      'CNC Milling',    'Lantai 1 - Zona A', 25.0, 20.0),
    ('Mesin_CNC_02',      'Mesin CNC 02',      'CNC Turning',    'Lantai 1 - Zona A', 25.0, 20.0),
    ('Conveyor_A',        'Conveyor A',         'Belt Conveyor',  'Lantai 1 - Zona B', 15.0, 12.0),
    ('Conveyor_B',        'Conveyor B',         'Belt Conveyor',  'Lantai 2 - Zona A', 15.0, 12.0),
    ('Kompresor_01',      'Kompresor 01',       'Air Compressor', 'Ruang Utilitas',    30.0, 25.0),
    ('Pompa_Hidrolik_01', 'Pompa Hidrolik 01',  'Hydraulic Pump', 'Lantai 2 - Zona B', 20.0, 16.0)
ON CONFLICT (nama_mesin) DO NOTHING;

-- ============================================================
-- VIEW: Status terkini
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
-- VIEW: Statistik harian
-- ============================================================
CREATE OR REPLACE VIEW v_statistik_harian AS
SELECT
    nama_mesin,
    DATE(waktu_simpan)                         AS tanggal,
    COUNT(*)                                   AS total_pembacaan,
    ROUND(AVG(nilai_arus)::NUMERIC, 3)         AS rata_rata_arus,
    ROUND(MAX(nilai_arus)::NUMERIC, 3)         AS puncak_arus,
    ROUND(MIN(nilai_arus)::NUMERIC, 3)         AS arus_minimum,
    COUNT(*) FILTER (WHERE status_mesin = 'WARNING')  AS total_warning,
    COUNT(*) FILTER (WHERE status_mesin = 'CRITICAL') AS total_critical
FROM logs_mesin
GROUP BY nama_mesin, DATE(waktu_simpan)
ORDER BY tanggal DESC, nama_mesin;

-- Verifikasi
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;

SELECT nama_mesin, nama_display, mqtt_topic FROM daftar_mesin;