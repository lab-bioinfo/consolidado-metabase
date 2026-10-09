-- Vistas de presentación exclusivamente: no modifica raw, analytics ni audit.
-- La clave de conciliación es (carga_id, numero_fila); EXISTS evita multiplicar
-- filas por las varias transformaciones/incidencias de una misma fila.
CREATE OR REPLACE VIEW mart.conciliacion_filas AS
SELECT f.id AS raw_fila_id, f.carga_id, c.archivo_nombre,
       f.archivo_origen, f.pestana_origen, f.numero_fila,
       COALESCE(a.medicamento_original,
           (SELECT v.valor FROM jsonb_array_elements_text(f.datos_json->'valores')
                WITH ORDINALITY AS v(valor, pos)
            JOIN jsonb_array_elements_text(f.datos_json->'columnas')
                WITH ORDINALITY AS h(columna, pos) USING (pos)
            WHERE h.columna = 'MEDICAMENTO' ORDER BY v.pos LIMIT 1)) AS medicamento,
       CASE
           WHEN EXISTS (SELECT 1 FROM analytics.consumo x
                        WHERE x.carga_id = f.carga_id AND x.numero_fila = f.numero_fila)
               THEN 'HECHO'
           WHEN EXISTS (SELECT 1 FROM audit.transformacion t
                        WHERE t.carga_id = f.carga_id AND t.numero_fila = f.numero_fila
                          AND t.resultado = 'IGNORADO_SUBTOTAL') THEN 'SUBTOTAL'
           WHEN EXISTS (SELECT 1 FROM audit.transformacion t
                        WHERE t.carga_id = f.carga_id AND t.numero_fila = f.numero_fila
                          AND t.resultado = 'IGNORADO_METADATA') THEN 'METADATA'
           ELSE 'SIN_CLASIFICAR'
       END AS clasificacion,
       EXISTS (SELECT 1 FROM audit.incidencia i
               WHERE i.carga_id = f.carga_id AND i.fila = f.numero_fila) AS tiene_incidencia
FROM raw.fila f
JOIN raw.carga c ON c.id = f.carga_id
LEFT JOIN analytics.consumo a ON a.carga_id = f.carga_id AND a.numero_fila = f.numero_fila;

-- Barras mutuamente excluyentes; la suma debe igualar filas originales.
CREATE OR REPLACE VIEW mart.conciliacion AS
SELECT clases.clasificacion, clases.orden, COUNT(f.raw_fila_id) AS filas
FROM (VALUES (1, 'HECHO'), (2, 'SUBTOTAL'), (3, 'METADATA'),
             (4, 'SIN_CLASIFICAR')) clases(orden, clasificacion)
LEFT JOIN mart.conciliacion_filas f ON f.clasificacion = clases.clasificacion
GROUP BY clases.clasificacion, clases.orden;

-- Denominador constante (número de hechos). Densidad: disponibilidad matemática
-- de la columna, NO validez clínica; flag publicado por separado.
CREATE OR REPLACE VIEW mart.cobertura_metricas AS
SELECT m.orden, m.metrica, COUNT(*) AS hechos_analiticos,
       COUNT(*) FILTER (WHERE m.valor IS NOT NULL) AS disponibles,
       COUNT(*) FILTER (WHERE m.valor IS NULL) AS no_disponibles,
       ROUND(100.0 * COUNT(*) FILTER (WHERE m.valor IS NOT NULL)
             / NULLIF(COUNT(*), 0), 2) AS porcentaje_disponible,
       COUNT(*) FILTER (WHERE m.orden = 5 AND m.valor IS NOT NULL
                       AND c.densidad_clinica_validada IS FALSE)
           AS densidades_no_validadas_clinicamente
FROM analytics.consumo c
CROSS JOIN LATERAL (VALUES
    (1, 'Unidades', c.unidades),
    (2, 'Gramos calculados', c.gramos_calculados),
    (3, 'DDD referencia usada', c.ddd_referencia_usada),
    (4, 'DDD consumidas', c.ddd_consumidas),
    (5, 'DDD/100 días-cama (calculada)', c.densidad_calculada),
    (6, 'Precio unitario', c.precio_unitario),
    (7, 'Gasto calculado', c.gasto_calculado)
) m(orden, metrica, valor)
GROUP BY m.orden, m.metrica;

