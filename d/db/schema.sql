-- ============================================================
-- DEMO INTEGRACION — Schema completo + datos de prueba
-- Ejecutar con:
--   psql "host=127.0.0.1 user=postgres password=postgres dbname=giirob" -f schema.sql
-- ============================================================


-- ============================================================
-- PARTE 1: SCHEMA REAL DEL PROYECTO
-- (extraído de mqtt_db_bridge/schema.sql)
-- ============================================================

CREATE TABLE IF NOT EXISTS proveedor (
    num_proveedor     CHAR(5)      PRIMARY KEY,
    cif_nif           VARCHAR(20)  NOT NULL UNIQUE,
    nombre            VARCHAR(100) NOT NULL,
    certificacion_iso BOOLEAN      NOT NULL
);

CREATE TABLE IF NOT EXISTS material_no_clasificado (
    lote_id                  CHAR(5)      PRIMARY KEY,
    fecha_inicio             DATE         NOT NULL,
    fecha_fin                DATE,
    total_tapas_entrada      INT          NOT NULL,
    total_tapas_clasificadas INT          DEFAULT 0,
    observaciones            VARCHAR(200),
    CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio),
    CHECK (total_tapas_entrada      >= 0),
    CHECK (total_tapas_clasificadas >= 0),
    CHECK (total_tapas_clasificadas <= total_tapas_entrada)
);

CREATE TABLE IF NOT EXISTS operario (
    operario_id INTEGER      PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,
    apellido    VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS palet (
    palet_id           INTEGER  PRIMARY KEY,
    codigo_palet       CHAR(10) NOT NULL UNIQUE,
    color_id           CHAR(5)  NOT NULL,
    estado             BOOLEAN  NOT NULL,
    operario_cierre_id INTEGER,
    FOREIGN KEY (operario_cierre_id) REFERENCES operario(operario_id)
);

CREATE TABLE IF NOT EXISTS caja (
    caja_id         CHAR(5)     PRIMARY KEY,
    color           VARCHAR(20) NOT NULL,
    codigo_etiqueta CHAR(10)    NOT NULL,
    estado          BOOLEAN     NOT NULL,
    palet_id        INTEGER,
    FOREIGN KEY (palet_id) REFERENCES palet(palet_id),
    CHECK (color IN ('RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'WHITE'))
);

CREATE TABLE IF NOT EXISTS proveedor_direccion (
    proveedor CHAR(5),
    direccion VARCHAR(200),
    PRIMARY KEY (proveedor, direccion),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_tlf (
    proveedor    CHAR(5),
    tlf_contacto VARCHAR(20),
    PRIMARY KEY (proveedor, tlf_contacto),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_correo (
    proveedor          CHAR(5),
    correo_electronico VARCHAR(100),
    PRIMARY KEY (proveedor, correo_electronico),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_categoria (
    proveedor CHAR(5),
    categoria VARCHAR(50),
    PRIMARY KEY (proveedor, categoria),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_material (
    proveedor CHAR(5),
    lote_id   CHAR(5),
    PRIMARY KEY (proveedor, lote_id),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor),
    FOREIGN KEY (lote_id)   REFERENCES material_no_clasificado(lote_id)
);

CREATE TABLE IF NOT EXISTS material_caja (
    lote_id CHAR(5),
    caja_id CHAR(5),
    PRIMARY KEY (lote_id, caja_id),
    FOREIGN KEY (lote_id) REFERENCES material_no_clasificado(lote_id),
    FOREIGN KEY (caja_id) REFERENCES caja(caja_id)
);


-- ============================================================
-- PARTE 2: DATOS DE PRUEBA PARA EL DEMO
-- ============================================================

-- Operarios (escenario 1 — asignación de cierre de pallet)
INSERT INTO operario (operario_id, nombre, apellido) VALUES
    (1, 'Carlos', 'Martinez'),
    (2, 'Laura',  'Gomez'),
    (3, 'Miguel', 'Lopez')
ON CONFLICT (operario_id) DO NOTHING;

-- Lotes pendientes (escenario 2 — ESP32 los consulta para generar tapas)
INSERT INTO material_no_clasificado
    (lote_id, fecha_inicio, total_tapas_entrada, total_tapas_clasificadas)
VALUES
    ('L0001', CURRENT_DATE, 3, 0),
    ('L0002', CURRENT_DATE, 3, 0)
ON CONFLICT (lote_id) DO NOTHING;

-- Cajas (escenario 1 — el bridge vincula estas cajas al pallet)
-- color debe ser exactamente uno de: RED GREEN BLUE YELLOW ORANGE WHITE
-- codigo_etiqueta es CHAR(10), máximo 10 caracteres
INSERT INTO caja (caja_id, color, codigo_etiqueta, estado) VALUES
    ('C0001', 'RED',  'ETQ0000001', true),
    ('C0002', 'RED',  'ETQ0000002', true),
    ('C0003', 'BLUE', 'ETQ0000003', true)
ON CONFLICT (caja_id) DO NOTHING;
