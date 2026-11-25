# KORVIA — memoria del proyecto

Última actualización: 2026-11-25.

Este archivo es el punto de partida al volver al proyecto. Aquí está lo importante acordado, construido y pendiente. `docs/Contexto.md` tiene la visión general; este archivo tiene el estado real.

## Cómo responder

El usuario pide español sencillo, frases cortas y pocas viñetas. Sin jerga innecesaria. Después de analizar o cambiar código, dar solo: qué se hizo, para qué sirve, qué se comprobó y qué falta. Las reglas están en `AGENTS.md`.

## Repositorio

- URL: https://github.com/MaicolAgudeloITM/korvia
- Rama: `main`. Repositorio público.
- Usuario Git local: `kemtch` / `kemtch19@gmail.com`.
- Último commit conocido: `50e55f5` — "Ampliar formatos admitidos: Office, OpenDocument, datos e imágenes".
- No se suben claves: `.env`, `.venv`, bases de datos y `data/*` están ignorados. `data/entrada/.gitkeep` sí se sube.

## Cómo arrancar

Con Docker (forma recomendada):

```bash
cd D:\Korvia
docker compose up --build
```

Abrir **http://127.0.0.1:8000** para la web, o `/docs` para probar la API.

Sin Docker, con el entorno ya creado:

```bash
cd D:\Korvia
.\.venv\Scripts\activate
cd backend
python -m uvicorn korvia.main:app --reload
```

Sin Docker se usa SQLite en `backend/data/korvia.db`. Para leer PDF escaneados hace falta Tesseract instalado; Docker ya lo trae.

Pruebas:

```bash
cd D:\Korvia
python -m pytest -q
```

Último resultado: **92 pruebas pasan**.

Comandos útiles:

```bash
docker compose logs korvia-api
docker compose ps -a
docker compose down          # apaga, conserva la base
docker compose down -v       # WARNING: borra la base de Docker
```

## Estado actual

La API está en versión `0.9.0`. La cabeza de migraciones es `cadcbf46d947`. No hay cambios de esquema pendientes.

Cadena de migraciones:

1. `534f0ab79f43` — esquema inicial.
2. `acf878be84ce` — usuarios y sesiones.
3. `7c1e9a4b2d30` — versiones, metadata y borrado lógico.
4. `b4d6e8f10a92` — embeddings para búsqueda.
5. `cafa2f6fd877` — sincronización de carpetas.
6. `0fc417d9bc36` — agentes e historial de ejecución.
7. `cadcbf46d947` — registro de auditoría.

Lo que ya funciona:

