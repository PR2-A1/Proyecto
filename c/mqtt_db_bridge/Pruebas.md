# MQTT DB Bridge

Servicio Rust que suscribe topics MQTT y persiste los eventos en PostgreSQL.

## Setup

1. Copia `.env.example` a `.env` y ajusta los valores.
2. Asegúrate de que PostgreSQL esté corriendo con la base de datos `giirob`.
3. Ejecuta el bridge:

```
cargo run
```

---

## Pruebas de integración

El bridge debe estar corriendo. Publica el JSON en el topic indicado y luego comprueba con el SQL.

**Restricciones del esquema a tener en cuenta:**
- `caja_id`, `lote_id`, `proveedor` → `CHAR(5)`, máximo 5 caracteres.
- `color` en `caja` → solo acepta: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `WHITE`.
- `proveedor` en `proveedor_material` → FK a la tabla `proveedor`, debe existir previamente.
- `lotes` en `caja_ready` → FK a `material_no_clasificado`, el lote debe existir antes.

**Proveedores de prueba — insertar antes de empezar:**
```sql
INSERT INTO proveedor (num_proveedor, cif_nif, nombre, certificacion_iso) VALUES
('P0001', 'B12345678', 'Tapas García S.L.', true),
('P0002', 'A87654321', 'Plásticos Roca S.A.', false),
('P0003', 'B11223344', 'Industrias Molina', true),
('P0004', 'A99887766', 'Suministros Vega S.L.', true),
('P0005', 'B55443322', 'Componentes del Sur S.A.', false);
```

**Operarios de prueba — insertar antes de empezar:**
```sql
INSERT INTO operario (operario_id, nombre, apellido) VALUES
(1, 'Carlos',   'Martínez'),
(2, 'Laura',    'Sánchez'),
(3, 'Miguel',   'Torres'),
(4, 'Ana',      'Romero'),
(5, 'Fernando', 'Jiménez');
```

---

### 1. Generar un lote desde SCADA (hacerlo primero)

El lote debe existir antes de poder asociarlo a una caja.

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "lote_id": "L0042",
  "proveedor": "P0003",
  "quantity": 500
}
```

> `proveedor` debe ser un `num_proveedor` que ya exista en la tabla `proveedor`.

**Verificar lote:**
```sql
SELECT lote_id, fecha_inicio, fecha_fin, total_tapas_entrada, total_tapas_clasificadas
FROM material_no_clasificado
WHERE lote_id = 'L0042';
```

**Verificar proveedor:**
```sql
    SELECT proveedor, lote_id
    FROM proveedor_material
    WHERE lote_id = 'L0042';
```

---

### 2. Generar un lote sin proveedor

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "lote_id": "L0043",
  "quantity": 200
}
```

**Verificar lote:**
```sql
SELECT lote_id, total_tapas_entrada
FROM material_no_clasificado
WHERE lote_id = 'L0043';
```

**Verificar que no se insertó proveedor:**
```sql
SELECT COUNT(*) FROM proveedor_material WHERE lote_id = 'L0043';
-- Debe devolver 0
```

---

### 3. Registrar una caja nueva (sin lotes)

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "C0001",
  "color": "RED",
  "codigo_etiqueta": "ETQ-ABC123",
  "estado": true,
  "lotes": []
}
```

> `color` debe ser uno de: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `WHITE` (el bridge lo convierte a mayúsculas automáticamente).

**Verificar:**
```sql
SELECT caja_id, color, codigo_etiqueta, estado, palet_id
FROM caja
WHERE caja_id = 'C0001';
```

---

### 4. Registrar una caja con lotes asociados

El lote `L0042` debe existir previamente (prueba 1).

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "C0002",
  "color": "BLUE",
  "codigo_etiqueta": "ETQ-XYZ999",
  "estado": true,
  "lotes": ["L0042"]
}
```

**Verificar caja:**
```sql
SELECT caja_id, color, codigo_etiqueta, estado
FROM caja
WHERE caja_id = 'C0002';
```

**Verificar relación caja-lote:**
```sql
SELECT lote_id, caja_id
FROM material_caja
WHERE caja_id = 'C0002';
```

---

### 5. Actualizar una caja existente

Misma `caja_id`, datos distintos. El bridge actualiza el registro.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "caja_id": "C0001",
  "color": "GREEN",
  "codigo_etiqueta": "ETQ-NUEVA1",
  "estado": false,
  "lotes": []
}
```

**Verificar:**
```sql
SELECT caja_id, color, codigo_etiqueta, estado
FROM caja
WHERE caja_id = 'C0001';
```
> Debe mostrar `GREEN`, `ETQ-NUEVA1` y `estado = false`.

---

### 6. Lote duplicado (debe ignorarse)

Publica el mismo `lote_id` de la prueba 1 con cantidad distinta. El segundo insert se ignora.

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "lote_id": "L0042",
  "proveedor": "P0003",
  "quantity": 999
}
```

**Verificar que los datos originales no cambiaron:**
```sql
SELECT total_tapas_entrada FROM material_no_clasificado WHERE lote_id = 'L0042';
-- Debe seguir siendo 500
```

---

---

### 7. Paletizar una caja (pallet aún abierto)

Requiere que `C0001` exista (prueba 3 o 4). El bridge vincula la caja al pallet y lo crea si no existe.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "caja_paletizada",
  "caja_id": "C0001",
  "palet_id": 10,
  "codigo_palet": "PALET00001",
  "color_id": "RED",
  "estado": false
}
```

**Verificar pallet creado:**
```sql
SELECT palet_id, codigo_palet, color_id, estado, operario_cierre_id
FROM palet
WHERE palet_id = 10;
-- operario_cierre_id debe ser NULL (pallet aún abierto)
```

**Verificar caja vinculada:**
```sql
SELECT caja_id, palet_id FROM caja WHERE caja_id = 'C0001';
-- palet_id debe ser 10
```

---

### 8. Cerrar un pallet (12 cajas alcanzadas)

El bridge detecta `estado: true`, consulta la tabla `operario` y asigna uno aleatoriamente como operario de cierre.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "caja_paletizada",
  "caja_id": "C0002",
  "palet_id": 10,
  "codigo_palet": "PALET00001",
  "color_id": "RED",
  "estado": true
}
```

**Verificar pallet cerrado con operario asignado:**
```sql
SELECT palet_id, estado, operario_cierre_id
FROM palet
WHERE palet_id = 10;
-- estado debe ser true
-- operario_cierre_id debe ser uno de: 1, 2, 3, 4, 5
```

**Verificar qué operario fue asignado:**
```sql
SELECT p.palet_id, p.estado, o.operario_id, o.nombre, o.apellido
FROM palet p
JOIN operario o ON o.operario_id = p.operario_cierre_id
WHERE p.palet_id = 10;
```

---

### Limpiar datos de prueba

```sql
UPDATE caja SET palet_id = NULL          WHERE caja_id IN ('C0001', 'C0002');
DELETE FROM palet                        WHERE palet_id IN (10);
DELETE FROM material_caja               WHERE caja_id IN ('C0001', 'C0002');
DELETE FROM caja                        WHERE caja_id IN ('C0001', 'C0002');
DELETE FROM proveedor_material          WHERE lote_id IN ('L0042', 'L0043');
DELETE FROM material_no_clasificado     WHERE lote_id IN ('L0042', 'L0043');
DELETE FROM operario                    WHERE operario_id IN (1, 2, 3, 4, 5);
```
