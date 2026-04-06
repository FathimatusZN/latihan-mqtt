-- ============================================================
--  FILE    : database/migrate_v1_to_v2.sql
--  FUNGSI  : Migrasi dari schema v1 (logs_mesin + daftar_mesin)
--            ke schema v2 (devices + tags + logs)
--  CARA    : Jalankan di pgAdmin / psql SETELAH init.sql v2
--  CATATAN : Script ini NON-DESTRUCTIVE — tabel lama tidak
--            dihapus sampai kamu yakin migrasi berhasil.
-- ============================================================

-- ============================================================
-- LANGKAH 1: Migrasikan daftar_mesin → devices
-- ============================================================
INSERT INTO devices (device_id, nama_display, tipe, lokasi, factory_id, aktif, dibuat_pada)
SELECT
    -- Gunakan nama_mesin sebagai device_id (sudah unique)
    nama_mesin                                       AS device_id,
    COALESCE(nama_display, REPLACE(nama_mesin, '_', ' ')) AS nama_display,
    tipe_mesin                                       AS tipe,
    lokasi,
    'efortech'                                       AS factory_id,
    aktif,
    dibuat_pada
FROM daftar_mesin
ON CONFLICT (device_id) DO NOTHING;

-- Verifikasi
SELECT 'devices migrated:' AS info, COUNT(*) FROM devices;

-- ============================================================
-- LANGKAH 2: Buat tags dari daftar_mesin
--            Setiap mesin lama → satu tag "current"
--            (karena v1 hanya monitor arus / current)
-- ============================================================
INSERT INTO tags (
    device_id, tag_name, satuan, deskripsi,
    mqtt_topic, batas_warning, batas_critical, aktif
)
SELECT
    nama_mesin                                       AS device_id,
    'current'                                        AS tag_name,
    'A'                                              AS satuan,
    'Arus listrik (migrasi dari v1)'                 AS deskripsi,
    -- Gunakan topic custom per mesin jika ada, fallback ke topic global v1
    COALESCE(
        mqtt_topic,
        'pabrik/efortech/' || nama_mesin || '/current'
    )                                                AS mqtt_topic,
    batas_arus_warning                               AS batas_warning,
    batas_arus_max                                   AS batas_critical,
    aktif
FROM daftar_mesin
ON CONFLICT (device_id, tag_name) DO NOTHING;

-- Verifikasi
SELECT 'tags migrated:' AS info, COUNT(*) FROM tags;
SELECT device_id, tag_name, mqtt_topic, batas_warning, batas_critical FROM tags ORDER BY device_id;

-- ============================================================
-- LANGKAH 3: Migrasikan logs_mesin → logs
--            Petakan nilai_arus ke tag "current"
-- ============================================================
INSERT INTO logs (device_id, tag_name, value, status, mqtt_topic, ts_sensor, ts_simpan)
SELECT
    nama_mesin                                       AS device_id,
    'current'                                        AS tag_name,
    nilai_arus                                       AS value,
    status_mesin                                     AS status,
    NULL                                             AS mqtt_topic,
    waktu_sensor                                     AS ts_sensor,
    waktu_simpan                                     AS ts_simpan
FROM logs_mesin
-- Hanya migrasi data yang device_id-nya sudah ada di tabel devices
WHERE nama_mesin IN (SELECT device_id FROM devices);

-- Verifikasi
SELECT 'logs migrated:' AS info, COUNT(*) FROM logs;
SELECT device_id, tag_name, COUNT(*) AS total
FROM logs GROUP BY device_id, tag_name ORDER BY device_id;

-- ============================================================
-- LANGKAH 4: Update mqtt_topic di tags v2 agar sesuai format baru
--            Jika topic lama masih format v1 (pabrik/efortech/mesin/arus)
--            → update ke format baru per-device
-- ============================================================
UPDATE tags
SET mqtt_topic = 'pabrik/efortech/' || device_id || '/current'
WHERE tag_name = 'current'
  AND mqtt_topic = 'pabrik/efortech/mesin/arus';  -- topic global v1

-- Verifikasi final
SELECT device_id, tag_name, mqtt_topic FROM tags ORDER BY device_id;

-- ============================================================
-- LANGKAH 5 (OPSIONAL): Rename tabel lama untuk backup
--            Jalankan ini HANYA setelah yakin migrasi berhasil
-- ============================================================
-- ALTER TABLE logs_mesin  RENAME TO logs_mesin_v1_backup;
-- ALTER TABLE daftar_mesin RENAME TO daftar_mesin_v1_backup;

-- ============================================================
-- ROLLBACK: Jika ingin kembali ke v1, jalankan ini
-- ============================================================
-- ALTER TABLE logs_mesin_v1_backup  RENAME TO logs_mesin;
-- ALTER TABLE daftar_mesin_v1_backup RENAME TO daftar_mesin;
-- DROP TABLE IF EXISTS logs CASCADE;
-- DROP TABLE IF EXISTS tags CASCADE;
-- DROP TABLE IF EXISTS devices CASCADE;
-- DROP TABLE IF EXISTS unknown_messages CASCADE;