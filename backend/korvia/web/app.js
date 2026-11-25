const $ = (id) => document.getElementById(id);
const state = {
  token: localStorage.getItem("korvia_token") || "",
  me: null,
  tenantId: "",
  spaceId: "",
  role: "",
};

const ACTIONS = {
  registro: "Creó la empresa",
  inicio_sesion: "Entró",
  cierre_sesion: "Salió",
  crear_empresa: "Creó una empresa",
  invitar_miembro: "Invitó a una persona",
  crear_espacio: "Creó un área",
  subir_documento: "Subió un documento",
  cambiar_metadata: "Cambió datos de un documento",
  ocultar_documento: "Ocultó un documento",
  restaurar_documento: "Restauró un documento",
  reindexar: "Actualizó la búsqueda",
  pregunta: "Hizo una pregunta",
  crear_agente: "Creó un agente",
  ejecutar_agente: "Ejecutó un agente",
  sincronizar: "Sincronizó archivos",
};

function notify(text, error = false) {
  const box = $("mensaje");
  box.textContent = text || "";
  box.classList.toggle("error", Boolean(error));
  if (text) {
    window.setTimeout(() => {
      if (box.textContent === text) box.textContent = "";
    }, 6000);
  }
}

function add(parent, tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  parent.appendChild(element);
  return element;
}

function clear(node) {
  node.replaceChildren();
}

function detailText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(detailText).join("; ");
  if (detail && typeof detail === "object") {
    if (typeof detail.msg === "string") {
      const parts = Array.isArray(detail.loc) ? detail.loc.filter((part) => part !== "body") : [];
      const field = parts.length ? `${parts.join(".")}: ` : "";
      return field + detail.msg;
    }
    if (detail.detail !== undefined) return detailText(detail.detail);
    return Object.entries(detail).map(([key, value]) => `${key}: ${detailText(value)}`).join("; ");
  }
  return String(detail ?? "");
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(detailText(data && data.detail) || `No se pudo completar la acción (${response.status}).`);
  }
  return data;
}

async function run(action) {
  try {
    await action();
  } catch (error) {
    notify(error.message, true);
  }
}

const tenantPath = () => `/api/tenants/${encodeURIComponent(state.tenantId)}`;
const spacePath = () => `${tenantPath()}/spaces/${encodeURIComponent(state.spaceId)}`;
const canWrite = () => state.role === "owner" || state.role === "admin";

function setRole() {
  const membership = state.me.memberships.find((item) => item.tenant_id === state.tenantId);
  state.role = membership ? membership.role : "";
  const esMiembro = state.role === "member";
  $("role-label").textContent = esMiembro
    ? "Miembro · puede preguntar y ejecutar agentes"
    : "Puedes gestionar";
  $("space-form").hidden = esMiembro;
  $("upload-form").hidden = esMiembro;
  document.querySelector('[data-tab="actividad"]').hidden = esMiembro;
}

function showApp() {
  $("login-panel").hidden = true;
  $("app-panel").hidden = false;
}

async function loadMe() {
  state.me = await api("/api/auth/me");
  const session = $("session");
  clear(session);
  add(session, "span", state.me.user.email, "muted");
  const exit = add(session, "button", "Salir", "link");
  exit.type = "button";
  exit.onclick = () => run(logout);

  const tenants = $("tenant-select");
  clear(tenants);
  state.me.memberships.forEach((membership) => {
    const option = document.createElement("option");
    option.value = membership.tenant_id;
    option.textContent = membership.tenant_name;
    tenants.appendChild(option);
  });
  state.tenantId = state.me.memberships[0].tenant_id;
  tenants.value = state.tenantId;
  setRole();
  showApp();
  await loadSpaces();
  if (canWrite()) await loadAudit();
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  state.token = "";
  state.me = null;
  localStorage.removeItem("korvia_token");
  $("app-panel").hidden = true;
  $("login-panel").hidden = false;
  clear($("session"));
  notify("Sesión cerrada.");
}

