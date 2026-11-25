# KORVIA — MASTER PROJECT CONTEXT

## 1. VISIÓN GENERAL

KORVIA es una plataforma de conocimiento empresarial conectada con inteligencia artificial. Su objetivo es conectar, procesar, organizar y mantener actualizada la información de una empresa para que pueda consultarse mediante IA, obtener respuestas confiables y posteriormente ejecutar tareas y automatizaciones.

No queremos construir simplemente un chatbot con RAG. Queremos desarrollar una infraestructura de conocimiento empresarial que pueda evolucionar hacia una plataforma de IA y automatización.

Propuesta de valor:
"KORVIA convierte la información dispersa de tu empresa en conocimiento organizado, actualizado y consultable mediante inteligencia artificial."

El cliente no debe necesitar conocimientos técnicos sobre embeddings, bases vectoriales, OCR o RAG. Debe poder conectar sus fuentes de información y utilizar KORVIA de manera sencilla.

## 2. PROBLEMA QUE RESOLVEMOS

Las empresas tienen información distribuida en:
- PDF, Word, Excel, CSV e imágenes.
- Carpetas locales y servidores.
- SharePoint y OneDrive.
- Bases de datos.
- ERP y CRM.
- Correos y sistemas internos.

La información suele estar desorganizada, duplicada, dispersa y difícil de consultar. Además, cambia constantemente: se crean documentos, se modifican archivos, se agregan registros y se eliminan datos.

KORVIA debe resolver tanto el acceso al conocimiento como su actualización continua.

## 3. ARQUITECTURA CONCEPTUAL

Fuentes empresariales
↓
Ingesta
↓
OCR / extracción
↓
Limpieza / normalización
↓
Metadata / clasificación
↓
Knowledge Layer
↓
RAG / Search
↓
AI Assistant
↓
Agents
↓
Automatización

### Función de cada componente

1. Fuentes empresariales: lugares donde reside la información de la empresa.
2. Ingesta: recibe archivos, registros o información desde conectores.
3. OCR / extracción: convierte documentos e imágenes en contenido procesable; extrae también tablas y datos estructurados.
4. Limpieza / normalización: corrige inconsistencias, elimina contenido innecesario y estandariza formatos.
5. Metadata / clasificación: identifica tipo de documento, área, fecha, tema, entidad, confidencialidad y otros atributos.
6. Knowledge Layer: capa central que organiza documentos, fragmentos, registros, entidades y relaciones. Permite consultar el conocimiento independientemente de la fuente original.
7. RAG / Search: recupera información relevante mediante búsqueda semántica, textual y filtros por metadata.
8. AI Assistant: responde preguntas utilizando el contexto recuperado y mostrando fuentes verificables.
9. Agents: ejecutan tareas de varios pasos utilizando herramientas y datos autorizados.
10. Automatización: permite ejecutar acciones en sistemas empresariales mediante APIs, integraciones y flujos controlados.

## 4. SINCRONIZACIÓN CONTINUA — COMPONENTE FUNDAMENTAL

KORVIA no puede quedarse con una copia estática de la información. Debe mantener su conocimiento sincronizado con las fuentes originales.

Diseñar un Sync Engine encargado de:

- Detectar documentos nuevos.
- Detectar archivos modificados.
- Detectar eliminaciones.
- Detectar registros nuevos o actualizados en bases de datos.
- Procesar únicamente los cambios necesarios.
- Actualizar los fragmentos, embeddings e índices afectados.
- Mantener versiones e historial de procesamiento.
- Evitar duplicados.
- Reintentar procesos fallidos.
- Registrar errores y estado de sincronización.
- Mostrar cuándo fue la última sincronización.

Métodos técnicos según la fuente:
- Archivos: hash de contenido, tamaño, fecha de modificación y versión.
- SharePoint / OneDrive: APIs, notificaciones de cambios y sincronización incremental.
- Bases de datos: campos updated_at, identificadores incrementales, CDC cuando sea viable.
- Otras integraciones: webhooks, APIs o consultas periódicas.

Manejar correctamente:
- Creación.
- Modificación.
- Eliminación.
- Reemplazo de documentos.
- Versiones antiguas y vigentes.
- Fallos parciales de sincronización.

La fuente empresarial original sigue siendo la fuente de verdad. KORVIA mantiene una representación derivada y actualizada de su información.

No se debe eliminar información vigente del índice hasta confirmar que la nueva versión fue procesada correctamente. El sistema debe evitar respuestas basadas en versiones obsoletas.

## 5. KNOWLEDGE LAYER

Es una de las partes estratégicas del producto.

No debe ser solamente una colección de embeddings. Debe organizar:
- Empresas y espacios de conocimiento.
- Fuentes de información.
- Documentos y versiones.
- Fragmentos de documentos.
- Registros estructurados.
- Entidades empresariales.
- Relaciones entre entidades.
- Metadata y permisos.
- Procedencia y trazabilidad.

Ejemplo:

