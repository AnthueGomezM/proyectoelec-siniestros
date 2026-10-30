-- =============================================================================
-- Datos de semilla · se cargan automáticamente al crear el contenedor de BD.
--
-- Contiene lo mínimo para que la demo tenga sentido:
--   * 12 pólizas, incluidas 2 vencidas y 1 cancelada (casos que el agente debe detectar).
--   * 10 siniestros históricos ya resueltos, con costo real: son el material que
--     devuelve la herramienta buscar_siniestros_similares (búsqueda de texto completo).
--
-- Nota de diseño: claims NO tiene llave foránea hacia policies a propósito. Un cliente
-- puede reportar con un id que no existe (error de digitación en el call center) y el
-- agente debe manejar ese caso, no la base de datos.
-- =============================================================================

INSERT INTO policies (customer_id, holder_name, product, status, coverage_limit, deductible, valid_from, valid_to, city) VALUES
    ('CUST-000123', 'Laura P.',   'AUTO',    'ACTIVE',    80000000,  800000, '2026-01-15', '2027-01-14', 'Bogotá'),
    ('CUST-004567', 'Andrés G.',  'MEDICAL', 'ACTIVE',   120000000,  300000, '2025-11-01', '2026-10-31', 'Medellín'),
    ('CUST-009999', 'Marta S.',   'HOME',    'ACTIVE',   200000000, 1200000, '2026-03-01', '2027-02-28', 'Cali'),
    ('CUST-007781', 'Carlos R.',  'AUTO',    'LAPSED',    60000000,  700000, '2024-09-01', '2025-08-31', 'Bogotá'),
    ('CUST-002210', 'Jorge D.',   'HOME',    'ACTIVE',   150000000, 1000000, '2026-02-10', '2027-02-09', 'Bucaramanga'),
    ('CUST-006612', 'Paula M.',   'MEDICAL', 'ACTIVE',    90000000,  250000, '2026-05-20', '2027-05-19', 'Pereira'),
    ('CUST-001190', 'Diego V.',   'AUTO',    'ACTIVE',    70000000,  900000, '2026-04-01', '2027-03-31', 'Bogotá'),
    ('CUST-008820', 'Sofía L.',   'HOME',    'ACTIVE',   180000000, 1100000, '2026-06-15', '2027-06-14', 'Manizales'),
    ('CUST-005501', 'Hernán T.',  'AUTO',    'ACTIVE',    65000000,  750000, '2026-07-01', '2027-06-30', 'Soacha'),
    ('CUST-003345', 'Camila O.',  'HOME',    'CANCELLED', 100000000,  900000, '2025-01-01', '2025-12-31', 'Barranquilla'),
    ('CUST-004410', 'Felipe N.',  'MEDICAL', 'LAPSED',    85000000,  280000, '2024-06-01', '2025-05-31', 'Cartagena'),
    ('CUST-009034', 'Natalia B.', 'AUTO',    'ACTIVE',    95000000,  850000, '2026-08-01', '2027-07-31', 'Bogotá')
ON CONFLICT (customer_id) DO NOTHING;

-- Siniestros históricos resueltos: alimentan la búsqueda de casos parecidos.
INSERT INTO claims (id, customer_id, claim_type, description, gps_latitude, gps_longitude,
                    incident_timestamp, estimated_cost, status, status_reason, reviewed_by, reviewed_at,
                    received_at, updated_at)
