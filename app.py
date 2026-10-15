
import os
import csv
import io
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    session, redirect, url_for, Response
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "maqcontrol.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "maqcontrol-desarrollo-cambiar-en-produccion"
)

# Evita que JavaScript acceda a la cookie de sesión.
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Protección de cookies.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# En Render se activa mediante COOKIE_SECURE=true.
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "false").lower() == "true"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Cambiar a True solamente cuando se publique con HTTPS.
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "false").lower() == "true"
)

PAGES = {
    "dashboard": "dashboard.html",
    "equipos": "equipos.html",
    "mantenimientos": "mantenimientos.html",
    "fallas": "fallas.html",
    "reportes": "reportes.html"
}

TABLES = {
    "equipos": {
        "fields": [
            "codigo", "nombre", "marca", "modelo", "serie",
            "horometro", "ubicacion", "estado"
        ],
        "required": ["codigo", "nombre"],
        "numbers": ["horometro"]
    },
    "mantenimientos": {
        "fields": [
            "equipo_id", "tipo", "descripcion", "fecha",
            "horometro_objetivo", "responsable", "estado"
        ],
        "required": ["equipo_id", "tipo", "descripcion", "fecha"],
        "numbers": ["equipo_id", "horometro_objetivo"]
    },
    "fallas": {
        "fields": [
            "equipo_id", "descripcion", "prioridad", "fecha",
            "responsable", "estado", "observaciones"
        ],
        "required": ["equipo_id", "descripcion", "fecha"],
        "numbers": ["equipo_id"]
    }
}

ESTADOS = {
    "equipos": ["Operativo", "En mantenimiento", "Fuera de servicio"],
    "mantenimientos": ["Pendiente", "En proceso", "Completado"],
    "fallas": ["Abierta", "En revisión", "Resuelta"]
}


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def rows_to_dict(rows):
    return [dict(row) for row in rows]


def initialize_database():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'Administrador'
        );

        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            marca TEXT DEFAULT '',
            modelo TEXT DEFAULT '',
            serie TEXT DEFAULT '',
            horometro REAL NOT NULL DEFAULT 0,
            ubicacion TEXT DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'Operativo',
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mantenimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            fecha TEXT NOT NULL,
            horometro_objetivo REAL DEFAULT NULL,
            responsable TEXT DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'Pendiente',
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id)
        );

        CREATE TABLE IF NOT EXISTS fallas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            prioridad TEXT NOT NULL DEFAULT 'Media',
            fecha TEXT NOT NULL,
            responsable TEXT DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'Abierta',
            observaciones TEXT DEFAULT '',
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipo_id) REFERENCES equipos(id)
        );
        """)

        # Cuenta únicamente para pruebas académicas.
        user_count = db.execute(
            "SELECT COUNT(*) FROM usuarios"
        ).fetchone()[0]

        if user_count == 0:
            db.execute("""
                INSERT INTO usuarios
                (nombre, usuario, password_hash, rol)
                VALUES (?, ?, ?, ?)
            """, (
                "Administrador MAQCONTROL",
                "admin",
                generate_password_hash("Admin12345!"),
                "Administrador"
            ))

        equipment_count = db.execute(
            "SELECT COUNT(*) FROM equipos"
        ).fetchone()[0]

        if equipment_count == 0:
            demo_equipment = [
                ("EXC-001", "Excavadora hidráulica", "Caterpillar",
                 "320", "DEMO-EX001", 2450, "Zona de excavación", "Operativo"),
                ("CAR-002", "Cargador frontal", "Komatsu",
                 "WA380", "DEMO-CA002", 3180, "Patio principal", "Operativo"),
                ("RET-003", "Retroexcavadora", "JCB",
                 "3CX", "DEMO-RE003", 1890, "Taller", "En mantenimiento"),
                ("VOL-004", "Volquete", "Volvo",
                 "FMX", "DEMO-VO004", 4210, "Zona de carga", "Operativo"),
                ("MOT-005", "Motoniveladora", "Caterpillar",
                 "140K", "DEMO-MO005", 2760, "Taller", "Fuera de servicio")
            ]

            db.executemany("""
                INSERT INTO equipos
                (codigo, nombre, marca, modelo, serie,
                 horometro, ubicacion, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, demo_equipment)

            today = date.today()

            db.executemany("""
                INSERT INTO mantenimientos
                (equipo_id, tipo, descripcion, fecha,
                 horometro_objetivo, responsable, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (1, "Preventivo", "Cambio de aceite y filtros",
                 str(today + timedelta(days=5)), 2500,
                 "Técnico de mantenimiento", "Pendiente"),
                (2, "Preventivo", "Inspección general",
                 str(today + timedelta(days=12)), 3250,
                 "Supervisor de taller", "Pendiente"),
                (3, "Correctivo", "Revisión del sistema hidráulico",
                 str(today), None,
                 "Técnico hidráulico", "En proceso")
            ])

            db.executemany("""
                INSERT INTO fallas
                (equipo_id, descripcion, prioridad, fecha,
                 responsable, estado, observaciones)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (3, "Pérdida de presión hidráulica", "Alta",
                 str(today), "Técnico hidráulico",
                 "En revisión", "Inspección pendiente"),
                (5, "Dificultad en el arranque", "Crítica",
                 str(today), "Técnico eléctrico",
                 "Abierta", "Equipo detenido")
            ])


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({
                    "error": "Sesión no iniciada"
                }), 401
            return redirect(url_for("login"))
        return function(*args, **kwargs)
    return wrapper


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/")
def home():
    return redirect(
        url_for("dashboard_home")
        if session.get("user_id")
        else url_for("login")
    )


