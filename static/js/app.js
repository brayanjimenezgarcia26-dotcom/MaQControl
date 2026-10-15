
"use strict";

/* ==========================================
   MAQCONTROL - SISTEMA DE GESTIÓN
   JavaScript principal
========================================== */

const PAGE = document.body.dataset.page || "dashboard";
const API = "/api";

const CONFIG = {
    dashboard: {
        title: "Panel principal",
        subtitle: "Resumen de operaciones"
    },
    equipos: {
        title: "Gestión de equipos",
        subtitle: "Inventario de maquinaria pesada"
    },
    mantenimientos: {
        title: "Mantenimientos",
        subtitle: "Planificación y seguimiento"
    },
    fallas: {
        title: "Control de fallas",
        subtitle: "Incidencias y reparaciones"
    },
    reportes: {
        title: "Reportes",
        subtitle: "Indicadores e historial"
    }
};

const MODULES = {
    equipos: {
        singular: "equipo",
        title: "Inventario de maquinaria",
        columns: [
            ["codigo", "Código"],
            ["nombre", "Equipo"],
            ["marca", "Marca"],
            ["modelo", "Modelo"],
            ["horometro", "Horómetro"],
            ["ubicacion", "Ubicación"],
            ["estado", "Estado"]
        ],
        fields: [
            {name:"codigo",label:"Código del equipo",required:true},
            {name:"nombre",label:"Tipo de maquinaria",required:true},
            {name:"marca",label:"Marca"},
            {name:"modelo",label:"Modelo"},
            {name:"serie",label:"Número de serie"},
            {name:"horometro",label:"Horómetro actual",type:"number",min:0},
            {name:"ubicacion",label:"Ubicación"},
            {name:"estado",label:"Estado",type:"select",
             options:["Operativo","En mantenimiento","Fuera de servicio"]}
        ]
    },
    mantenimientos: {
        singular: "mantenimiento",
        title: "Programación de mantenimientos",
        columns: [
            ["equipo_codigo", "Código"],
            ["equipo_nombre", "Equipo"],
            ["tipo", "Tipo"],
            ["descripcion", "Actividad"],
            ["fecha", "Fecha"],
            ["responsable", "Responsable"],
            ["estado", "Estado"]
        ],
        fields: [
            {name:"equipo_id",label:"Equipo",type:"equipment",required:true},
            {name:"tipo",label:"Tipo",type:"select",
             options:["Preventivo","Correctivo"],required:true},
            {name:"descripcion",label:"Trabajo a realizar",
             type:"textarea",required:true},
            {name:"fecha",label:"Fecha programada",type:"date",required:true},
            {name:"horometro_objetivo",label:"Horómetro objetivo",
             type:"number",min:0},
            {name:"responsable",label:"Técnico responsable"},
            {name:"estado",label:"Estado",type:"select",
             options:["Pendiente","En proceso","Completado"]}
        ]
    },
    fallas: {
        singular: "falla",
        title: "Registro y seguimiento de fallas",
        columns: [
            ["equipo_codigo", "Código"],
            ["equipo_nombre", "Equipo"],
            ["descripcion", "Descripción"],
            ["prioridad", "Prioridad"],
            ["fecha", "Fecha"],
            ["responsable", "Responsable"],
            ["estado", "Estado"]
        ],
        fields: [
            {name:"equipo_id",label:"Equipo afectado",
             type:"equipment",required:true},
            {name:"descripcion",label:"Descripción de la falla",
             type:"textarea",required:true},
            {name:"prioridad",label:"Prioridad",type:"select",
             options:["Baja","Media","Alta","Crítica"]},
            {name:"fecha",label:"Fecha del reporte",type:"date",required:true},
            {name:"responsable",label:"Técnico asignado"},
            {name:"estado",label:"Estado",type:"select",
             options:["Abierta","En revisión","Resuelta"]},
            {name:"observaciones",label:"Observaciones técnicas",
             type:"textarea"}
        ]
    }
};

let records = [];
let equipmentOptions = [];
let currentModule = "";
let userInfo = null;

/* SEGURIDAD DE PRESENTACIÓN */

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function safeValue(value) {
    return escapeHTML(value === null || value === undefined
        ? "" : value);
}

