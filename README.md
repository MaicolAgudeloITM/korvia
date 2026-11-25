# KORVIA

Guarda tus documentos (PDF, DOCX y XLSX) y haz preguntas sobre ellos. Las respuestas muestran de qué archivo salieron.

**Aviso:** es un prototipo para usar en tu computador. No lo expongas a Internet ni subas información confidencial.

## Ponerlo en marcha

Necesitas Docker Desktop.

```bash
docker compose up --build
```

Luego abre **http://127.0.0.1:8000**. Ahí está la página web. Si prefieres probar la API directamente, abre **http://127.0.0.1:8000/docs**.

## Primeros pasos

1. En la página web, pulsa **¿No tienes cuenta? Crear una** y escribe correo, contraseña y empresa.
2. Crea un área, por ejemplo "General", y sube un PDF, Word o Excel.
3. Ve a **Buscar** para encontrar fragmentos o a **Preguntas** para obtener una respuesta con fuentes.
4. En **Agentes** puedes crear una lista de preguntas y generar un informe.

La página guarda la sesión en tu navegador. Para salir, pulsa **Salir** arriba a la derecha.

## Qué puedes hacer

- **Subir documentos.** Si subes otro con el mismo nombre, se guarda como una versión nueva.
- **Buscar.** `POST /api/tenants/{tenant_id}/search` con `{"query":"texto a buscar"}`.
- **Preguntar.** La respuesta trae citas `[1]`, `[2]` con el archivo de origen. Si no hay información, dice que no encontró nada.
- **Sincronizar una carpeta.** Deja tus archivos en `data/entrada` y llama a `POST /api/tenants/{tenant_id}/spaces/{space_id}/sync`. Los cambios se aplican cuando ejecutas esa orden.
- **Usar un agente.** Varias preguntas ejecutadas en orden que entregan un informe con fuentes.
- **Ver la actividad.** `GET /api/tenants/{tenant_id}/audit` muestra quién hizo cada acción. Solo dueño o administrador.
- **Invitar personas.** `POST /api/tenants/{tenant_id}/members`. Dueño y administrador pueden subir archivos y crear agentes; los miembros pueden preguntar y ejecutarlos.

## Agentes

Un agente es una tarea con varias preguntas. Dueño y administrador lo crean; cualquier miembro puede ejecutarlo.

1. Créalo con `POST /api/tenants/{tenant_id}/agents` y `{"name":"Revisión","steps":["¿cada cuánto se cambia el filtro?","¿quién lo revisa?"]}`.
2. Ejecútalo con `POST /api/tenants/{tenant_id}/agents/{agent_id}/run`. Devuelve un informe con la respuesta y las citas de cada paso.
3. Consulta el historial con `GET /api/tenants/{tenant_id}/agents/{agent_id}/runs`: cuándo se ejecutó, quién lo hizo y si falló.

Al crearlo puedes añadir `"space_id"` o `"metadata_filters"` para limitar qué documentos consulta. Si una pregunta no tiene evidencia, el informe lo dice en vez de inventar.

## Opciones

Crea un archivo `.env` junto a `compose.yaml` si quieres cambiar algo. Ese archivo no se sube a Git.

- `KORVIA_EMBEDDING_PROVIDER=openai` y `KORVIA_OPENAI_API_KEY`: para que la búsqueda entienda el significado, no solo las palabras.
- `KORVIA_CHAT_PROVIDER=openai` y `KORVIA_CHAT_API_KEY`: para que las respuestas sean redactadas por un modelo de IA.
- `KORVIA_CHAT_BASE_URL` y `KORVIA_OPENAI_BASE_URL`: para usar otro proveedor compatible en vez de OpenAI.
- `KORVIA_MAX_UPLOAD_BYTES`: tamaño máximo por archivo (25 MB por defecto).
- `KORVIA_LOGIN_MAX_FAILURES`: intentos fallidos de acceso permitidos (5 por defecto).
- `KORVIA_LOGIN_WINDOW_SECONDS`: tiempo en segundos para contar esos intentos (900 = 15 minutos).

Sin esas opciones KORVIA funciona igual, pero la búsqueda es básica y las respuestas solo muestran los fragmentos encontrados.

## Pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Límites

- La API escucha solo en tu computador (`127.0.0.1`).
- No hay recuperación de contraseña. Sí hay un límite de intentos fallidos, pero se guarda solo en memoria: se reinicia al arrancar y no se comparte entre servidores.
- Las respuestas llevan cabeceras básicas de seguridad; aun así, la API sigue siendo local de prueba.
- Si ejecutas Python sin Docker, el OCR necesita Tesseract instalado.
- Los archivos se guardan en `data/uploads` y los datos en PostgreSQL.
