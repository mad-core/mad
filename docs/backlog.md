# Backlog — Mad

Cosas identificadas como mejoras pero fuera del scope de v0.1. Se abordarán cuando duelan o cuando la base esté estable.

## Arquitectura

### 1. Separar event log de estado proyectado
**Problema:** releer el JSONL completo para reconstruir el estado en cada recuperación mezcla dos responsabilidades (log inmutable vs. estado actual) y escala mal a medida que las sesiones crecen. Además, `GET /v1/sessions` obliga a escanear el directorio entero.

**Propuesta:** mantener el JSONL como event log append-only e inmutable, pero proyectar el estado actual (status, turn, cursor, stop_reason, metadata) en:
- un `state.json` por sesión, o
- una tabla SQLite única (`sessions`) con una fila por sesión.

SQLite adicionalmente habilita queries para listar, filtrar y paginar sesiones sin tocar el filesystem.

**Impacto:** necesario antes de soportar >100 sesiones o filtros en el listado.

---

### 2. Sacar el harness (agent loop) a un worker separado
**Problema:** hoy el agent loop corre como `asyncio.Task` dentro del proceso de FastAPI. Si uvicorn se reinicia o crashea, todas las sesiones en vuelo se pierden. El comentario "el harness es stateless y retoma desde el log" solo se cumple de verdad si el harness es un proceso aparte.

**Propuesta:**
- Proceso worker independiente (subprocess, systemd unit, o contenedor) que consume trabajo.
- Cola ligera: Redis + `arq`, o incluso una tabla `jobs` en SQLite con polling.
- La API solo escribe eventos `user.message` y encola; el worker hace el loop y escribe los eventos `agent.*` al log.

**Impacto:** convierte el sistema en tolerante a reinicios y desbloquea concurrencia real entre sesiones.

---

### 3. Pub/sub para el stream SSE
**Problema:** el endpoint SSE lee el JSONL con tail-follow. Eso funciona para un cliente local, pero no soporta bien reconexiones (no hay `Last-Event-ID`), múltiples suscriptores por sesión, ni baja latencia si el log está en disco lento.

**Propuesta:**
- En memoria: `asyncio.Queue` por `session_id`, más fallback a lectura del archivo para reconexión con `Last-Event-ID` (leer desde el offset indicado).
- Externo: Redis pub/sub cuando el harness sea un proceso aparte (ver punto 2).
- Implementar el header `Last-Event-ID` que el cliente EventSource envía automáticamente al reconectar.

**Impacto:** necesario cuando haya cliente web o múltiples observadores por sesión.

---

## Otros

- **Docker sandbox** — reemplazar bwrap/subprocess directo por contenedores efímeros.
- **Vaults encriptados** para credenciales en lugar de pasarlas en el JSON.
- **Workflows multi-sesión** encadenando agentes.
- **Scheduler/cron** para lanzar sesiones recurrentes.
- **Autenticación de la API**.
- **Dashboard web**.
- **Más LLM providers** (Ollama, OpenAI, etc).