Máquina X
├── Manual técnico
├── Procedimiento de mantenimiento
├── Historial de mantenimiento
├── Repuestos
└── Técnico responsable

La capa debe permitir relacionar información que proviene de diferentes documentos y sistemas.

Debe diseñarse de manera modular para poder evolucionar sin depender de una tecnología específica.

## 6. RAG / SEARCH

Cuando un usuario hace una pregunta:

1. KORVIA recibe la pregunta.
2. Identifica el contexto y los permisos del usuario.
3. Busca información relevante en el conocimiento empresarial.
4. Combina búsqueda semántica, textual y filtros.
5. Recupera los fragmentos y registros necesarios.
6. Envía el contexto al modelo de IA.
7. Genera una respuesta fundamentada.
8. Muestra documentos, páginas o registros de origen.

Las respuestas deben poder indicar cuando no existe información suficiente. No se debe inventar información.

## 7. AI ASSISTANT

Es la interfaz conversacional para los empleados.

Ejemplos:
- ¿Cuál es el procedimiento de mantenimiento de la máquina X?
- ¿Cuándo fue el último mantenimiento?
- ¿Qué documentos hablan sobre seguridad industrial?
- ¿Qué proveedores tenemos registrados?

Debe responder con lenguaje natural, fuentes, referencias y contexto empresarial autorizado.

## 8. AGENTS Y AUTOMATIZACIÓN

Evolución posterior:

Un Assistant responde preguntas.

Un Agent puede ejecutar tareas de varios pasos utilizando herramientas autorizadas.

Ejemplo:
"Analiza los mantenimientos y dime cuáles están atrasados."

El Agent:
1. Consulta los datos.
2. Identifica las máquinas.
3. Consulta periodicidades.
4. Compara fechas.
5. Identifica atrasos.
6. Genera un reporte.

Automatizaciones futuras:
- Enviar correos.
- Crear tareas.
- Generar informes.
- Registrar información en ERP/CRM.
- Notificar eventos.
- Ejecutar flujos de trabajo.

Las acciones sensibles deben requerir autorización, permisos y confirmación cuando corresponda. Registrar auditoría de las acciones realizadas.

## 9. ARQUITECTURA TÉCNICA INICIAL

Stack propuesto para el MVP:

- Backend: Python + FastAPI.
- Base de datos: PostgreSQL.
- Búsqueda vectorial: pgvector.
- Frontend: React / Next.js.
- Procesamiento: librerías de extracción de PDF, DOCX, XLSX y OCR.
- IA: integración modular con proveedores LLM.
- Embeddings: proveedor intercambiable.
- Archivos: almacenamiento de objetos.
- Procesos en segundo plano: cola de tareas y workers.
- Infraestructura: Docker.

No son tecnologías inamovibles. Evaluar cada decisión según escalabilidad, costos, mantenimiento y necesidades reales.

Separar módulos para:
- Autenticación y usuarios.
- Empresas y espacios de conocimiento.
- Gestión de fuentes.
- Ingesta.
- Extracción.
- Procesamiento.
- Metadata.
- Knowledge Layer.
- Search / RAG.
- AI Assistant.
- Sincronización.
- Agents.
- Automatización.
- Auditoría y monitoreo.

## 10. SEGURIDAD Y MULTITENANCY

KORVIA está dirigido a empresas. La seguridad es fundamental.

Diseñar desde el inicio:
- Separación de datos por empresa (tenant).
- Autenticación y autorización.
- Roles y permisos.
- Control de acceso a documentos y respuestas.
- Protección de archivos y credenciales.
- Cifrado en tránsito y en reposo.
- Registro de actividad y auditoría.
- Aislamiento de consultas entre empresas.
- Gestión segura de conectores y tokens.

La IA nunca debe recuperar información a la que el usuario no tenga permiso de acceder. Los permisos deben aplicarse durante la recuperación, no solamente en la interfaz.

## 11. MODELO DE NEGOCIO

Clientes iniciales:
- Empresas de 20 a 200 empleados.
- Manufactura e ingeniería.
- Construcción y proyectos técnicos.
- BPO y servicios empresariales.

Enfoque geográfico inicial: Antioquia, Colombia.

Problema comercial:
Los empleados pierden tiempo buscando información que la empresa ya tiene.

KORVIA vende:
- Reducción del tiempo de búsqueda.
- Productividad.
- Acceso centralizado al conocimiento.
- Respuestas fundamentadas.
- Mejor aprovechamiento de información existente.
- Automatización futura.

Modelo de ingresos:
- Implementación inicial.
- Suscripción SaaS mensual.
- Integraciones y personalizaciones.
- Planes empresariales.

Los rangos económicos iniciales son hipótesis por validar, no precios de mercado confirmados.

Estrategia comercial:
1. Identificar empresas con problemas reales de información.
2. Entender sus fuentes y procesos.
3. Demostrar KORVIA con documentos reales autorizados.
4. Ejecutar un piloto de 2 a 4 semanas.
5. Medir tiempo ahorrado y calidad de respuestas.
6. Convertir el piloto en cliente recurrente.