function formatNumber(value) {
    return Number(value || 0).toLocaleString("es-PE", {
        maximumFractionDigits: 1
    });
}

function formatDate(value) {
    if (!value) return "Sin fecha";
    const parts = String(value).split("-");
    if (parts.length !== 3) return value;
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function todayISO() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2,"0");
    const day = String(d.getDate()).padStart(2,"0");
    return `${year}-${month}-${day}`;
}

/* COMUNICACIÓN CON PYTHON */

async function apiRequest(path, options = {}) {
    let response;

    try {
        response = await fetch(API + path, {
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {})
            },
            ...options
        });
    } catch {
        throw new Error(
            "No se pudo conectar con el servidor MAQCONTROL."
        );
    }

    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error("Respuesta inesperada del servidor.");
    }

    if (response.status === 401 && path !== "/login") {
        window.location.href = "/login";
        throw new Error("Sesión finalizada.");
    }

    if (!response.ok) {
        throw new Error(data.error || "No se pudo completar la operación.");
    }

    return data;
}

/* NOTIFICACIONES */

function toast(message, error = false) {
    document.querySelector(".toast")?.remove();

    const element = document.createElement("div");
    element.className = "toast" + (error ? " error" : "");
    element.textContent = message;
    element.setAttribute("role", "status");

    document.body.appendChild(element);

    setTimeout(() => element.remove(), 3500);
}

/* LOGIN */

function initializeLogin() {
    const form = document.getElementById("loginForm");
    const toggle = document.getElementById("togglePassword");
    const password = document.getElementById("password");

    toggle?.addEventListener("click", () => {
        const visible = password.type === "text";
        password.type = visible ? "password" : "text";
        toggle.textContent = visible ? "Mostrar" : "Ocultar";
    });

    form?.addEventListener("submit", async event => {
        event.preventDefault();

        const button = document.getElementById("loginButton");
        const error = document.getElementById("loginError");

        error.hidden = true;
        button.disabled = true;
        button.textContent = "Verificando acceso...";

        try {
            const result = await apiRequest("/login", {
                method: "POST",
                body: JSON.stringify({
                    usuario: document.getElementById("usuario").value,
                    password: password.value
                })
            });

            window.location.href = result.redirect;
        } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
            button.disabled = false;
            button.textContent = "Ingresar a MAQCONTROL →";
        }
    });
}

/* ESTRUCTURA VISUAL */

function navLink(key, icon, title) {
    return `
        <a class="nav-link ${PAGE === key ? "active" : ""}"
           href="/${key}">
            <span class="nav-icon">${icon}</span>
            <span>${title}</span>
        </a>
    `;
}

function renderShell() {
    const pageConfig = CONFIG[PAGE];

    document.getElementById("app").innerHTML = `
        <div class="app-layout">
            <div class="overlay" id="overlay"></div>

            <aside class="sidebar" id="sidebar">
                <div class="sidebar-brand">
                    <img src="/static/img/Logo.png" alt="MAQCONTROL">
                    <div>
                        <strong>MAQ<span class="accent">CONTROL</span></strong>
                        <small>GESTIÓN INDUSTRIAL</small>
                    </div>
                </div>

                <nav class="sidebar-menu" aria-label="Navegación">
                    <div class="menu-label">MENÚ PRINCIPAL</div>
                    ${navLink("dashboard","▦","Panel principal")}
                    ${navLink("equipos","⚙","Equipos")}
                    ${navLink("mantenimientos","▣","Mantenimientos")}
                    ${navLink("fallas","⚠","Fallas")}
                    <div class="menu-label">ANÁLISIS</div>
                    ${navLink("reportes","▥","Reportes")}
                </nav>

                <div class="sidebar-footer">
                    <p>MAQCONTROL · Versión académica</p>
                    <p>Gestión y seguimiento de maquinaria</p>
                </div>
            </aside>

            <div class="main-area">
                <header class="topbar">
                    <div class="topbar-left">
                        <button class="icon-button menu-toggle"
                                id="menuToggle"
                                aria-label="Abrir menú">☰</button>
                        <div>
                            <div class="topbar-title">
                                ${pageConfig.title}
                            </div>
                            <div class="topbar-subtitle">
                                ${pageConfig.subtitle}
                            </div>
                        </div>
                    </div>

                    <div class="topbar-right">
                        <div class="user-name">
                            <strong id="userName">Administrador</strong>
                            <div class="topbar-subtitle" id="userRole">
                                Administrador
                            </div>
                        </div>
                        <div class="user-avatar">MC</div>
                        <button class="btn btn-outline btn-small"
                                id="logoutButton">
                            Salir
                        </button>
                    </div>
                </header>

                <main class="content" id="pageContent">
                    <div class="empty-state">
                        Cargando información...
                    </div>
                </main>
            </div>
        </div>

        <div id="modalRoot"></div>
    `;

    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("overlay");

    document.getElementById("menuToggle").onclick = () => {
        sidebar.classList.add("open");
        overlay.classList.add("show");
    };

    overlay.onclick = () => {
        sidebar.classList.remove("open");
        overlay.classList.remove("show");
    };

    document.getElementById("logoutButton").onclick = async () => {
        try {
            await apiRequest("/logout", {method:"POST"});
            window.location.href = "/login";
        } catch (error) {
            toast(error.message, true);
        }
    };
}