async function loadSpaces() {
  const spaces = await api(`${tenantPath()}/spaces`);
  const select = $("space-select");
  clear(select);
  spaces.forEach((space) => {
    const option = document.createElement("option");
    option.value = space.id;
    option.textContent = space.name;
    select.appendChild(option);
  });
  state.spaceId = spaces.length ? spaces[0].id : "";
  select.value = state.spaceId;
  await loadDocuments();
  await loadAgents();
}

async function loadDocuments() {
  const list = $("document-list");
  clear(list);
  clear($("document-detail"));
  if (!state.spaceId) {
    add(list, "p", "Crea un área para poder subir documentos.", "muted");
    return;
  }
  const data = await api(`${spacePath()}/documents`);
  if (!data.documents.length) {
    add(list, "p", "Todavía no hay documentos en esta área.", "muted");
    return;
  }
  data.documents.forEach((document) => {
    const row = add(list, "div", null, "item");
    add(row, "strong", document.filename);
    add(row, "span", `Versión ${document.version_count} · ${document.chunk_count} fragmentos`, "muted");
    const metadata = Object.entries(document.metadata || {})
      .map(([key, value]) => `${key}: ${value}`)
      .join(" · ");
    if (metadata) add(row, "small", metadata, "muted");
    const view = add(row, "button", "Ver texto", "link");
    view.type = "button";
    view.onclick = () => run(() => viewDocument(document.id));
    if (canWrite()) {
      const hide = add(row, "button", "Ocultar", "link danger");
      hide.type = "button";
      hide.onclick = () => run(async () => {
        await api(`${spacePath()}/documents/${document.id}`, { method: "DELETE" });
        notify("Documento ocultado.");
        await loadDocuments();
      });
    }
  });
}

async function viewDocument(documentId) {
  const document = await api(`${spacePath()}/documents/${documentId}`);
  const detail = $("document-detail");
  clear(detail);
  add(detail, "h3", `${document.filename} — versión ${document.version}`);
  if (!document.chunks.length) {
    add(detail, "p", "Este documento no tiene texto extraído.", "muted");
    return;
  }
  document.chunks.forEach((chunk) => {
    const block = add(detail, "div", null, "fragment");
    add(block, "strong", `Fragmento ${chunk.position + 1}`);
    add(block, "p", chunk.text);
    add(block, "small", (chunk.sources || []).join(" · "), "muted");
  });
}

async function searchDocuments(query) {
  const results = await api(`${tenantPath()}/search`, {
    method: "POST",
    body: JSON.stringify({ query, top_k: 5 }),
  });
  const list = $("search-results");
  clear(list);
  if (!results.results.length) {
    add(list, "p", "No encontré fragmentos parecidos.", "muted");
    return;
  }
  results.results.forEach((result) => {
    const row = add(list, "div", null, "item");
    add(row, "strong", result.document_filename);
    add(row, "span", `Similitud ${result.score} · ${(result.sources || []).join(", ")}`, "muted");
    add(row, "p", result.text);
  });
}

