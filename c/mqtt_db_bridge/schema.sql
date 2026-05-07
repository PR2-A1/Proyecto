-- =============================================================================
--  GIIROB — Esquema de base de datos
-- =============================================================================

-- -----------------------------------------------------------------------------
--  TABLAS INDEPENDIENTES
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS proveedor (
    num_proveedor CHAR(5)     PRIMARY KEY,
    cif_nif       VARCHAR(20) NOT NULL UNIQUE,
    nombre        VARCHAR(100) NOT NULL,
    certificacion_iso BOOLEAN NOT NULL
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
    palet_id          INTEGER  PRIMARY KEY,
    codigo_palet      CHAR(10) NOT NULL UNIQUE,
    color_id          CHAR(5)  NOT NULL,
    estado            BOOLEAN  NOT NULL,
    operario_cierre_id INTEGER,
    FOREIGN KEY (operario_cierre_id) REFERENCES operario(operario_id)
);

CREATE TABLE IF NOT EXISTS caja (
    caja_id          CHAR(5)     PRIMARY KEY,
    color            VARCHAR(20) NOT NULL,
    codigo_etiqueta  CHAR(10)    NOT NULL,
    estado           BOOLEAN     NOT NULL,
    palet_id         INTEGER,
    FOREIGN KEY (palet_id) REFERENCES palet(palet_id),
    CHECK (color IN ('RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'WHITE'))
);

-- -----------------------------------------------------------------------------
--  TABLAS DEPENDIENTES DE PROVEEDOR
-- -----------------------------------------------------------------------------

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
    proveedor            CHAR(5),
    correo_electronico   VARCHAR(100),
    PRIMARY KEY (proveedor, correo_electronico),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

CREATE TABLE IF NOT EXISTS proveedor_categoria (
    proveedor CHAR(5),
    categoria VARCHAR(50),
    PRIMARY KEY (proveedor, categoria),
    FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor)
);

-- -----------------------------------------------------------------------------
--  TABLAS DE RELACIÓN
-- -----------------------------------------------------------------------------

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
