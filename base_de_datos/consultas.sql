/*
    @file consultas.sql
    @author Sergio Real, Felix Piedrasanta, Diego Jimenez, Enric Talens
    @brief SQL file to create the queries for the PR2-A1 project.
*/

/*
 --------------------------------------------------------------------------------
    MAIN TABLES
 --------------------------------------------------------------------------------
*/

INSERT INTO material_no_clasificado (lote_id, fecha_inicio, fecha_fin, total_tapas_entrada, total_tapas_clasificadas, observaciones) 
VALUES ('L01', '2024-01-01', '2024-01-31', 1000, 800, 'LOTE DE ALTA CALIDAD.');

-- lote_id: char(5) PRIMARY KEY,
-- fecha_inicio: date NOT NULL,
-- fecha_fin: date NOT NULL,
-- total_tapas_entrada: int NOT NULL,
-- total_tapas_clasificadas: int,
-- observaciones: varchar(200)

INSERT INTO operario (operario_id, nombre, apellido) 
VALUES (1, 'Sergio', 'Real');

-- operario_id: int PRIMARY KEY,
-- nombre: varchar(100) NOT NULL,
-- apellido: varchar(100) NOT NULL

-- Corrección: El proveedor ahora solo recibe sus 4 columnas principales
INSERT INTO proveedor (num_proveedor, cif_nif, nombre, certificacion_iso)
VALUES ('PR01', 'B12345678', 'Proveedor Uno', true);

-- num_proveedor char(5) PRIMARY KEY,
-- cif_nif varchar(20) NOT NULL UNIQUE,
-- nombre varchar(100) NOT NULL,
-- certificacion_iso boolean NOT NULL

/*
 --------------------------------------------------------------------------------
    DEPENDENT TABLES
 --------------------------------------------------------------------------------
*/

-- Palet depende del operario
INSERT INTO palet(palet_id, codigo_palet, color_id, estado, operario_cierre_id) 
VALUES (1, 'P01', 'C01', false, 1);

-- palet_id: int PRIMARY KEY,
-- codigo_palet: char(10) NOT NULL UNIQUE,
-- color_id: char(5) NOT NULL,
-- estado: bool,
-- operario_cierre_id: int

-- Caja depende del palet
INSERT INTO caja (caja_id, color, codigo_etiqueta, estado, palet_id) 
VALUES ('C01', 'RED', '243324234', false, 1);

-- caja_id: char(5) PRIMARY KEY, 
-- color VARCHAR(20) NOT NULL, 
-- codigo_etiqueta char(10) NOT NULL, 
-- estado: bool
-- palet_id: int,

/*
 --------------------------------------------------------------------------------
    AUXILIARY TABLES
 --------------------------------------------------------------------------------
*/

INSERT INTO proveedor_direccion (proveedor, direccion) VALUES ('PR01', 'Calle 123, Ciudad');
-- proveedor: char(5),
-- direccion: varchar(200)

INSERT INTO proveedor_tlf (proveedor, tlf_contacto) VALUES ('PR01', '123456789');
-- proveedor: char(5),
-- tlf_contacto: varchar(20)

INSERT INTO proveedor_correo (proveedor, correo_electronico) VALUES ('PR01', 'proveedoruno@email.com');
-- proveedor: char(5),
-- correo_electronico: varchar(100)

INSERT INTO proveedor_categoria (proveedor, categoria) VALUES ('PR01', 'Alimentacion');
-- proveedor: char(5),
-- categoria: varchar(50)

/*
 --------------------------------------------------------------------------------
    RELATION TABLES
 --------------------------------------------------------------------------------
*/

INSERT INTO proveedor_material (proveedor, lote_id) 
VALUES ('PR01', 'L01');
-- proveedor: char(5),
-- lote_id: char(5)

INSERT INTO material_caja (lote_id, caja_id) 
VALUES ('L01', 'C01');
-- lote_id: char(5),
-- caja_id: char(5)


/*
   --------------------------------------------------------------------------------
      KPIS QUERIES
   --------------------------------------------------------------------------------
*/

-- 1. Tasa de clasificados de cada proveedor (cruce de datos de varias tablas y funciones agregadas)
SELECT p.nombre, COUNT(m.lote_id) AS total_lotes, SUM(m.total_tapas_entrada) AS total_tapas 
FROM proveedor p, proveedor_material pm, material_no_clasificado m
WHERE p.num_proveedor = pm.proveedor AND pm.lote_id = m.lote_id
GROUP BY p.num_proveedor, p.nombre;

-- 2. Lote con mayor volumen de tapas de entrada (subconsultas)
SELECT lote_id, fecha_inicio, total_tapas_entrada
FROM material_no_clasificado
WHERE total_tapas_entrada >= (SELECT MAX(total_tapas_entrada) FROM material_no_clasificado);

-- 3. Trazabilidad de operarios que han cerrado palets con cajas de color rojo (multiples subconsultas)
SELECT nombre, apellido FROM operario WHERE operario_id IN (
   SELECT operario_cierre_id FROM palet WHERE palet_id IN (
      SELECT palet_id FROM caja WHERE color = 'RED'
   )
);

-- 4. Palets con al menos 5 cajas sin clasificar (subconsultas)
SELECT p.codigo_palet, p.color_id 
FROM palet p WHERE p.estado = false AND (SELECT COUNT(*) FROM caja c WHERE c.palet_id = p.palet_id) >= 5;

-- 5. Lotes con tasa de clasificación inferior a la media (subconsultas con AGV)
SELECT lote_id, total_tapas_entrada, total_tapas_clasificadas
FROM material_no_clasificado WHERE total_tapas_clasificadas < (SELECT AVG(total_tapas_clasificadas) FROM material_no_clasificado);
