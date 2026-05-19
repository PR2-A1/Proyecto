/*
   @file db_structure.sql
   @author Sergio Real, Felix Piedrasanta, Diego Jimenez, Enric _Talens
   @brief SQL file to create the database structure for the PR2-A1 project
*/

/*
-------------------------------------------------------------------
   IMPORTANT:
-------------------------------------------------------------------
   Before running this SQL file, make sure you have created the database with the name "pr2_a1_db".
   After, this command has to be run before the execution of this sql file for the correct creation of the tables in the pr2_a1_db schema:
       " ALTER ROLE CURRENT_USER SET search_path TO pr2_a1_db; "
*/

-------------------------------------------------------------------
-- MAIN TABLES
------------------------------------------------------------------- 

-------------------------------------------------------------------
-- TABLAS INDEPENDIENTES
-------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS proveedor (
   num_proveedor     CHAR(5)      PRIMARY KEY,
   cif_nif           VARCHAR(20)  NOT NULL UNIQUE,
   nombre            VARCHAR(100) NOT NULL,
   certificacion_iso BOOLEAN      NOT NULL
);

CREATE TABLE IF NOT EXISTS lote (
   id_lote                 CHAR(5)      PRIMARY KEY,
   fecha_inicio             DATE         NOT NULL,
   fecha_fin                DATE,
   total_tapas_entrada      INT          NOT NULL,
   total_tapas_clasificadas INT NOT NULL DEFAULT 0,
   observaciones            VARCHAR(200),
   CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio),
   CHECK (total_tapas_entrada      >= 0),
   CHECK (total_tapas_clasificadas >= 0),
   CHECK (total_tapas_clasificadas <= total_tapas_entrada)
);

CREATE TABLE IF NOT EXISTS operario (
   id_operario CHAR(5)      PRIMARY KEY,
   nombre      VARCHAR(100) NOT NULL,
   apellido    VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS palet (
   id_palet     CHAR(5)  PRIMARY KEY,
   id_color     CHAR(20)  NOT NULL,
   estado       BOOLEAN  NOT NULL,
   id_operario  CHAR(5),
   FOREIGN KEY (id_operario) REFERENCES operario(id_operario),
   CHECK (id_color IN ('RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'WHITE'))
);

CREATE TABLE IF NOT EXISTS caja (
   id_caja         CHAR(5)     PRIMARY KEY,
   color           VARCHAR(20) NOT NULL,
   codigo_etiqueta CHAR(10)    NOT NULL,
   estado          BOOLEAN     NOT NULL,
   id_palet        CHAR(5),
   FOREIGN KEY (id_palet) REFERENCES palet(id_palet),
   CHECK (color IN ('RED', 'GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'WHITE'))
);

-------------------------------------------------------------------
-- TABLAS DEPENDIENTES DE PROVEEDOR
-------------------------------------------------------------------

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

-------------------------------------------------------------------
-- TABLAS DE RELACIÓN
-------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS proveedor_material (
   proveedor CHAR(5),
   lote      CHAR(5),
   PRIMARY KEY (proveedor, lote),
   FOREIGN KEY (proveedor) REFERENCES proveedor(num_proveedor),
   FOREIGN KEY (lote)      REFERENCES lote(id_lote)
);

CREATE TABLE IF NOT EXISTS material_caja (
   lote    CHAR(5),
   id_caja CHAR(5),
   PRIMARY KEY (lote, id_caja),
   FOREIGN KEY (lote)    REFERENCES lote(id_lote),
   FOREIGN KEY (id_caja) REFERENCES caja(id_caja)
);