function pageHeading(title, description, actions = "") {
    return `
        <div class="page-heading">
            <div>
                <span class="section-kicker">
                    PLATAFORMA MAQCONTROL
                </span>
                <h1>${title}</h1>
                <p>${description}</p>
            </div>
            <div class="page-actions">${actions}</div>
        </div>
    `;
}

function statCard(label, value, icon, foot) {
    return `
        <article class="stat-card">
            <div class="stat-top">
                <span class="stat-label">${label}</span>
                <span class="stat-icon">${icon}</span>
            </div>
            <div class="stat-value">${value}</div>
            <div class="stat-foot">${foot}</div>
        </article>
    `;
}

function badge(value) {
    const status = String(value || "");
    let color = "gray";

    if (["Operativo","Completado","Resuelta","Baja"].includes(status))
        color = "green";

    if (["Pendiente","En mantenimiento","Media"].includes(status))
        color = "orange";

    if (["Fuera de servicio","Abierta","Crítica","Alta"].includes(status))
        color = "red";

    if (["En proceso","En revisión","Preventivo"].includes(status))
        color = "blue";

    return `<span class="badge badge-${color}">
        ${escapeHTML(status)}
    </span>`;
}

/* DASHBOARD */

async function renderDashboard() {
    const data = await apiRequest("/resumen");
    const name = userInfo?.nombre || "Administrador";

    const equipmentPercent = data.disponibilidad;

    const maintenanceRows = data.proximos.map(item => `
        <div class="alert-item">
            <span class="stat-icon">▣</span>
            <div>
                <strong>${escapeHTML(item.equipo_codigo)}
                    · ${escapeHTML(item.descripcion)}</strong>
                <p>
                    ${formatDate(item.fecha)}
                    · ${escapeHTML(item.estado)}
                </p>
            </div>
        </div>
    `).join("");

    const faultRows = data.ultimas_fallas.map(item => `
        <div class="alert-item">
            <span class="stat-icon">⚠</span>
            <div>
                <strong>${escapeHTML(item.equipo_codigo)}
                    · ${escapeHTML(item.descripcion)}</strong>
                <p>
                    Prioridad: ${escapeHTML(item.prioridad)}
                    · ${escapeHTML(item.estado)}
                </p>
            </div>
        </div>
    `).join("");

    document.getElementById("pageContent").innerHTML = `
        ${pageHeading(
            "Centro de operaciones",
            "Consulta el estado general de tu maquinaria."
        )}

        <section class="welcome-banner">
            <div>
                <span class="banner-tag">BIENVENIDO A MAQCONTROL</span>
                <h2>Hola, ${escapeHTML(name)}</h2>
                <p>
                    Controla tus equipos, supervisa las incidencias
                    y mantén organizada la programación de servicios.
                </p>
            </div>
            <a href="/equipos" class="btn btn-primary banner-action">
                Ver equipos →
            </a>
        </section>

        <div class="notice">
            Los registros iniciales son datos de demostración
            para presentar y evaluar el prototipo.
        </div>

        <section class="stats-grid">
            ${statCard("Equipos registrados",data.total,"⚙",
                "Total del inventario")}
            ${statCard("Equipos operativos",data.operativos,"✓",
                "Disponibles según estado registrado")}
            ${statCard("Mantenimientos pendientes",
                data.mantenimientos_pendientes,"▣",
                "Servicios sin completar")}
            ${statCard("Fallas activas",data.fallas_activas,"⚠",
                "Incidencias sin resolver")}
        </section>

        <div class="dashboard-grid">
            <section class="panel">
                <div class="panel-title">
                    <h3>Próximos mantenimientos</h3>
                    <a href="/mantenimientos">Ver todos →</a>
                </div>
                <div class="alert-list">
                    ${maintenanceRows || `
                        <div class="empty-state">
                            No hay mantenimientos pendientes.
                        </div>`}
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Disponibilidad registrada</h3>
                </div>

                <div class="stat-value">${equipmentPercent}%</div>
                <p class="muted">
                    Equipos marcados como operativos
                </p>

                <div class="progress-track">
                    <div class="progress-fill"
                         style="width:${equipmentPercent}%"></div>
                </div>

                <div class="legend-list">
                    <div class="legend-item">
                        <span class="legend-name">
                            <i class="legend-dot dot-green"></i>
                            Operativos
                        </span>
                        <strong>${data.operativos}</strong>
                    </div>
                    <div class="legend-item">
                        <span class="legend-name">
                            <i class="legend-dot dot-orange"></i>
                            En mantenimiento
                        </span>
                        <strong>${data.en_mantenimiento}</strong>
                    </div>
                    <div class="legend-item">
                        <span class="legend-name">
                            <i class="legend-dot dot-red"></i>
                            Fuera de servicio
                        </span>
                        <strong>${data.fuera_servicio}</strong>
                    </div>
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Últimas fallas registradas</h3>
                    <a href="/fallas">Ver incidencias →</a>
                </div>
                <div class="alert-list">
                    ${faultRows || `
                        <div class="empty-state">
                            No se han registrado fallas.
                        </div>`}
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Accesos rápidos</h3>
                </div>
                <div class="alert-list">
                    <a href="/equipos" class="alert-item">
                        ⚙ Registrar o consultar maquinaria →
                    </a>
                    <a href="/mantenimientos" class="alert-item">
                        ▣ Programar un mantenimiento →
                    </a>
                    <a href="/fallas" class="alert-item">
                        ⚠ Registrar una falla →
                    </a>
                    <a href="/reportes" class="alert-item">
                        ▥ Consultar indicadores →
                    </a>
                </div>
            </section>
        </div>
    `;
}

