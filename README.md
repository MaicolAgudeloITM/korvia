# KORVIA

Guarda tus documentos (PDF, DOCX y XLSX) y haz preguntas sobre ellos. Las respuestas muestran de qué archivo salieron.

**Aviso:** es un prototipo para usar en tu computador. No lo expongas a Internet ni subas información confidencial.

## Ponerlo en marcha

Necesitas Docker Desktop.

```bash
docker compose up --build
```

Luego abre **http://127.0.0.1:8000/docs**. Ahí puedes probar la API sin escribir código.

## Primeros pasos

1. En `/docs`, usa `POST /api/auth/register` con `email`, `password` y `company_name`. Te devuelve un `token`.
2. Pulsa **Authorize** arriba y pega `Bearer <token>`.
3. Crea un espacio con `POST /api/tenants/{tenant_id}/spaces` y `{"name":"General"}`.
4. Sube un archivo con `POST /api/tenants/{tenant_id}/spaces/{space_id}/documents`.
5. Pregunta con `POST /api/tenants/{tenant_id}/ask` y `{"question":"¿cada cuánto se cambia el filtro?"}`.

Para ver tus empresas y tu rol, usa `GET /api/auth/me`.

## Qué puedes hacer

- **Subir documentos.** Si subes otro con el mismo nombre, se guarda como una versión nueva.
- **Buscar.** `POST /api/tenants/{tenant_id}/search` con `{"query":"texto a buscar"}`.
- **Preguntar.** La respuesta trae citas `[1]`, `[2]` con el archivo de origen. Si no hay información, dice que no encontró nada.
- **Sincronizar una carpeta.** Deja tus archivos en `data/entrada` y llama a `POST /api/tenants/{tenant_id}/spaces/{space_id}/sync`. Los cambios se aplican cuando ejecutas esa orden.
- **Invitar personas.** `POST /api/tenants/{tenant_id}/members`. Dueño y administrador pueden subir archivos; los miembros solo pueden leer.

## Opciones

Crea un archivo `.env` junto a `compose.yaml` si quieres cambiar algo. Ese archivo no se sube a Git.

- `KORVIA_EMBEDDING_PROVIDER=openai` y `KORVIA_OPENAI_API_KEY`: para que la búsqueda entienda el significado, no solo las palabras.
- `KORVIA_CHAT_PROVIDER=openai` y `KORVIA_CHAT_API_KEY`: para que las respuestas sean redactadas por un modelo de IA.
- `KORVIA_CHAT_BASE_URL` y `KORVIA_OPENAI_BASE_URL`: para usar otro proveedor compatible en vez de OpenAI.
- `KORVIA_MAX_UPLOAD_BYTES`: tamaño máximo por archivo (25 MB por defecto).

Sin esas opciones KORVIA funciona igual, pero la búsqueda es básica y las respuestas solo muestran los fragmentos encontrados.

## Pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Límites

- La API escucha solo en tu computador (`127.0.0.1`).
- No hay recuperación de contraseña ni protección contra intentos repetidos.
- Si ejecutas Python sin Docker, el OCR necesita Tesseract instalado.
- Los archivos se guardan en `data/uploads` y los datos en PostgreSQL.