VALUES
    ('11111111-0000-4000-8000-000000000001', 'CUST-000123', 'AUTO',
     'Choque por alcance en la autopista norte a la altura del peaje. El otro conductor frenó de golpe y el bómper delantero quedó hundido. No hubo heridos.',
     4.710989, -74.072090, now() - interval '120 days', 4200000, 'APPROVED',
     'Daño material verificado con fotos y peritaje', 'ana', now() - interval '118 days',
     now() - interval '120 days', now() - interval '118 days'),

    ('11111111-0000-4000-8000-000000000002', 'CUST-001190', 'AUTO',
     'Volcamiento en la vía a La Calera por lluvia. El vehículo quedó con pérdida total y el conductor fue trasladado en ambulancia con fracturas.',
     4.717000, -74.030000, now() - interval '95 days', 68000000, 'APPROVED',
     'Pérdida total confirmada, atención médica cubierta', 'luis', now() - interval '92 days',
     now() - interval '95 days', now() - interval '92 days'),

    ('11111111-0000-4000-8000-000000000003', 'CUST-005501', 'AUTO',
     'Rayón profundo en la puerta del conductor hecho en el parqueadero de un centro comercial. Sin testigos.',
     4.676000, -74.048000, now() - interval '60 days', 950000, 'APPROVED',
     'Aprobación rápida por monto menor', 'nlp-triage', now() - interval '60 days',
     now() - interval '60 days', now() - interval '60 days'),

    ('11111111-0000-4000-8000-000000000004', 'CUST-009034', 'AUTO',
     'Robo del vehículo en vía pública con intimidación armada. Se puso denuncia ante la Fiscalía el mismo día.',
     4.628000, -74.065000, now() - interval '45 days', 95000000, 'APPROVED',
     'Hurto calificado con denuncia validada', 'ana', now() - interval '40 days',
     now() - interval '45 days', now() - interval '40 days'),

    ('11111111-0000-4000-8000-000000000005', 'CUST-004567', 'MEDICAL',
     'Caída en el baño con fractura de cadera. Requirió hospitalización de cinco días y cirugía de reemplazo parcial.',
     6.244203, -75.581211, now() - interval '150 days', 34000000, 'APPROVED',
     'Procedimiento dentro de cobertura', 'luis', now() - interval '140 days',
     now() - interval '150 days', now() - interval '140 days'),

    ('11111111-0000-4000-8000-000000000006', 'CUST-006612', 'MEDICAL',
     'Infarto agudo de miocardio atendido en urgencias. Ingreso a unidad de cuidados intensivos por 48 horas.',
     4.813330, -75.696110, now() - interval '80 days', 52000000, 'APPROVED',
     'Urgencia vital cubierta al 100%', 'ana', now() - interval '79 days',
     now() - interval '80 days', now() - interval '79 days'),

    ('11111111-0000-4000-8000-000000000007', 'CUST-004567', 'MEDICAL',
     'Consulta por dolor de garganta y fiebre. Tratamiento ambulatorio con antibiótico por cinco días.',
     6.244203, -75.581211, now() - interval '30 days', 180000, 'APPROVED',
     'Gasto ambulatorio menor', 'nlp-triage', now() - interval '30 days',
     now() - interval '30 days', now() - interval '30 days'),

    ('11111111-0000-4000-8000-000000000008', 'CUST-009999', 'HOME',
     'Incendio en la cocina por falla del calentador a gas. Los bomberos controlaron el fuego y hubo quemaduras leves en un brazo.',
     3.451647, -76.532050, now() - interval '70 days', 41000000, 'APPROVED',
     'Incendio con causa técnica verificada', 'luis', now() - interval '65 days',
     now() - interval '70 days', now() - interval '65 days'),

    ('11111111-0000-4000-8000-000000000009', 'CUST-002210', 'HOME',
     'Tubería rota en el segundo piso que inundó la sala y dañó los muebles de madera y el piso laminado.',
     7.119349, -73.122742, now() - interval '55 days', 12500000, 'APPROVED',
     'Daño por agua cubierto, deducible aplicado', 'ana', now() - interval '50 days',
     now() - interval '55 days', now() - interval '50 days'),

    ('11111111-0000-4000-8000-00000000000a', 'CUST-008820', 'HOME',
     'Gotera en el techo del cuarto principal después de varios días de lluvia. Humedad en la pared y pintura levantada.',
     5.070300, -75.517380, now() - interval '20 days', 1800000, 'APPROVED',
     'Mantenimiento cubierto por amparo de daños por agua', 'nlp-triage', now() - interval '20 days',
     now() - interval '20 days', now() - interval '20 days')
ON CONFLICT (id) DO NOTHING;
