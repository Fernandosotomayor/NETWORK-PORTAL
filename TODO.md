# Contexto Maestro del Proyecto: Portal de Gestión de Switches

## 1. Stack Tecnológico Base
* **Backend:** Python (FastAPI).
* **Motor de Plantillas:** Jinja2 (Server-Side Rendering).
* **Persistencia:** File-based (Lectura de archivos JSON en `/normalized_json`). Sin base de datos SQL/NoSQL.
* **Modelo de Datos:** `JsonInventoryRepository` mapea los JSON a objetos `SwitchRecord` en memoria.
* **Integración Externa:** Oxidized (para respaldos y versionado en Git).

---

## 2. Hoja de Ruta y Estado Actual (MVPs)

### [x] MVP 1: Portal de Inventario (Completado)
* **Objetivo:** Reemplazar la consulta manual de respaldos.
* **Flujo actual:** CFG -> Parser Python -> JSON -> Portal Web (FastAPI).
* **Funcionalidades:** Dashboard general (Switches, VLANs, Puertos), tabla de inventario y buscador por texto/VLAN.

### [x] MVP 2: Auditoría Automática (Completado)
* **Objetivo:** Detectar inconsistencias de configuración mediante reglas lógicas sobre el JSON.
* **Regla 1:** Detectar VLANs utilizadas en puertos (access/trunk) que no existen en la base global de VLANs del switch.
* **Regla 2:** Detectar enlaces Trunk sospechosos (ej. Native VLAN configurada pero Allowed VLAN vacía).
* **Regla 3:** Detectar puertos físicos sin descripción (`description` vacía o nula).
* **Entregable:** Endpoint de reporte y vista en Jinja2 con contadores de hallazgos (Críticos/Advertencias).

### [x] MVP 3: Historial y Auditoría de Cambios (Completado)
* **Objetivo:** Visualizar el "Diff" de qué cambió, cuándo y dónde.
* **Fuente de Datos:** Integración con el repositorio Git local generado por Oxidized.
* **Funcionalidades:** Línea de tiempo de modificaciones por switch y resumen de cambios por fecha.

### [x] MVP 4: Topología de Red (Completado)
* **Objetivo:** Generar diagramas de red dinámicos eliminando el dibujo manual.
* **Fase A:** Mapeo estático basado en el parseo del campo `description` de las interfaces (ej. "Trunk_to_SW_BODEGA").
* **Fase B:** Preparar el modelo de datos para ingestar la tabla de vecinos LLDP.
* **Entregable:** Vista de árbol o grafo visual mostrando jerarquías.

### [ ] MVP 5: Integración en Tiempo Real con Oxidized
* **Objetivo:** Cero intervención humana en la actualización del inventario.
* **Desarrollo:** Creación de un Webhook o Cronjob en FastAPI.
* **Flujo esperado:** Oxidized detecta cambio -> Genera Backup -> Llama al Webhook de FastAPI -> FastAPI ejecuta el `parser.main` -> Actualiza los JSON -> Refresca la vista en el portal.

### [ ] MVP 6: CMDB de Red (Contexto Enriquecido)
* **Objetivo:** Agregar metadatos operativos al inventario.
* **Funcionalidades:** Mapeo de equipos finales (ej. Access Points conectados), ubicaciones físicas (Bodegas, Oficinas) y responsables de área.
* **Desarrollo:** Ampliar el esquema JSON and el modelo `SwitchRecord` para soportar campos de metadatos manuales o semi-automatizados.

### [ ] MVP 7: Descubrimiento Automático Activo
* **Objetivo:** Auto-documentación de la red.
* **Tecnología:** Implementar *polling* activo mediante SNMP y LLDP desde el backend.
* **Métricas:** Recolección de Uptime, versión exacta de Firmware en vivo, y estado Up/Down de los equipos (Online/Offline).

---

## 3. Directivas de Desarrollo para el Agente (IA)
* **Regla estricta:** NO introducir bases de datos relacionales (SQL) ni ORMs (SQLAlchemy) a menos que se indique explícitamente la transición fuera del modelo File-Based.
* **Regla estricta:** Mantener la ligereza del proyecto usando FastAPI y Jinja2. Evitar introducir frameworks de frontend complejos (React/Vue) para mantener la arquitectura actual.
* **Regla estricta:** Al desarrollar una nueva fase, actualizar las casillas de verificación `[ ]` a `[x]` en este documento.