-- Motivos registrados para cada métrica no disponible. Se atribuye solo una
-- transformación del MISMO campo; sin registro específico se indica explícitamente
-- que el motivo no está determinado. Las incidencias se consultan aparte.
CREATE OR REPLACE VIEW mart.no_disponibilidad AS
SELECT m.metrica, m.orden, c.carga_id, c.numero_fila, c.archivo_origen,
       c.pestana_origen, c.medicamento_original AS medicamento,
       COALESCE(t.resultado, 'SIN_RESULTADO_ESPECIFICO') AS resultado_registrado,
       t.regla_aplicada, t.columna_origen, t.valor_original,
       EXISTS (SELECT 1 FROM audit.incidencia i
               WHERE i.carga_id = c.carga_id AND i.fila = c.numero_fila)
           AS tiene_incidencia
FROM analytics.consumo c
CROSS JOIN LATERAL (VALUES
    (1, 'Unidades', 'unidades', c.unidades),
    (2, 'Gramos calculados', 'gramos_calculados', c.gramos_calculados),
    (3, 'DDD referencia usada', 'ddd_referencia_usada', c.ddd_referencia_usada),
    (4, 'DDD consumidas', 'ddd_consumidas', c.ddd_consumidas),
    (5, 'DDD/100 días-cama (calculada)', 'densidad_calculada', c.densidad_calculada),
    (6, 'Precio unitario', 'precio_unitario', c.precio_unitario),
    (7, 'Gasto calculado', 'gasto_calculado', c.gasto_calculado)
) m(orden, metrica, campo, valor)
LEFT JOIN LATERAL (
    SELECT resultado, regla_aplicada, columna_origen, valor_original
    FROM audit.transformacion t
    WHERE t.carga_id = c.carga_id AND t.numero_fila = c.numero_fila
      AND t.campo_destino = m.campo
    ORDER BY t.id LIMIT 1
) t ON TRUE
WHERE m.valor IS NULL;

-- Una fila por interpretación, también para subtotales y metadata. No se
-- agrupan ni se ocultan INVALIDO/PENDIENTE_VALIDACION.
CREATE OR REPLACE VIEW mart.trazabilidad AS
SELECT t.id AS transformacion_id, t.carga_id, f.id AS raw_fila_id,
       c.archivo_nombre, t.archivo_origen, t.pestana_origen, t.numero_fila,
       r.medicamento, r.clasificacion, t.campo_destino, t.columna_origen,
       t.valor_original, t.valor_interpretado, t.regla_aplicada, t.resultado,
       r.tiene_incidencia
FROM audit.transformacion t
JOIN raw.fila f ON f.carga_id = t.carga_id AND f.numero_fila = t.numero_fila
JOIN raw.carga c ON c.id = t.carga_id
JOIN mart.conciliacion_filas r ON r.raw_fila_id = f.id;

-- La fila física se muestra verticalmente, celda por celda, en orden original.
-- Incluye celdas vacías (ausencia no se convierte en cero) y encabezados repetidos.
CREATE OR REPLACE VIEW mart.origen_celdas AS
SELECT r.raw_fila_id, r.carga_id, r.archivo_nombre, r.archivo_origen,
       r.pestana_origen, r.numero_fila, r.medicamento, r.clasificacion,
       h.pos::INTEGER AS posicion_columna, h.columna AS columna_origen,
       v.valor AS valor_original
FROM raw.fila f
JOIN mart.conciliacion_filas r ON r.raw_fila_id = f.id
JOIN LATERAL jsonb_array_elements_text(f.datos_json->'columnas')
     WITH ORDINALITY AS h(columna, pos) ON TRUE
LEFT JOIN LATERAL jsonb_array_elements_text(f.datos_json->'valores')
     WITH ORDINALITY AS v(valor, pos) ON v.pos = h.pos;

GRANT SELECT ON mart.conciliacion_filas, mart.conciliacion,
    mart.cobertura_metricas, mart.no_disponibilidad,
    mart.trazabilidad, mart.origen_celdas TO metabase_reader;