async function askQuestion(question) {
  const answer = await api(`${tenantPath()}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, top_k: 5 }),
  });
  const box = $("ask-answer");
  clear(box);
  add(box, "h3", "Respuesta");
  add(box, "p", answer.answer);
  if (answer.sources.length) {
    add(box, "h4", "Fuentes");
    answer.sources.forEach((source) => {
      add(box, "p", `[${source.number}] ${source.filename} · versión ${source.version}`, "muted");
    });
  }
}

async function loadAgents() {
  const list = $("agent-list");
  clear(list);
  const agents = await api(`${tenantPath()}/agents`);
  if (!agents.length) {
    add(list, "p", "Todavía no hay agentes.", "muted");
    return;
  }
  agents.forEach((agent) => {
    const row = add(list, "div", null, "item");
    add(row, "strong", agent.name);
    add(row, "small", `${agent.steps.length} pasos`, "muted");
    const execute = add(row, "button", "Ejecutar", "link");
    execute.type = "button";
    execute.onclick = () => run(async () => {
      const result = await api(`${tenantPath()}/agents/${agent.id}/run`, { method: "POST", body: "{}" });
      const box = $("agent-result");
      clear(box);
      add(box, "h3", `Informe: ${agent.name}`);
      add(box, "pre", result.report, "report");
    });
    const history = add(row, "button", "Historial", "link");
    history.type = "button";
    history.onclick = () => run(async () => {
      const runs = await api(`${tenantPath()}/agents/${agent.id}/runs`);
      const box = $("agent-result");
      clear(box);
      add(box, "h3", `Historial: ${agent.name}`);
      if (!runs.length) add(box, "p", "Todavía no se ha ejecutado.", "muted");
      runs.forEach((entry) => {
        const line = add(box, "p", null, "item");
        add(line, "span", new Date(entry.started_at).toLocaleString());
        add(line, "span", `${ACTIONS.ejecutar_agente}: ${entry.status} · ${entry.steps_count} pasos`, "muted");
      });
    });
  });
}

async function loadAudit() {
  const list = $("audit-list");
  clear(list);
  const events = await api(`${tenantPath()}/audit?limit=50`);
  if (!events.length) {
    add(list, "p", "Todavía no hay actividad registrada.", "muted");
    return;
  }
  events.forEach((event) => {
    const row = add(list, "div", null, "item");
    add(row, "strong", ACTIONS[event.action] || event.action);
    add(row, "span", event.summary || "", "muted");
    add(row, "small", `${event.actor_email || ""} · ${new Date(event.created_at).toLocaleString()}`, "muted");
  });
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((section) => {
    section.hidden = section.id !== `tab-${name}`;
  });
  document.querySelectorAll("#tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
}

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async () => {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: $("login-email").value, password: $("login-password").value }),
    });
    state.token = data.token;
    localStorage.setItem("korvia_token", data.token);
    $("login-password").value = "";
    notify("Bienvenido.");
    await loadMe();
  });
});

$("register-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async () => {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: $("register-email").value,
        password: $("register-password").value,
        company_name: $("register-company").value,
      }),
    });
    state.token = data.token;
    localStorage.setItem("korvia_token", data.token);
    $("register-password").value = "";
    notify("Cuenta creada.");
    await loadMe();
  });
});

$("tenant-select").addEventListener("change", () => run(async () => {
  state.tenantId = $("tenant-select").value;
  setRole();
  await loadSpaces();
  if (canWrite()) await loadAudit();
}));

$("space-select").addEventListener("change", () => run(async () => {
  state.spaceId = $("space-select").value;
  await loadDocuments();
}));

$("space-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = $("space-name").value.trim();
  if (!name) return;
  run(async () => {
    await api(`${tenantPath()}/spaces`, { method: "POST", body: JSON.stringify({ name }) });
    $("space-name").value = "";
    notify("Área creada.");
    await loadSpaces();
  });
});

$("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = $("upload-file").files[0];
  if (!file) return;
  if (!state.spaceId) {
    notify("Elige un área antes de subir el archivo.", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  run(async () => {
    const document = await api(`${spacePath()}/documents`, { method: "POST", body });
    notify(`Guardado: ${document.filename} (versión ${document.version}).`);
    $("upload-file").value = "";
    await loadDocuments();
  });
});

$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(() => searchDocuments($("search-query").value.trim()));
});

$("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(() => askQuestion($("ask-question").value.trim()));
});

$("agent-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const steps = $("agent-steps").value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!steps.length) {
    notify("Escribe al menos una pregunta.", true);
    return;
  }
  run(async () => {
    await api(`${tenantPath()}/agents`, {
      method: "POST",
      body: JSON.stringify({ name: $("agent-name").value.trim(), steps }),
    });
    $("agent-name").value = "";
    $("agent-steps").value = "";
    notify("Agente creado.");
    await loadAgents();
  });
});

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

if (state.token) {
  loadMe().catch((error) => {
    notify(error.message, true);
    state.token = "";
    localStorage.removeItem("korvia_token");
    $("app-panel").hidden = true;
    $("login-panel").hidden = false;
  });
}