/* TABLAS Y MÓDULOS */

function displayCell(key, value) {
    if (key === "estado" || key === "prioridad" || key === "tipo") {
        return badge(value);
    }

    if (key === "fecha") {
        return escapeHTML(formatDate(value));
    }

    if (key === "horometro") {
        return `${formatNumber(value)} h`;
    }

    const content = String(value ?? "—");
    const shortened = content.length > 65
        ? content.slice(0, 65) + "…" : content;

    return escapeHTML(shortened);
}

function tableHTML(module, data) {
    const config = MODULES[module];

    if (!data.length) {
        return `
            <div class="empty-state">
                <strong>No se encontraron registros</strong>
                Agrega un registro o modifica la búsqueda.
            </div>
        `;
    }

    return `
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        ${config.columns.map(c =>
                            `<th>${c[1]}</th>`
                        ).join("")}
                        <th>Acciones</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.map(record => `
                        <tr>
                            ${config.columns.map(c => `
                                <td>${displayCell(c[0],record[c[0]])}</td>
                            `).join("")}
                            <td>
                                <div class="table-actions">
                                    <button class="action-btn"
                                            data-edit="${record.id}">
                                        Editar
                                    </button>
                                    <button class="action-btn danger"
                                            data-delete="${record.id}">
                                        Eliminar
                                    </button>
                                </div>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;
}