@app.route("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard_home"))
    return render_template("login.html")


@app.route("/<page>")
@login_required
def dashboard(page=None):
    if page not in PAGES:
        return redirect(url_for("dashboard_home"))

    return render_template(PAGES[page])


# Ruta adicional para /dashboard.
@app.route("/dashboard")
@login_required
def dashboard_home():
    return render_template("dashboard.html")


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("usuario", "")).strip()
    password = str(data.get("password", ""))

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM usuarios WHERE usuario = ?",
            (username,)
        ).fetchone()

    if not user or not check_password_hash(
        user["password_hash"], password
    ):
        return jsonify({
            "error": "Usuario o contraseña incorrectos"
        }), 401

    session.clear()
    session["user_id"] = user["id"]
    session["nombre"] = user["nombre"]
    session["rol"] = user["rol"]

    return jsonify({
        "message": "Bienvenido a MAQCONTROL",
        "redirect": "/dashboard"
    })


@app.post("/api/logout")
@login_required
def api_logout():
    session.clear()
    return jsonify({"message": "Sesión cerrada"})


@app.get("/api/me")
@login_required
def api_me():
    return jsonify({
        "nombre": session["nombre"],
        "rol": session["rol"]
    })


@app.get("/api/<table>")
@login_required
def list_records(table):
    if table not in TABLES:
        return jsonify({"error": "Módulo no encontrado"}), 404

    with get_db() as db:
        if table == "equipos":
            rows = db.execute(
                "SELECT * FROM equipos ORDER BY id DESC"
            ).fetchall()
        else:
            rows = db.execute(f"""
                SELECT t.*, e.codigo AS equipo_codigo,
                       e.nombre AS equipo_nombre
                FROM {table} t
                JOIN equipos e ON e.id = t.equipo_id
                ORDER BY t.id DESC
            """).fetchall()

    return jsonify(rows_to_dict(rows))


def validate_payload(table, data):
    config = TABLES[table]
    cleaned = {}

    for field in config["fields"]:
        value = data.get(field, None)

        if field in config["numbers"]:
            if value is None or value == "":
                value = None if field == "horometro_objetivo" else 0
            try:
                value = float(value) if value is not None else None
            except (ValueError, TypeError):
                raise ValueError(f"Valor numérico inválido: {field}")
            if value is not None and value < 0:
                raise ValueError(f"{field} no puede ser negativo")
            if field == "equipo_id":
                if not value or not value.is_integer():
                    raise ValueError("Selecciona un equipo válido")
                value = int(value)
        else:
            value = str(value or "").strip()
            if len(value) > 1000:
                raise ValueError(f"Texto demasiado largo: {field}")

        cleaned[field] = value

    for field in config["required"]:
        if cleaned[field] is None or cleaned[field] == "":
            raise ValueError(f"El campo {field} es obligatorio")

    if table == "equipos":
        cleaned["estado"] = cleaned["estado"] or "Operativo"

    if table == "mantenimientos":
        cleaned["estado"] = cleaned["estado"] or "Pendiente"

    if table == "fallas":
        cleaned["estado"] = cleaned["estado"] or "Abierta"
        cleaned["prioridad"] = cleaned["prioridad"] or "Media"

    if cleaned["estado"] not in ESTADOS[table]:
        raise ValueError("Estado no permitido")

    if table == "mantenimientos":
        if cleaned["tipo"] not in ["Preventivo", "Correctivo"]:
            raise ValueError("Tipo de mantenimiento inválido")

    if table == "fallas":
        if cleaned["prioridad"] not in [
            "Baja", "Media", "Alta", "Crítica"
        ]:
            raise ValueError("Prioridad inválida")

    if table in ("fallas", "mantenimientos"):
        try:
            date.fromisoformat(cleaned["fecha"])
        except ValueError:
            raise ValueError("Fecha inválida")

    return cleaned


