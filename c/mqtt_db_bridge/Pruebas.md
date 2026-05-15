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
- `id_caja`, `id_lote`, `proveedor` → `CHAR(5)`, máximo 5 caracteres.
- `color` en `caja` → solo acepta: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `WHITE`.
- `proveedor` en `proveedor_material` → FK a la tabla `proveedor`, debe existir previamente.
- `lotes` en `caja_ready` → FK a `lote`, el lote debe existir antes.

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
INSERT INTO operario (id_operario, nombre, apellido) VALUES
('OP001', 'Carlos',   'Martínez'),
('OP002', 'Laura',    'Sánchez'),
('OP003', 'Miguel',   'Torres'),
('OP004', 'Ana',      'Romero'),
('OP005', 'Fernando', 'Jiménez');
```

---

### 1. Generar un lote desde SCADA (hacerlo primero)

El lote debe existir antes de poder asociarlo a una caja.

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "id_lote": "L0042",
  "proveedor": "P0003",
  "quantity": 500
}
```

> `proveedor` debe ser un `num_proveedor` que ya exista en la tabla `proveedor`.

**Verificar lote:**
```sql
SELECT id_lote, fecha_inicio, fecha_fin, total_tapas_entrada, total_tapas_clasificadas
FROM lote
WHERE id_lote = 'L0042';
```

**Verificar proveedor:**
```sql
SELECT proveedor, lote
FROM proveedor_material
WHERE lote = 'L0042';
```

---

### 2. Generar un lote sin proveedor

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "id_lote": "L0043",
  "quantity": 200
}
```

**Verificar lote:**
```sql
SELECT id_lote, total_tapas_entrada
FROM lote
WHERE id_lote = 'L0043';
```

**Verificar que no se insertó proveedor:**
```sql
SELECT COUNT(*) FROM proveedor_material WHERE lote = 'L0043';
-- Debe devolver 0
```

---

### 3. Registrar una caja nueva (sin lotes)

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "id_caja": "B0001",
  "color": "RED",
  "codigo_etiqueta": "ETQ-ABC123",
  "estado": true,
  "lotes": []
}
```

> `color` debe ser uno de: `RED`, `GREEN`, `BLUE`, `YELLOW`, `ORANGE`, `WHITE` (el bridge lo convierte a mayúsculas automáticamente).

**Verificar:**
```sql
SELECT id_caja, color, codigo_etiqueta, estado, id_palet
FROM caja
WHERE id_caja = 'B0001';
```

---

### 4. Registrar una caja con lotes asociados

El lote `L0042` debe existir previamente (prueba 1).

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "id_caja": "B0002",
  "color": "BLUE",
  "codigo_etiqueta": "ETQ-XYZ999",
  "estado": true,
  "lotes": ["L0042"]
}
```

**Verificar caja:**
```sql
SELECT id_caja, color, codigo_etiqueta, estado
FROM caja
WHERE id_caja = 'B0002';
```

**Verificar relación caja-lote:**
```sql
SELECT lote, id_caja
FROM material_caja
WHERE id_caja = 'B0002';
```

---

### 5. Actualizar una caja existente

Mismo `id_caja`, datos distintos. El bridge actualiza el registro.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "BOX_COMPLETED",
  "id_caja": "B0001",
  "color": "GREEN",
  "codigo_etiqueta": "ETQ-NUEVA1",
  "estado": false,
  "lotes": []
}
```

**Verificar:**
```sql
SELECT id_caja, color, codigo_etiqueta, estado
FROM caja
WHERE id_caja = 'B0001';
```
> Debe mostrar `GREEN`, `ETQ-NUEVA1` y `estado = false`.

---

### 6. Lote duplicado (debe ignorarse)

Publica el mismo `id_lote` de la prueba 1 con cantidad distinta. El segundo insert se ignora.

**Topic:** `giirob/pr2-A1/devices/scada/action`

**JSON:**
```json
{
  "cmd": "gen",
  "id_lote": "L0042",
  "proveedor": "P0003",
  "quantity": 999
}
```

**Verificar que los datos originales no cambiaron:**
```sql
SELECT total_tapas_entrada FROM lote WHERE id_lote = 'L0042';
-- Debe seguir siendo 500
```

---

---

### 7. Paletizar una caja (pallet aún abierto)

Requiere que `B0001` exista (prueba 3 o 4). El bridge vincula la caja al pallet y lo crea si no existe.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "caja_paletizada",
  "id_caja": "B0001",
  "id_palet": "P0001",
  "id_color": "RED",
  "estado": false
}
```

**Verificar pallet creado:**
```sql
SELECT id_palet, id_color, estado, id_operario
FROM palet
WHERE id_palet = 'P0001';
-- id_operario debe ser NULL (pallet aún abierto)
```

**Verificar caja vinculada:**
```sql
SELECT id_caja, id_palet FROM caja WHERE id_caja = 'B0001';
-- id_palet debe ser 'P0001'
```

---

### 8. Cerrar un pallet (12 cajas alcanzadas)

El bridge detecta `estado: true`, consulta la tabla `operario` y asigna uno aleatoriamente como operario de cierre.

**Topic:** `giirob/pr2-A1/db/push`

**JSON:**
```json
{
  "event": "caja_paletizada",
  "id_caja": "B0002",
  "id_palet": "P0001",
  "id_color": "RED",
  "estado": true
}
```

**Verificar pallet cerrado con operario asignado:**
```sql
SELECT id_palet, estado, id_operario
FROM palet
WHERE id_palet = 'P0001';
-- estado debe ser true
-- id_operario debe ser uno de: OP001..OP005
```

**Verificar qué operario fue asignado:**
```sql
SELECT p.id_palet, p.estado, o.id_operario, o.nombre, o.apellido
FROM palet p
JOIN operario o ON o.id_operario = p.id_operario
WHERE p.id_palet = 'P0001';
```

---

### Limpiar datos de prueba

```sql
UPDATE caja SET id_palet = NULL          WHERE id_caja IN ('B0001', 'B0002');
DELETE FROM palet                        WHERE id_palet IN ('P0001', 'P0002');
DELETE FROM material_caja               WHERE id_caja IN ('B0001', 'B0002');
DELETE FROM caja                        WHERE id_caja IN ('B0001', 'B0002');
DELETE FROM proveedor_material          WHERE lote IN ('L0042', 'L0043');
DELETE FROM lote                        WHERE id_lote IN ('L0042', 'L0043');
DELETE FROM operario                    WHERE id_operario IN ('OP001', 'OP002', 'OP003', 'OP004', 'OP005');
```
