-- ============================================================
--  FILE    : database/init.sql
--  FUNGSI  : Inisialisasi database - Industrial IoT Tag Architecture
--  VERSI   : 2.0 (Topic-based, Tag-aware)
-- ============================================================

-- ============================================================
-- TABEL: devices
-- Representasi perangkat fisik / sensor di lapangan
-- ============================================================
CREATE TABLE IF NOT EXISTS devices (
    id              SERIAL PRIMARY KEY,
    device_id       VARCHAR(100) UNIQUE NOT NULL,   -- "PM_001", "CONV_A"
    nama_display    VARCHAR(150),                   -- "Power Meter 001"
    tipe            VARCHAR(100),                   -- "Power Meter", "Conveyor"
    lokasi          VARCHAR(150),                   -- "Lantai 1 - Zona A"
    factory_id      VARCHAR(100) NOT NULL DEFAULT 'efortech',
    aktif           BOOLEAN NOT NULL DEFAULT TRUE,
    dibuat_pada     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    diupdate_pada   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_devices_device_id  ON devices (device_id);
CREATE INDEX IF NOT EXISTS idx_devices_factory_id ON devices (factory_id);
CREATE INDEX IF NOT EXISTS idx_devices_aktif      ON devices (aktif);

-- ============================================================
-- TABEL: tags
-- Satu device bisa punya banyak tag (current, voltage, freq, dll)
-- Tag = parameter yang dimonitor, dipetakan ke MQTT topic
-- ============================================================
CREATE TABLE IF NOT EXISTS tags (
    id              SERIAL PRIMARY KEY,
    device_id       VARCHAR(100) NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    tag_name        VARCHAR(100) NOT NULL,           -- "current", "voltage", "frequency"
    satuan          VARCHAR(30),                     -- "A", "V", "Hz"
    deskripsi       VARCHAR(200),                    -- "Arus fasa R"
    mqtt_topic      VARCHAR(255) NOT NULL,           -- "pabrik/efortech/PM_001/current"
    batas_warning   NUMERIC(12,4),                   -- nilai warning threshold
    batas_critical  NUMERIC(12,4),                   -- nilai critical threshold
    aktif           BOOLEAN NOT NULL DEFAULT TRUE,
    dibuat_pada     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (device_id, tag_name)
);

CREATE INDEX IF NOT EXISTS idx_tags_device_id   ON tags (device_id);
CREATE INDEX IF NOT EXISTS idx_tags_mqtt_topic  ON tags (mqtt_topic);
CREATE INDEX IF NOT EXISTS idx_tags_aktif       ON tags (aktif);

-- ============================================================
-- TABEL: logs
-- Time-series readings — satu baris per tag per pembacaan
-- ============================================================
CREATE TABLE IF NOT EXISTS logs (
    id              BIGSERIAL PRIMARY KEY,
    device_id       VARCHAR(100) NOT NULL,
    tag_name        VARCHAR(100) NOT NULL,
    value           NUMERIC(14,6) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'NORMAL'
                    CHECK (status IN ('NORMAL', 'WARNING', 'CRITICAL')),
    mqtt_topic      VARCHAR(255),                    -- topic asal pesan
    ts_sensor       TIMESTAMPTZ,                     -- timestamp dari payload/sensor
    ts_simpan       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_device_tag   ON logs (device_id, tag_name);
CREATE INDEX IF NOT EXISTS idx_logs_ts_simpan    ON logs (ts_simpan DESC);
CREATE INDEX IF NOT EXISTS idx_logs_device_ts    ON logs (device_id, ts_simpan DESC);
CREATE INDEX IF NOT EXISTS idx_logs_status       ON logs (status);
CREATE INDEX IF NOT EXISTS idx_logs_topic        ON logs (mqtt_topic);

-- ============================================================
-- TABEL: unknown_messages
-- Log pesan dari topic/device yang tidak dikenal
-- (audit trail + debugging)
-- ============================================================
CREATE TABLE IF NOT EXISTS unknown_messages (
    id          BIGSERIAL PRIMARY KEY,
    mqtt_topic  VARCHAR(255) NOT NULL,
    payload_raw TEXT,
    alasan      VARCHAR(200),               -- "device not found", "tag not found", dll
    ts_terima   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unknown_topic ON unknown_messages (mqtt_topic);
CREATE INDEX IF NOT EXISTS idx_unknown_ts    ON unknown_messages (ts_terima DESC);

-- ============================================================
-- DATA AWAL: devices
-- ============================================================
INSERT INTO devices (device_id, nama_display, tipe, lokasi, factory_id) VALUES
    ('PM_001',   'Power Meter 001',    'Power Meter',    'Lantai 1 - Zona A', 'efortech'),
    ('PM_002',   'Power Meter 002',    'Power Meter',    'Lantai 1 - Zona A', 'efortech'),
    ('CONV_A',   'Conveyor A',         'Belt Conveyor',  'Lantai 1 - Zona B', 'efortech'),
    ('CONV_B',   'Conveyor B',         'Belt Conveyor',  'Lantai 2 - Zona A', 'efortech'),
    ('COMP_01',  'Kompresor 01',       'Air Compressor', 'Ruang Utilitas',    'efortech'),
    ('PUMP_H01', 'Pompa Hidrolik 01',  'Hydraulic Pump', 'Lantai 2 - Zona B', 'efortech')
ON CONFLICT (device_id) DO NOTHING;

-- ============================================================
-- DATA AWAL: tags
-- Format topic: pabrik/{factory_id}/{device_id}/{tag_name}
-- ============================================================

-- Power Meter 001
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('PM_001', 'current',   'A',   'Arus listrik',       'pabrik/efortech/PM_001/current',   20.0, 25.0),
    ('PM_001', 'voltage',   'V',   'Tegangan listrik',   'pabrik/efortech/PM_001/voltage',   240.0, 250.0),
    ('PM_001', 'frequency', 'Hz',  'Frekuensi jaringan', 'pabrik/efortech/PM_001/frequency', 51.0,  52.0)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Power Meter 002
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('PM_002', 'current',   'A',  'Arus listrik',       'pabrik/efortech/PM_002/current',   20.0, 25.0),
    ('PM_002', 'voltage',   'V',  'Tegangan listrik',   'pabrik/efortech/PM_002/voltage',   240.0, 250.0)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Conveyor A
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('CONV_A', 'current',   'A',    'Arus motor conveyor',  'pabrik/efortech/CONV_A/current',   12.0, 15.0),
    ('CONV_A', 'speed',     'RPM',  'Kecepatan conveyor',   'pabrik/efortech/CONV_A/speed',     800.0, 900.0)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Conveyor B
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('CONV_B', 'current',   'A',  'Arus motor conveyor',  'pabrik/efortech/CONV_B/current',   12.0, 15.0)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Kompresor 01
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('COMP_01', 'current',   'A',   'Arus kompresor',       'pabrik/efortech/COMP_01/current',   25.0, 30.0),
    ('COMP_01', 'pressure',  'bar', 'Tekanan udara output', 'pabrik/efortech/COMP_01/pressure',  7.5,  8.5)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Pompa Hidrolik
INSERT INTO tags (device_id, tag_name, satuan, deskripsi, mqtt_topic, batas_warning, batas_critical) VALUES
    ('PUMP_H01', 'current',  'A',   'Arus pompa',         'pabrik/efortech/PUMP_H01/current',  16.0, 20.0),
    ('PUMP_H01', 'pressure', 'bar', 'Tekanan hidrolik',   'pabrik/efortech/PUMP_H01/pressure', 180.0, 200.0)
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- ============================================================
-- VIEW: status terkini per tag per device
-- ============================================================
CREATE OR REPLACE VIEW v_tag_status AS
SELECT DISTINCT ON (l.device_id, l.tag_name)
    l.device_id,
    d.nama_display,
    d.lokasi,
    d.factory_id,
    l.tag_name,
    t.satuan,
    t.deskripsi       AS tag_deskripsi,
    t.batas_warning,
    t.batas_critical,
    l.value,
    l.status,
    l.ts_sensor,
    l.ts_simpan       AS terakhir_update
FROM logs l
JOIN devices d ON d.device_id = l.device_id
JOIN tags    t ON t.device_id = l.device_id AND t.tag_name = l.tag_name
ORDER BY l.device_id, l.tag_name, l.ts_simpan DESC;

-- ============================================================
-- VIEW: statistik harian per tag
-- ============================================================
DROP VIEW IF EXISTS v_statistik_harian;

CREATE VIEW v_statistik_harian AS
SELECT
    device_id,
    tag_name,
    DATE(ts_simpan)                             AS tanggal,
    COUNT(*)                                    AS total_pembacaan,
    ROUND(AVG(value)::NUMERIC, 4)               AS rata_rata,
    ROUND(MAX(value)::NUMERIC, 4)               AS nilai_max,
    ROUND(MIN(value)::NUMERIC, 4)               AS nilai_min,
    COUNT(*) FILTER (WHERE status = 'WARNING')  AS total_warning,
    COUNT(*) FILTER (WHERE status = 'CRITICAL') AS total_critical
FROM logs
GROUP BY device_id, tag_name, DATE(ts_simpan)
ORDER BY tanggal DESC, device_id, tag_name;

-- Verifikasi
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;

SELECT d.device_id, d.nama_display, t.tag_name, t.mqtt_topic
FROM devices d
JOIN tags t ON t.device_id = d.device_id
ORDER BY d.device_id, t.tag_name;