async function renderModule(module) {
    currentModule = module;
    records = await apiRequest("/" + module);

    const config = MODULES[module];

    const content = document.getElementById("pageContent");

    content.innerHTML = `
        ${pageHeading(
            CONFIG[module].title,
            CONFIG[module].subtitle,
            `
            <button class="btn btn-outline" id="exportButton">
                ↓ Exportar CSV
            </button>
            <button class="btn btn-primary" id="newButton">
                + Nuevo ${config.singular}
            </button>
            `
        )}

        <section class="stats-grid">
            ${statCard("Registros",records.length,"▦",
                "Total registrado")}
            ${statCard("Equipos vinculados",
                new Set(records.map(x =>
                    module === "equipos" ? x.id : x.equipo_id
                )).size,"⚙","Equipos relacionados")}
            ${statCard("Actualización",formatDate(todayISO()),"▣",
                "Fecha de consulta")}
            ${statCard("Módulo activo","✓","●",
                "Información disponible")}
        </section>

        <section class="panel">
            <div class="panel-title">
                <h3>${config.title}</h3>
                <span class="muted text-small">
                    ${records.length} registros
                </span>
            </div>

            <div class="table-toolbar">
                <input class="search-input"
                       id="searchInput"
                       placeholder="Buscar por equipo, código o estado..."
                       aria-label="Buscar registros">
                <span class="muted text-small">
                    Selecciona Editar para modificar un registro
                </span>
            </div>

            <div id="tableContainer">
                ${tableHTML(module,records)}
            </div>
        </section>
    `;

    document.getElementById("newButton").onclick = () =>
        openForm(module);

    document.getElementById("exportButton").onclick = () => {
        window.location.href = `/api/exportar/${module}`;
    };

    document.getElementById("searchInput").oninput = event => {
        const term = event.target.value.toLowerCase().trim();

        const filtered = records.filter(record =>
            Object.values(record).some(value =>
                String(value ?? "").toLowerCase().includes(term)
            )
        );

        document.getElementById("tableContainer").innerHTML =
            tableHTML(module,filtered);
    };

    content.addEventListener("click", event => {
        const editButton = event.target.closest("[data-edit]");
        const deleteButton = event.target.closest("[data-delete]");

        if (editButton) {
            const record = records.find(x =>
                x.id === Number(editButton.dataset.edit)
            );
            if (record) openForm(module,record);
        }

        if (deleteButton) {
            removeRecord(module,Number(deleteButton.dataset.delete));
        }
    });
}

/* FORMULARIOS */

function fieldHTML(field, record = {}) {
    const value = record[field.name] ?? "";
    const id = `field_${field.name}`;
    const required = field.required ? "required" : "";

    let control = "";

    if (field.type === "textarea") {
        control = `
            <textarea id="${id}" name="${field.name}"
                      ${required}>${safeValue(value)}</textarea>
        `;
    } else if (field.type === "select") {
        control = `
            <select id="${id}" name="${field.name}" ${required}>
                ${!field.required ? `<option value="">Seleccionar</option>` : ""}
                ${field.options.map(option => `
                    <option value="${safeValue(option)}"
                        ${value === option ? "selected" : ""}>
                        ${escapeHTML(option)}
                    </option>
                `).join("")}
            </select>
        `;
    } else if (field.type === "equipment") {
        control = `
            <select id="${id}" name="${field.name}" required>
                <option value="">Selecciona un equipo</option>
                ${equipmentOptions.map(eq => `
                    <option value="${eq.id}"
                        ${Number(value) === eq.id ? "selected" : ""}>
                        ${escapeHTML(eq.codigo)}
                        - ${escapeHTML(eq.nombre)}
                    </option>
                `).join("")}
            </select>
        `;
    } else {
        control = `
            <input id="${id}"
                   name="${field.name}"
                   type="${field.type || "text"}"
                   value="${safeValue(
                       field.type === "date" && !value
                           ? todayISO() : value
                   )}"
                   ${field.min !== undefined ? `min="${field.min}"` : ""}
                   ${field.type === "number" ? `step="any"` : ""}
                   ${required}>
        `;
    }

    return `
        <div class="form-group ${field.type === "textarea"
            ? "form-span-2" : ""}">
            <label for="${id}">
                ${field.label}${field.required ? " *" : ""}
            </label>
            ${control}
        </div>
    `;
}

