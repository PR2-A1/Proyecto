/*
    @file queries.sql
    @brief SQL file to insert sample data into the database for the PR2-A1 project.
    @author Sergio Real, Felix Piedrasanta, Diego Jimenez, Enric Talens
*/

/*
-------------------------------------------------------------------
   MAIN TABLES
-------------------------------------------------------------------
*/

-- LOTES
INSERT INTO lote (id_lote, fecha_inicio, fecha_fin, total_tapas_entrada, total_tapas_clasificadas, observaciones)
VALUES 
    ('L01', '2024-01-01', '2024-01-31', 1000, 800, 'LOTE DE ALTA CALIDAD.'),
    ('L02', '2024-02-01', '2024-02-15', 2000, 2000, 'Lote completado al 100%.'),
    ('L03', '2024-03-01', '2024-03-10', 500, 450, 'Lote pequeño.'),
    ('L04', '2024-04-01', NULL, 3000, 1500, 'Lote en proceso actual.');

-- OPERARIOS
INSERT INTO operario (id_operario, nombre, apellido)
VALUES 
    ('OP01', 'Sergio', 'Real'),
    ('OP02', 'Ana', 'Lopez'),
    ('OP03', 'Luis', 'Gomez');

-- PROVEEDORES
INSERT INTO proveedor (num_proveedor, cif_nif, nombre, certificacion_iso)
VALUES 
    ('PR01', 'B12345678', 'Proveedor Uno', true),
    ('PR02', 'B87654321', 'Proveedor Dos', false),
    ('PR03', 'B11223344', 'Proveedor Tres', true);

/*
-------------------------------------------------------------------
   DEPENDENT TABLES
-------------------------------------------------------------------
*/

-- PALETS (Varios operarios y estados para el KPI 4)
INSERT INTO palet (id_palet, id_color, estado, id_operario)
VALUES 
    ('PA01', 'red', false, 'OP01'),    -- En proceso
    ('PA02', 'green', true, 'OP01'),   -- Completado por Sergio
    ('PA03', 'blue', true, 'OP02'),    -- Completado por Ana
    ('PA04', 'yellow', true, 'OP02'),  -- Completado por Ana
    ('PA05', 'orange', false, 'OP03'); -- En proceso por Luis

-- CAJAS (Varios estados para el KPI 3)
INSERT INTO caja (id_caja, color, codigo_etiqueta, estado, id_palet)
VALUES 
    ('C01', 'red', '2433242340', false, 'PA01'),
    ('C02', 'green', '2433242341', true, 'PA02'),
    ('C03', 'blue', '2433242342', true, 'PA03'),
    ('C04', 'yellow', '2433242343', true, 'PA04'),
    ('C05', 'orange', '2433242344', false, 'PA05');

/*
-------------------------------------------------------------------
   AUXILIARY TABLES
-------------------------------------------------------------------
*/

-- DIRECCIONES
INSERT INTO proveedor_direccion (proveedor, direccion)
VALUES 
    ('PR01', 'Calle 123, Ciudad'),
    ('PR02', 'Avenida 456, Villa'),
    ('PR03', 'Poligono Sur, Nave 3');

-- TELEFONOS
INSERT INTO proveedor_tlf (proveedor, tlf_contacto)
VALUES 
    ('PR01', '123456789'),
    ('PR02', '987654321'),
    ('PR03', '555666777');

-- CORREOS
INSERT INTO proveedor_correo (proveedor, correo_electronico)
VALUES 
    ('PR01', 'proveedoruno@email.com'),
    ('PR02', 'contacto@proveedordos.com'),
    ('PR03', 'ventas@proveedortres.es');

-- CATEGORIAS
INSERT INTO proveedor_categoria (proveedor, categoria)
VALUES 
    ('PR01', 'Alimentacion'),
    ('PR02', 'Plasticos Generales'),
    ('PR03', 'Reciclaje Avanzado');

/*
-------------------------------------------------------------------
   RELATION TABLES
-------------------------------------------------------------------
*/

-- RELACIÓN PROVEEDOR - LOTE (Para el KPI 5)
-- Proveedor 1 aporta L01 y L02 (Total = 3000 tapas)
-- Proveedor 2 aporta L03 (Total = 500 tapas)
-- Proveedor 3 aporta L04 (Total = 3000 tapas)
INSERT INTO proveedor_material (proveedor, lote)
VALUES 
    ('PR01', 'L01'),
    ('PR01', 'L02'),
    ('PR02', 'L03'),
    ('PR03', 'L04');

-- RELACIÓN LOTE - CAJA
INSERT INTO material_caja (lote, id_caja)
VALUES 
    ('L01', 'C01'),
    ('L02', 'C02'),
    ('L02', 'C03'),
    ('L03', 'C04'),
    ('L04', 'C05');