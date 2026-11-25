# KORVIA — prototipo local

KORVIA busca organizar información empresarial para que las personas puedan encontrarla más rápido y una IA pueda responder usando fuentes verificables.

## Estado actual

KORVIA recibe PDF, DOCX y XLSX, extrae su contenido, intenta leer con OCR las páginas de PDF escaneadas y conserva fragmentos con referencias a su origen. Permite crear empresas y espacios, guardar documentos y consultar sus fragmentos. Ya hay **usuarios, inicio de sesión y permisos por empresa**: dueño (`owner`), administrador (`admin`) y miembro (`member`, solo lectura). Los documentos tienen **versiones** (subir de nuevo el mismo nombre crea una versión), **metadata** editable y **borrado lógico** con restauración. Los fragmentos tienen **embeddings**, se pueden buscar por similitud y se pueden usar para **responder preguntas con fuentes citadas**. También se puede **sincronizar una carpeta local** para crear, actualizar u ocultar documentos según cambien los archivos.

**Todavía no es el MVP completo:** el flujo de RAG existe, pero por defecto no usa un modelo de lenguaje: solo muestra los fragmentos encontrados con sus citas. Para respuestas redactadas por IA hay que configurar un proveedor de chat compatible con OpenAI. El proveedor de embeddings por defecto es local y **no es semántica real**. Es un prototipo local: usa contraseñas cifradas y sesiones revocables, pero no tiene verificación de correo, recuperación de contraseña ni protección contra abuso de peticiones. No uses documentos empresariales confidenciales.

## Ejecutar con Docker

Requiere Docker Desktop.

```bash
docker compose up --build
```

La API queda disponible solamente en el computador local en `http://127.0.0.1:8000`.

- Estado: `GET http://127.0.0.1:8000/health`
- Documentación interactiva: `http://127.0.0.1:8000/docs`

## Crear usuario y iniciar sesión

1. `POST /api/auth/register` con `{"email":"tu@empresa.com","password":"clave-segura-123","company_name":"Mi empresa"}`. Crea la empresa, te deja como dueño y devuelve un `token`.
2. En las demás peticiones envía la cabecera `Authorization: Bearer <token>`.
3. `POST /api/auth/login` con correo y contraseña devuelve otro token; `GET /api/auth/me` muestra tus empresas y roles; `POST /api/auth/logout` cierra la sesión.
4. El dueño puede invitar a otro usuario registrado con `POST /api/tenants/{tenant_id}/members` y `{"email":"otro@empresa.com","role":"member"}`.

## Probar documentos guardados

Con la cabecera `Authorization: Bearer <token>`:

1. Usa `POST /api/tenants` con `{"name":"Otra empresa"}` para crear otra empresa (serás su dueño).
2. Usa `POST /api/tenants/{tenant_id}/spaces` con `{"name":"General"}` para crear su espacio.
3. Usa `POST /api/tenants/{tenant_id}/spaces/{space_id}/documents` para subir un PDF, DOCX o XLSX. Si subes otro archivo con el **mismo nombre**, se crea la versión 2 (y así sucesivamente).
4. Usa `GET /api/tenants/{tenant_id}/spaces/{space_id}/documents` para ver los documentos y `GET .../documents/{document_id}` para consultar los fragmentos de la versión vigente.
5. `GET .../documents/{document_id}/versions` lista las versiones y `GET .../documents/{document_id}/versions/{numero}` muestra los fragmentos de una versión antigua.
6. `PATCH .../documents/{document_id}` con `{"metadata":{"area":"Mantenimiento","anio":2026}}` guarda metadata libre (texto, números o banderas).
7. `DELETE .../documents/{document_id}` oculta el documento sin borrar su historial; `POST .../documents/{document_id}/restore` lo devuelve.
8. También puedes probar un archivo sin guardarlo con `POST /api/documents/inspect` (formulario, campo `file`).

La información queda guardada localmente en PostgreSQL y en la carpeta `data/uploads`. Docker conserva la base de datos aunque se reinicie el contenedor.

## Buscar por similitud

Con la cabecera `Authorization: Bearer <token>`:

1. `POST /api/tenants/{tenant_id}/search` con `{"query":"¿cada cuánto se cambia el filtro?","top_k":5}` devuelve los fragmentos más parecidos, con puntaje, documento, versión y fuentes (`página 1`, por ejemplo).
2. Puedes añadir `"space_id":"<id>"` para buscar en un solo espacio o `"metadata_filters":{"area":"Mantenimiento"}` para filtrar por metadata.
3. Solo se buscan fragmentos de la **versión vigente** de documentos activos. Cualquier miembro puede buscar; solo el dueño puede reindexar.
4. Si un documento se subió sin embeddings (por ejemplo, si el proveedor falló), el dueño puede ejecutar `POST /api/tenants/{tenant_id}/search/reindex` para generar los vectores que faltan.

