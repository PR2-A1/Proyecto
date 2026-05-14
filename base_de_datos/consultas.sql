/*
    @file consultas.sql
    @author Sergio Real, Felix Piedrasanta, Diego Jimenez, Enric Talens
    @brief SQL file to create the queries for the PR2-A1 project.
*/

-- Seleccionamos el esquema por defecto para evitar el error de TablePlus
SET search_path TO public;

/*
 --------------------------------------------------------------------------------
    MAIN TABLES (Tablas Independientes)
 --------------------------------------------------------------------------------
*/

-- Inserción en material_no_clasificado
INSERT INTO material_no_clasificado (lote_id, fecha_inicio, fecha_fin, total_tapas_entrada, total_tapas_clasificadas, observaciones) 
VALUES ('L01', '2024-01-01', '2024-01-31', 1000, 800, 'LOTE DE ALTA CALIDAD.');

-- Inserción en operario
INSERT INTO operario (operario_id, nombre, apellido) 
VALUES (1, 'Sergio', 'Real');

-- Inserción en proveedor
INSERT INTO proveedor (num_proveedor, cif_nif, nombre, certificacion_iso)
VALUES ('PR01', 'B12345678', 'Proveedor Uno', true);


/*
 --------------------------------------------------------------------------------
    DEPENDENT TABLES (Tablas con Claves Foráneas)
 --------------------------------------------------------------------------------
*/

-- Palet depende del operario (operario_id 1 debe existir)
INSERT INTO palet (palet_id, codigo_palet, color_id, estado, operario_cierre_id) 
VALUES (1, 'P01', 'C01', false, 1);

-- Caja depende del palet (palet_id 1 debe existir)
-- Nota: El color 'RED' está permitido por tu CHECK
INSERT INTO caja (caja_id, color, codigo_etiqueta, estado, palet_id) 
VALUES ('C01', 'RED', '243324234', false, 1);


/*
 --------------------------------------------------------------------------------
    AUXILIARY TABLES (Atributos Multivaluados de Proveedor)
 --------------------------------------------------------------------------------
*/

INSERT INTO proveedor_direccion (proveedor, direccion) 
VALUES ('PR01', 'Calle 123, Ciudad');

INSERT INTO proveedor_tlf (proveedor, tlf_contacto) 
VALUES ('PR01', '123456789');

INSERT INTO proveedor_correo (proveedor, correo_electronico) 
VALUES ('PR01', 'proveedoruno@email.com');

INSERT INTO proveedor_categoria (proveedor, categoria) 
VALUES ('PR01', 'Alimentacion');


/*
 --------------------------------------------------------------------------------
    RELATION TABLES (Tablas de Relación Muchos a Muchos)
 --------------------------------------------------------------------------------
*/

-- Relación entre Proveedor y Material
INSERT INTO proveedor_material (proveedor, lote_id) 
VALUES ('PR01', 'L01');

-- Relación entre Material y Caja
INSERT INTO material_caja (lote_id, caja_id) 
VALUES ('L01', 'C01');
