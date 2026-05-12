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

-- KPI 1. Tasa de clasificación de tapas por lote
SELECT lote_id,
       total_tapas_entrada,
       total_tapas_clasificadas
FROM material_no_clasificado
WHERE total_tapas_entrada > 0
ORDER BY total_tapas_clasificadas ASC;

-- KPI 2. Tiempo medio de procesamiento de lotes completados
SELECT AVG(DATEDIFF(fecha_fin, fecha_inicio)) 
           AS media_dias_procesamiento
FROM material_no_clasificado
WHERE fecha_fin IS NOT NULL;

-- KPI 3. Número de cajas completadas frente al total generadas
SELECT COUNT(*) AS total_cajas,
       (SELECT COUNT(*) 
        FROM caja 
        WHERE estado = TRUE) AS cajas_completadas
FROM caja;

-- KPI 4. Palets completados asignados por operario
SELECT O.operario_id,
       O.nombre,
       O.apellido,
       COUNT(P.palet_id) AS palets_asignados
FROM operario O, palet P
WHERE P.operario_cierre_id = O.operario_id
AND   P.estado = TRUE
GROUP BY O.operario_id, O.nombre, O.apellido
ORDER BY palets_asignados DESC;

-- KPI 5. Volumen total de tapas aportado por cada proveedor
SELECT P.num_proveedor,
       P.nombre,
       SUM(M.total_tapas_entrada) AS total_tapas_aportadas
FROM proveedor P, proveedor_material PM, material_no_clasificado M
WHERE PM.proveedor = P.num_proveedor
AND   M.lote_id   = PM.lote_id
GROUP BY P.num_proveedor, P.nombre
ORDER BY total_tapas_aportadas DESC;