Objetivo de validación: conseguir empresas dispuestas a pagar antes de construir funcionalidades innecesarias.

## 12. ROADMAP DE DESARROLLO

FASE 1 — MVP:
- Registro y autenticación.
- Empresas y usuarios.
- Espacios de conocimiento.
- Carga de PDF, Word y Excel.
- Extracción de contenido.
- Procesamiento y metadata básica.
- PostgreSQL + pgvector.
- RAG.
- Chat con fuentes verificables.
- Gestión básica de documentos.

FASE 2 — CONOCIMIENTO Y SINCRONIZACIÓN:
- Knowledge Layer más completa.
- Versionado.
- Detección de cambios.
- Sync Engine.
- Procesamiento incremental.
- Eliminaciones y documentos obsoletos.
- Conectores para SharePoint y bases de datos.
- Mejor búsqueda híbrida.
- Permisos por documento.

FASE 3 — INTELIGENCIA:
- AI Assistant avanzado.
- Consultas sobre datos estructurados.
- Relaciones entre entidades.
- Análisis y reportes.
- Agents con herramientas controladas.

FASE 4 — AUTOMATIZACIÓN:
- Integraciones ERP y CRM.
- Email y otros sistemas.
- Flujos automáticos.
- Ejecución de acciones con auditoría y autorización.

No construir todas las fases al mismo tiempo. Priorizar un MVP funcional y validar con empresas reales.

## 13. PRINCIPIOS DE DISEÑO

1. Modularidad: cada componente debe poder evolucionar independientemente.
2. Escalabilidad: preparar la arquitectura para múltiples empresas.
3. Independencia tecnológica: evitar depender de un único LLM, proveedor de embeddings o base vectorial.
4. Actualización continua: el conocimiento debe reflejar los cambios de las fuentes.
5. Trazabilidad: las respuestas deben mostrar de dónde proviene la información.
6. Seguridad: aislamiento estricto de datos y permisos.
7. Simplicidad: el usuario empresarial no debe conocer la complejidad técnica.
8. Eficiencia: procesar solamente lo nuevo o modificado cuando sea posible.
9. Fiabilidad: registrar errores, reintentar y evitar duplicados.
10. Viabilidad comercial: desarrollar funcionalidades que resuelvan problemas por los que las empresas estén dispuestas a pagar.

## 14. INSTRUCCIONES PARA LA IA QUE DESARROLLARÁ KORVIA

Actúa como arquitecto de software, ingeniero senior y responsable técnico del desarrollo de KORVIA.

Tu misión es convertir esta visión en un producto funcional, mantenible, seguro y comercialmente viable.

Antes de escribir código:
1. Analiza el repositorio y los archivos existentes.
2. Identifica qué está construido y qué falta.
3. Revisa la arquitectura, dependencias, estructura y documentación.
4. No reemplaces ni modifiques funcionalidades existentes sin comprenderlas.
5. Identifica problemas técnicos y riesgos.
6. Propón un plan de ejecución por etapas.

Durante el desarrollo:
- Trabaja en funcionalidades pequeñas y verificables.
- Explica brevemente qué estás construyendo y por qué.
- Mantén una arquitectura modular.
- Escribe código limpio y mantenible.
- Incluye pruebas.
- Documenta decisiones importantes.
- No simules funcionalidades que todavía no existen.
- No construyas integraciones ficticias.
- No agregues complejidad sin necesidad.
- Considera seguridad, permisos y aislamiento desde el inicio.
- Mantén actualizado el estado del proyecto.

Si utilizas Git o trabajas con varias sesiones de IA, evita modificar simultáneamente los mismos archivos y coordina ramas y cambios.

## 15. PRIMER OBJETIVO DE EJECUCIÓN

Comienza realizando una auditoría técnica del proyecto existente.

Entrega:
1. Estado actual del proyecto.
2. Arquitectura existente.
3. Funcionalidades terminadas.
4. Funcionalidades incompletas.
5. Errores o riesgos detectados.
6. Diferencias frente a la arquitectura objetivo de KORVIA.
7. Plan priorizado de implementación.
8. Primera tarea concreta para comenzar.

No comiences reescribiendo todo. Conserva lo que funcione y construye progresivamente sobre una base sólida.

## VISIÓN FINAL

KORVIA debe evolucionar así:

INFORMACIÓN DISPERSA
↓
CONOCIMIENTO ORGANIZADO
↓
CONOCIMIENTO ACTUALIZADO
↓
BÚSQUEDA INTELIGENTE
↓
RESPUESTAS CONFIABLES
↓
AGENTES INTELIGENTES
↓
AUTOMATIZACIÓN EMPRESARIAL

La meta es convertir KORVIA en una plataforma de conocimiento empresarial e infraestructura de IA que permita a las organizaciones aprovechar su información, tomar mejores decisiones y automatizar procesos.