### Proveedor de embeddings

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `KORVIA_EMBEDDING_PROVIDER` | `local-hash` | `local-hash` (pruebas, sin red) u `openai` (semántica real). |
| `KORVIA_OPENAI_API_KEY` | (vacía) | Clave API, obligatoria si eliges `openai`. |
| `KORVIA_OPENAI_MODEL` | `text-embedding-3-small` | Modelo de embeddings. |
| `KORVIA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Cambia la URL si usas un proveedor compatible. |

Con `openai`, los textos de los fragmentos y las preguntas se envían a ese proveedor. Si no quieres enviar información fuera de tu empresa, mantén `local-hash` o configura un proveedor compatible alojado por ti.

En PostgreSQL la migración crea la extensión `vector` y un índice `hnsw` sobre la columna de embeddings. En SQLite (pruebas) la similitud se calcula en Python, sin extensión.

## Preguntar y obtener fuentes (RAG)

Con la cabecera `Authorization: Bearer <token>`:

1. `POST /api/tenants/{tenant_id}/ask` con `{"question":"¿cada cuánto se cambia el filtro?","top_k":5}` devuelve `answer` (respuesta), `sources` (documento, versión, posición y puntaje de cada cita), `provider` y `insufficient_evidence`.
2. Acepta los mismos filtros que la búsqueda: `"space_id"` y `"metadata_filters"`.
3. Solo usa fragmentos de la **versión vigente** de documentos activos, y descarta los que tengan similitud casi nula. Si no hay evidencia, responde "No encontré información suficiente..." sin llamar al modelo.
4. El proveedor de chat por defecto (`extractive`) no es un modelo de IA: muestra los fragmentos con citas `[1]`, `[2]`, etc. Cualquier miembro puede preguntar.

### Proveedor de chat

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `KORVIA_CHAT_PROVIDER` | `extractive` | `extractive` (sin red) u `openai` (endpoint compatible con OpenAI). |
| `KORVIA_CHAT_API_KEY` | (vacía) | Clave API, obligatoria si eliges `openai`. |
| `KORVIA_CHAT_MODEL` | `gpt-4o-mini` | Modelo de lenguaje. |
| `KORVIA_CHAT_BASE_URL` | `https://api.openai.com/v1` | Cambia la URL para usar tu proveedor. |
| `KORVIA_MIN_ANSWER_SCORE` | `0.05` | Similitud mínima para considerar un fragmento como evidencia. |

Con `openai`, la pregunta y los fragmentos se envían a ese proveedor. El mensaje de sistema le pide responder solo con el contexto y citar `[n]`; aun así, revisa las fuentes antes de confiar en la respuesta. Claude Code no ofrece un endpoint de chat usable desde la API, pero cualquier proveedor compatible con `/chat/completions` funciona indicando su URL y clave.

Con Docker, pon estas variables en un archivo `.env` junto a `compose.yaml` (o expórtalas antes de `docker compose up`). `compose.yaml` ya las pasa al contenedor. No subas ese archivo con tus claves a Git.

## Sincronizar una carpeta

KORVIA puede revisar una carpeta local y traer los cambios automáticamente.

1. Con Docker, deja tus PDF, DOCX o XLSX en `data/entrada` (ya está creada y se monta como solo lectura).
2. Ejecuta `POST /api/tenants/{tenant_id}/spaces/{space_id}/sync` con un token de dueño o administrador.
3. La respuesta dice cuántos archivos se crearon, se actualizaron, quedaron igual, se eliminaron y fallaron.
4. `GET /api/tenants/{tenant_id}/spaces/{space_id}/sync` muestra la última sincronización y el estado de cada archivo.

Un archivo nuevo se guarda como documento; si cambia, crea una nueva versión; si desaparece de la carpeta, el documento se oculta (no se borra su historial). Dos archivos con el mismo nombre en carpetas distintas se tratan como documentos distintos. Los archivos demasiado grandes se informan como error y no se guardan.

Fuera de Docker, configura `KORVIA_SYNC_ROOT` con la ruta de la carpeta. Si no está configurada, el endpoint devuelve un error claro. Por ahora la sincronización se ejecuta cuando tú llamas al endpoint; todavía no es automática ni periódica.

## Ejecutar pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Cambios en la base de datos

El esquema se controla con Alembic. Al arrancar la API se aplican las migraciones pendientes automáticamente. Para crear una migración nueva después de cambiar `backend/korvia/models.py`:

```bash
cd backend
DATABASE_URL="sqlite:///./data/korvia.db" python -m alembic revision --autogenerate -m "descripción del cambio"
```

Revisa siempre el archivo generado en `backend/alembic/versions` antes de usarlo. Para ver el estado actual: `python -m alembic current`.

## Privacidad y límites

- Los archivos originales se guardan en `data/uploads` y la información organizada en PostgreSQL.
- La API escucha solo en `127.0.0.1`; no debe exponerse a Internet.
- El límite inicial de carga es 25 MB y puede cambiarse con `KORVIA_MAX_UPLOAD_BYTES`.
- Los embeddings tienen 384 dimensiones. Si cambias de proveedor, ejecuta el reindexado para regenerar los vectores con el nuevo modelo.
- La sincronización detecta cambios solo cuando se llama al endpoint; aún no hay un programador que la ejecute sola.
- En el entorno local de Python, el OCR requiere instalar Tesseract OCR y los idiomas español e inglés. La imagen Docker ya los incluye.
- Las contraseñas se guardan con PBKDF2 y los tokens como hash, pero la API sigue siendo local de prueba: no está preparada para Internet sin añadir HTTPS, rate limiting y recuperación de contraseña.