async function openForm(module, record = null) {
    const config = MODULES[module];

    if (module !== "equipos") {
        try {
            equipmentOptions = await apiRequest("/equipos");
        } catch (error) {
            toast(error.message,true);
            return;
        }

        if (!equipmentOptions.length) {
            toast("Primero registra un equipo de maquinaria.",true);
            return;
        }
    }

    const editing = Boolean(record);

    document.getElementById("modalRoot").innerHTML = `
        <div class="modal-backdrop" id="modalBackdrop">
            <div class="modal" role="dialog"
                 aria-modal="true"
                 aria-labelledby="modalTitle">

                <div class="modal-header">
                    <div>
                        <span class="section-kicker">MAQCONTROL</span>
                        <h3 id="modalTitle">
                            ${editing ? "Editar" : "Registrar"}
                            ${config.singular}
                        </h3>
                    </div>
                    <button class="icon-button"
                            id="closeModal"
                            aria-label="Cerrar">×</button>
                </div>

                <form id="recordForm">
                    <div class="modal-body">
                        <div class="form-grid">
                            ${config.fields.map(field =>
                                fieldHTML(field,record || {})
                            ).join("")}
                        </div>
                    </div>

                    <div class="modal-footer">
                        <button type="button"
                                class="btn btn-outline"
                                id="cancelModal">
                            Cancelar
                        </button>
                        <button type="submit"
                                class="btn btn-primary"
                                id="saveRecord">
                            Guardar registro
                        </button>
                    </div>
                </form>
            </div>
        </div>
    `;

    const close = () => {
        document.getElementById("modalRoot").innerHTML = "";
    };

    document.getElementById("closeModal").onclick = close;
    document.getElementById("cancelModal").onclick = close;

    document.getElementById("modalBackdrop").addEventListener(
        "click", event => {
            if (event.target.id === "modalBackdrop") close();
        }
    );

    document.getElementById("recordForm").onsubmit = async event => {
        event.preventDefault();

        const button = document.getElementById("saveRecord");
        button.disabled = true;
        button.textContent = "Guardando...";

        const form = new FormData(event.target);
        const payload = Object.fromEntries(form.entries());

        const path = editing
            ? `/${module}/${record.id}`
            : `/${module}`;

        try {
            await apiRequest(path, {
                method: editing ? "PUT" : "POST",
                body: JSON.stringify(payload)
            });

            close();
            toast(editing
                ? "Registro actualizado correctamente."
                : "Registro creado correctamente.");

            await renderModule(module);
        } catch (error) {
            toast(error.message,true);
            button.disabled = false;
            button.textContent = "Guardar registro";
        }
    };

    document.getElementById(
        `field_${config.fields[0].name}`
    )?.focus();
}

/* ELIMINACIÓN */

async function removeRecord(module, id) {
    const record = records.find(x => x.id === id);
    if (!record) return;

    const confirmed = window.confirm(
        "¿Seguro que deseas eliminar este registro? " +
        "Esta acción no se puede deshacer."
    );

    if (!confirmed) return;

    try {
        await apiRequest(`/${module}/${id}`, {
            method: "DELETE"
        });

        toast("Registro eliminado correctamente.");
        await renderModule(module);
    } catch (error) {
        toast(error.message,true);
    }
}

/* REPORTES */

function reportBar(label, value, total) {
    const percent = total > 0
        ? Math.min(100,(value / total) * 100)
        : 0;

    return `
        <div class="bar-row">
            <span>${escapeHTML(label)}</span>
            <div class="bar-track">
                <div class="bar-fill"
                     style="width:${percent}%"></div>
            </div>
            <strong>${value}</strong>
        </div>
    `;
}