@app.post("/api/<table>")
@login_required
def create_record(table):
    if table not in TABLES:
        return jsonify({"error": "Módulo no encontrado"}), 404

    data = request.get_json(silent=True) or {}

    try:
        cleaned = validate_payload(table, data)
        fields = list(cleaned.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join(["?"] * len(fields))

        with get_db() as db:
            cursor = db.execute(
                f"INSERT INTO {table} ({columns}) "
                f"VALUES ({placeholders})",
                [cleaned[field] for field in fields]
            )
            record_id = cursor.lastrowid

        return jsonify({
            "message": "Registro guardado correctamente",
            "id": record_id
        }), 201

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "Código duplicado o equipo no válido"
        }), 409


@app.put("/api/<table>/<int:record_id>")
@login_required
def update_record(table, record_id):
    if table not in TABLES:
        return jsonify({"error": "Módulo no encontrado"}), 404

    data = request.get_json(silent=True) or {}

    try:
        cleaned = validate_payload(table, data)
        fields = list(cleaned.keys())
        assignments = ", ".join(f"{field} = ?" for field in fields)

        with get_db() as db:
            cursor = db.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                [cleaned[field] for field in fields] + [record_id]
            )

        if cursor.rowcount == 0:
            return jsonify({"error": "Registro no encontrado"}), 404

        return jsonify({"message": "Registro actualizado"})

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except sqlite3.IntegrityError:
        return jsonify({
            "error": "Código duplicado o referencia inválida"
        }), 409


@app.delete("/api/<table>/<int:record_id>")
@login_required
def delete_record(table, record_id):
    if table not in TABLES:
        return jsonify({"error": "Módulo no encontrado"}), 404

    try:
        with get_db() as db:
            cursor = db.execute(
                f"DELETE FROM {table} WHERE id = ?",
                (record_id,)
            )

        if cursor.rowcount == 0:
            return jsonify({"error": "Registro no encontrado"}), 404

        return jsonify({"message": "Registro eliminado"})

    except sqlite3.IntegrityError:
        return jsonify({
            "error": "Este equipo tiene registros asociados. "
                     "No puede eliminarse sin revisar su historial."
        }), 409


@app.get("/api/resumen")
@login_required
def summary():
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM equipos"
        ).fetchone()[0]

        operativos = db.execute("""
            SELECT COUNT(*) FROM equipos
            WHERE estado = 'Operativo'
        """).fetchone()[0]

        mantenimiento = db.execute("""
            SELECT COUNT(*) FROM equipos
            WHERE estado = 'En mantenimiento'
        """).fetchone()[0]

        fuera_servicio = db.execute("""
            SELECT COUNT(*) FROM equipos
            WHERE estado = 'Fuera de servicio'
        """).fetchone()[0]

        pendientes = db.execute("""
            SELECT COUNT(*) FROM mantenimientos
            WHERE estado != 'Completado'
        """).fetchone()[0]

        fallas_activas = db.execute("""
            SELECT COUNT(*) FROM fallas
            WHERE estado != 'Resuelta'
        """).fetchone()[0]

        proximos = rows_to_dict(db.execute("""
            SELECT m.*, e.codigo AS equipo_codigo,
                   e.nombre AS equipo_nombre
            FROM mantenimientos m
            JOIN equipos e ON e.id = m.equipo_id
            WHERE m.estado != 'Completado'
            ORDER BY m.fecha ASC
            LIMIT 6
        """).fetchall())

        ultimas_fallas = rows_to_dict(db.execute("""
            SELECT f.*, e.codigo AS equipo_codigo,
                   e.nombre AS equipo_nombre
            FROM fallas f
            JOIN equipos e ON e.id = f.equipo_id
            ORDER BY f.id DESC
            LIMIT 5
        """).fetchall())

    return jsonify({
        "total": total,
        "operativos": operativos,
        "en_mantenimiento": mantenimiento,
        "fuera_servicio": fuera_servicio,
        "mantenimientos_pendientes": pendientes,
        "fallas_activas": fallas_activas,
        "disponibilidad": round(
            operativos * 100 / total, 1
        ) if total else 0,
        "proximos": proximos,
        "ultimas_fallas": ultimas_fallas
    })


@app.get("/api/exportar/<table>")
@login_required
def export_csv(table):
    if table not in TABLES:
        return jsonify({"error": "Módulo no encontrado"}), 404

    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM {table} ORDER BY id DESC"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow(["Sin registros"])

    content = "\ufeff" + output.getvalue()

    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f"attachment; filename=maqcontrol_{table}.csv"
        }
    )


# ==========================================
# INICIALIZACIÓN DE MAQCONTROL
# Compatible con ejecución local y Render
# ==========================================

# Crea las tablas y los registros iniciales
# cuando Flask es cargado por Gunicorn.
initialize_database()

# Ejecución local desde Visual Studio Code.
if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