- **Usuarios y permisos:** registro, inicio de sesión, sesiones revocables, roles `owner`, `admin` y `member`. Contraseñas con PBKDF2; tokens guardados como hash.
- **Empresas y espacios:** cada usuario pertenece a una empresa; dueño/admin gestionan, miembro solo lee.
- **Documentos:** subida de PDF, Word, Excel, PowerPoint, LibreOffice, texto, datos e imágenes; OCR en Docker; extracción en fragmentos con origen (página, fila, línea, diapositiva, imagen).
- **Formatos admitidos:** `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.odt`, `.ods`, `.odp`, `.md`, `.txt`, `.log`, `.csv`, `.tsv`, `.json`, `.xml`, `.yaml`, `.yml`, `.html`, `.htm`, `.rtf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, `.bmp`. La lista única está en `SUPPORTED_EXTENSIONS` (`document_processing.py`).
- **Lectura de texto:** Markdown limpia títulos, listas, negritas y enlaces; HTML quita etiquetas y scripts; RTF quita órdenes de formato; CSV/TSV se leen como filas. Todo cita `línea N` o `fila N`. Acepta UTF-8 con BOM; si no es UTF-8 avisa y usa otra codificación.
- **Presentaciones:** PPTX usa `python-pptx` (dependencia nueva). ODT, ODS y ODP se leen del XML interno con la librería estándar de Python.
- **Imágenes:** se leen con Tesseract compartiendo la función `_recognize_image` con el OCR de PDF. Sin Tesseract se devuelve un error claro, nunca texto inventado.
- **Versiones:** subir de nuevo el mismo nombre crea una versión nueva. Solo se usa la versión vigente en búsquedas y respuestas.
- **Metadata y borrado:** metadata libre; borrado lógico con restauración.
- **Búsqueda:** por similitud, con filtros de espacio y metadata; reindexado para dueño.
- **Respuestas (RAG):** `POST /ask` devuelve respuesta, fuentes citadas `[1]`, `[2]` y aviso cuando no hay evidencia.
- **Sincronización:** `POST .../sync` revisa `data/entrada`; crea, actualiza u oculta documentos. `GET .../sync` muestra el estado. Es manual, no automática.
- **Agentes:** lista de preguntas que se ejecutan en orden y entregan un informe con fuentes. Historial con quién ejecutó y resultado.
- **Auditoría:** `GET .../audit` para dueño/admin con acciones importantes.
- **Seguridad básica:** límite de 5 intentos fallidos de login en 15 minutos y cabeceras de seguridad. El límite es solo en memoria.
- **Interfaz web:** página en `/` con create account, login, áreas, documentos, búsqueda, preguntas, agentes y actividad. El selector de archivos acepta todos los formatos. HTML/JS/CSS puro, sin Internet ni build. El token se guarda en `localStorage`.

## Proveedores

Por defecto todo funciona sin red:

- Embeddings: `local-hash`. Es determinista, **no es semántica real**.
- Chat: `extractive`. Muestra los fragmentos con citas, no inventa nada.

Opciones configurables (en `.env` o variables de entorno):

- `KORVIA_EMBEDDING_PROVIDER=openai`, `KORVIA_OPENAI_API_KEY`, `KORVIA_OPENAI_MODEL`, `KORVIA_OPENAI_BASE_URL`.
- `KORVIA_CHAT_PROVIDER=openai`, `KORVIA_CHAT_API_KEY`, `KORVIA_CHAT_MODEL`, `KORVIA_CHAT_BASE_URL`.
- `KORVIA_MIN_ANSWER_SCORE` (por defecto `0.05`).
- `KORVIA_MAX_UPLOAD_BYTES` (25 MB), `KORVIA_SYNC_ROOT`, `KORVIA_SESSION_HOURS`.
- `KORVIA_LOGIN_MAX_FAILURES` (5), `KORVIA_LOGIN_WINDOW_SECONDS` (900).
- `DATABASE_URL`, `KORVIA_STORAGE_DIR`.

Claude Code/Anthropic no sirve como proveedor de embeddings ni expone un endpoint de chat usable. Cualquier proveedor compatible con `/embeddings` o `/chat/completions` sí funciona indicando URL y modelo. Nunca pegar claves en el chat; van en `.env`.

## Archivos principales

- `backend/korvia/main.py`: endpoints y lógica de API.
- `backend/korvia/models.py`: tablas y modelos SQLAlchemy.
- `backend/korvia/database.py`: conexión y ejecución de migraciones al arrancar.
- `backend/korvia/auth.py`: contraseñas, sesiones, permisos, límite de login.
- `backend/korvia/chat.py`: proveedores de respuesta RAG.
- `backend/korvia/embeddings.py`: proveedores de vectores (384 dimensiones).
- `backend/korvia/search.py`: búsqueda y similitud.
- `backend/korvia/document_processing.py` y `file_storage.py`: extracción y guardado.
- `backend/korvia/sync.py`: lectura segura de la carpeta local.
- `backend/korvia/web/`: `index.html`, `app.js`, `styles.css`.
- `backend/alembic/versions/`: migraciones.
- `backend/tests/`: pruebas de API, auth, versiones, búsqueda, RAG, sync, agentes, auditoría, web y migraciones.
- `compose.yaml`: PostgreSQL pgvector + API.
- `README.md`: guía corta para usuarios.
- `docs/Contexto.md`: visión y roadmap original.

## Endpoints principales

- `GET /health`, `GET /` (web), `/docs`.
- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`.
- Empresas: `POST /api/tenants`, `GET/POST /api/tenants/{id}/members`.
- Espacios: `GET/POST /api/tenants/{id}/spaces`.
- Documentos: subida, listado, detalle, versiones, metadata, ocultar, restaurar, `POST /api/documents/inspect`.
- Búsqueda: `POST /api/tenants/{id}/search`, `POST /api/tenants/{id}/search/reindex`.
- Preguntas: `POST /api/tenants/{id}/ask`.
- Sincronización: `POST/GET /api/tenants/{id}/spaces/{space_id}/sync`.
- Agentes: `POST/GET /api/tenants/{id}/agents`, `POST .../agents/{agent_id}/run`, `GET .../agents/{agent_id}/runs`.
- Auditoría: `GET /api/tenants/{id}/audit?limit=50`.

## Decisiones importantes

- Desarrollo por fases pequeñas y verificables: cada fase termina con pruebas y documentación.
- Nada de integraciones ficticias. Si algo no existe, se dice.
- El proveedor por defecto nunca llama a la red ni inventa respuestas.
- La separación por empresa se aplica en la base de datos, no solo en la interfaz.
- Actividades sensibles quedan en auditoría.
- Los archivos originales se guardan aparte; los documentos borrados conservan historial.
- La base de Docker se recreó limpia el 2026-11-25. No hay usuarios todavía; hay que crear cuenta en la web.

## Problema grave ya corregido

Las migraciones funcionaban en SQLite pero fallaban en PostgreSQL. Faltaban reglas únicas para claves foráneas compuestas:

- `7c1e9a4b2d30`: Falta `uq_version_tenant_id` en `document_versions`.
- `0fc417d9bc36`: Falta `uq_agent_tenant_id` en `agents`.

Se corrigieron ambas migraciones y los modelos. Se añadió la prueba `test_las_claves_foraneas_compuestas_tienen_columnas_unicas` para detectarlo antes. Si existe una base antigua creada antes de `f7ccc32`, conviene recrearla con `docker compose down -v`.

## Pendiente

- Sincronización automática con programador y conectores reales (SharePoint, bases de datos).
- Agentes con pasos elegidos por un modelo y herramientas reales, con confirmación para acciones sensibles.
- Auditoría persistente del límite de login (ahora es en memoria) y protección contra abuso más completa.
- Recuperación de contraseña, verificación de correo, HTTPS y permisos por documento.
- Mejorar la interfaz y usar semántica real configurando un proveedor de embeddings.
- Validar con empresas reales antes de construir más funcionalidades.

## Regla para futuras sesiones

Al empezar, leer este archivo. Al terminar cada cambio importante, actualizarlo con: estado nuevo, decisiones, comandos de prueba, número de pruebas y pendientes. Así no se pierde contexto entre sesiones.