async function renderReports() {
    const [summary, equipos, mantenimientos, fallas] =
        await Promise.all([
            apiRequest("/resumen"),
            apiRequest("/equipos"),
            apiRequest("/mantenimientos"),
            apiRequest("/fallas")
        ]);

    const preventive = mantenimientos.filter(
        x => x.tipo === "Preventivo"
    ).length;

    const corrective = mantenimientos.filter(
        x => x.tipo === "Correctivo"
    ).length;

    const completed = mantenimientos.filter(
        x => x.estado === "Completado"
    ).length;

    const resolved = fallas.filter(
        x => x.estado === "Resuelta"
    ).length;

    const totalM = mantenimientos.length;
    const totalF = fallas.length;

    document.getElementById("pageContent").innerHTML = `
        ${pageHeading(
            "Reportes e indicadores",
            "Información consolidada para apoyar decisiones.",
            `<button class="btn btn-primary"
                     onclick="window.print()">
                Imprimir reporte
             </button>`
        )}

        <div class="notice">
            Los indicadores se calculan a partir de los registros
            guardados. La disponibilidad representa el porcentaje
            de equipos con estado «Operativo», no un cálculo
            histórico de disponibilidad mecánica.
        </div>

        <section class="stats-grid">
            ${statCard("Equipos",equipos.length,"⚙","Inventario total")}
            ${statCard("Disponibilidad registrada",
                summary.disponibilidad+"%","✓",
                "Según estado de equipos")}
            ${statCard("Mantenimientos",totalM,"▣",
                "Intervenciones registradas")}
            ${statCard("Fallas",totalF,"⚠",
                "Incidencias registradas")}
        </section>

        <div class="report-grid">
            <section class="panel">
                <div class="panel-title">
                    <h3>Estado de maquinaria</h3>
                </div>
                <div class="bar-chart">
                    ${reportBar("Operativos",
                        summary.operativos,equipos.length)}
                    ${reportBar("En mantenimiento",
                        summary.en_mantenimiento,equipos.length)}
                    ${reportBar("Fuera de servicio",
                        summary.fuera_servicio,equipos.length)}
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Tipos de mantenimiento</h3>
                </div>
                <div class="bar-chart">
                    ${reportBar("Preventivos",preventive,totalM)}
                    ${reportBar("Correctivos",corrective,totalM)}
                    ${reportBar("Completados",completed,totalM)}
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Prioridad de fallas</h3>
                </div>
                <div class="bar-chart">
                    ${["Baja","Media","Alta","Crítica"].map(p =>
                        reportBar(p,fallas.filter(
                            x => x.prioridad === p
                        ).length,totalF)
                    ).join("")}
                </div>
            </section>

            <section class="panel">
                <div class="panel-title">
                    <h3>Seguimiento de incidencias</h3>
                </div>
                <div class="bar-chart">
                    ${reportBar("Abiertas",
                        fallas.filter(x =>
                            x.estado === "Abierta").length,totalF)}
                    ${reportBar("En revisión",
                        fallas.filter(x =>
                            x.estado === "En revisión").length,totalF)}
                    ${reportBar("Resueltas",resolved,totalF)}
                </div>
            </section>
        </div>

        <section class="panel" style="margin-top:22px">
            <div class="panel-title">
                <h3>Exportar información</h3>
            </div>

            <p class="muted" style="margin-bottom:18px">
                Descarga los registros en formato CSV para
                analizarlos en Excel o adjuntarlos a un informe.
            </p>

            <div class="page-actions">
                <a class="btn btn-outline"
                   href="/api/exportar/equipos">
                    ↓ Equipos
                </a>
                <a class="btn btn-outline"
                   href="/api/exportar/mantenimientos">
                    ↓ Mantenimientos
                </a>
                <a class="btn btn-outline"
                   href="/api/exportar/fallas">
                    ↓ Fallas
                </a>
            </div>
        </section>
    `;
}

/* INICIALIZACIÓN */

async function initializeApp() {
    if (PAGE === "login") {
        initializeLogin();
        return;
    }

    renderShell();

    try {
        userInfo = await apiRequest("/me");

        document.getElementById("userName").textContent =
            userInfo.nombre;

        document.getElementById("userRole").textContent =
            userInfo.rol;

        if (PAGE === "dashboard") {
            await renderDashboard();
        } else if (PAGE === "reportes") {
            await renderReports();
        } else if (MODULES[PAGE]) {
            await renderModule(PAGE);
        }
    } catch (error) {
        document.getElementById("pageContent").innerHTML = `
            <section class="panel">
                <h3>No se pudo cargar la información</h3>
                <p class="muted">${escapeHTML(error.message)}</p>
                <button class="btn btn-primary"
                        onclick="location.reload()">
                    Reintentar
                </button>
            </section>
        `;
    }
}

document.addEventListener("DOMContentLoaded", initializeApp);
