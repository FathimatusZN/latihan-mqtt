-- ============================================================
--  FILE    : database/migrate_001_display_name_mqtt_topic.sql
--  FUNGSI  : Tambah kolom nama_display dan mqtt_topic ke tabel daftar_mesin
--  CARA    : Jalankan sekali di pgAdmin / psql
-- ============================================================

-- Tambah nama_display — nama tampilan yang bisa diubah bebas
ALTER TABLE daftar_mesin
    ADD COLUMN IF NOT EXISTS nama_display VARCHAR(150);

-- Isi nama_display dari nama_mesin yang sudah ada (replace _ dengan spasi)
UPDATE daftar_mesin
SET nama_display = REPLACE(nama_mesin, '_', ' ')
WHERE nama_display IS NULL;

-- Tambah mqtt_topic — topic khusus per mesin (NULL = pakai topic global)
ALTER TABLE daftar_mesin
    ADD COLUMN IF NOT EXISTS mqtt_topic VARCHAR(255);

-- Verifikasi
SELECT nama_mesin, nama_display, mqtt_topic FROM daftar_mesin;