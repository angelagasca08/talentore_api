import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.models import Base, engine, Empleado, SessionLocal


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _create_employee(client, payload, headers=None):
    if headers is None:
        headers = {}
    return client.post("/api/v1/empleados", json=payload, headers=headers)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ac01_solicitud_valida_y_calculo_saldo(client):
    # 1. Crear ADMIN_RRHH (id=1)
    admin_payload = {
        "departamento_id": 1,
        "puesto_id": 1,
        "manager_id": None,
        "nombre_completo": "Admin RRHH",
        "email": "admin@talentcore.com",
        "fecha_alta": "2020-01-01"
    }
    resp = _create_employee(client, admin_payload)
    assert resp.status_code == 201
    admin_id = resp.json()["id"]
    assert admin_id == 1

    # Inyectar rol ADMIN_RRHH directamente en la BD para pasar la validación de permisos
    db = SessionLocal()
    admin = db.query(Empleado).filter(Empleado.id == admin_id).first()
    admin.rol = "ADMIN_RRHH"
    db.commit()
    db.close()

    # 2. Crear MANAGER (id=2)
    manager_payload = {
        "departamento_id": 1,
        "puesto_id": 2,
        "manager_id": admin_id,
        "nombre_completo": "Manager Uno",
        "email": "manager@talentcore.com",
        "fecha_alta": "2019-01-01"
    }
    resp = _create_employee(client, manager_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    manager_id = resp.json()["id"]
    assert manager_id == 2

    # Inyectar rol MANAGER
    db = SessionLocal()
    manager = db.query(Empleado).filter(Empleado.id == manager_id).first()
    manager.rol = "MANAGER"
    db.commit()
    db.close()

    # 3. Crear EMPLEADO (id=3) con 3 años de antigüedad
    # Fecha alta: hace 3 años completos
    fecha_alta_empleado = (date.today() - timedelta(days=365 * 3)).isoformat()
    empleado_payload = {
        "departamento_id": 1,
        "puesto_id": 3,
        "manager_id": manager_id,
        "nombre_completo": "Empleado Tres",
        "email": "empleado@talentcore.com",
        "fecha_alta": fecha_alta_empleado
    }
    resp = _create_employee(client, empleado_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    empleado_id = resp.json()["id"]
    assert empleado_id == 3

    # 4. Verificar saldo inicial
    # Fórmula: MIN(12 + 2*(3-1), 20) = MIN(16, 20) = 16
    resp = client.get(f"/api/v1/vacaciones/saldo/{empleado_id}")
    assert resp.status_code == 200
    saldo_data = resp.json()
    assert saldo_data["dias_generados"] == 16
    assert saldo_data["saldo_disponible"] == 16

    # 5. Solicitar 5 días de vacaciones
    # Rango de 5 días calendario
    fecha_inicio = (date.today() + timedelta(days=10)).isoformat()
    fecha_fin = (date.today() + timedelta(days=14)).isoformat()
    
    solicitud_payload = {
        "empleado_id": empleado_id,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin
    }
    resp = client.post("/api/v1/vacaciones/solicitar", json=solicitud_payload)
    assert resp.status_code == 201
    solicitud_data = resp.json()
    assert solicitud_data["estado"] == "PENDING"
    solicitud_id = solicitud_data["id"]
    assert solicitud_id == 1

    # 6. Manager aprueba la solicitud
    revision_payload = {
        "accion": "APPROVE",
        "comentario": "Aprobado"
    }
    resp = client.post(
        f"/api/v1/vacaciones/{solicitud_id}/revisar",
        json=revision_payload,
        headers={"X-User-Id": str(manager_id)}
    )
    assert resp.status_code == 200
    aprobada_data = resp.json()
    assert aprobada_data["estado"] == "APPROVED"

    # 7. Verificar nuevo saldo disponible
    # Saldo anterior: 16. Días solicitados (calendario): 5.
    # Nota: El código actual en main.py usa `dias_calendario` para la validación y almacenamiento.
    # Por lo tanto, el saldo se reduce en 5.
    # Nuevo saldo: 16 - 5 = 11
    resp = client.get(f"/api/v1/vacaciones/saldo/{empleado_id}")
    assert resp.status_code == 200
    nuevo_saldo = resp.json()
    assert nuevo_saldo["saldo_disponible"] == 11


def test_ac02_saldo_insuficiente(client):
    # 1. Crear ADMIN_RRHH (id=1)
    admin_payload = {
        "departamento_id": 1,
        "puesto_id": 1,
        "manager_id": None,
        "nombre_completo": "Admin RRHH",
        "email": "admin2@talentcore.com",
        "fecha_alta": "2020-01-01"
    }
    resp = _create_employee(client, admin_payload)
    assert resp.status_code == 201
    admin_id = resp.json()["id"]
    assert admin_id == 1

    db = SessionLocal()
    admin = db.query(Empleado).filter(Empleado.id == admin_id).first()
    admin.rol = "ADMIN_RRHH"
    db.commit()
    db.close()

    # 2. Crear EMPLEADO (id=2) con 1 año de antigüedad
    fecha_alta_empleado = (date.today() - timedelta(days=365 * 1)).isoformat()
    empleado_payload = {
        "departamento_id": 1,
        "puesto_id": 2,
        "manager_id": None,
        "nombre_completo": "Empleado Dos",
        "email": "empleado2@talentcore.com",
        "fecha_alta": fecha_alta_empleado
    }
    resp = _create_employee(client, empleado_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    empleado_id = resp.json()["id"]
    assert empleado_id == 2

    # 3. Intentar solicitar 15 días (Saldo disponible es 12)
    fecha_inicio = (date.today() + timedelta(days=10)).isoformat()
    fecha_fin = (date.today() + timedelta(days=24)).isoformat() # 15 días calendario
    
    solicitud_payload = {
        "empleado_id": empleado_id,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin
    }
    resp = client.post("/api/v1/vacaciones/solicitar", json=solicitud_payload)
    assert resp.status_code == 400
    assert "Insufficient vacation balance" in resp.json()["detail"]


def test_ac03_manager_no_autorizado(client):
    # 1. Crear ADMIN_RRHH (id=1)
    admin_payload = {
        "departamento_id": 1,
        "puesto_id": 1,
        "manager_id": None,
        "nombre_completo": "Admin RRHH",
        "email": "admin3@talentcore.com",
        "fecha_alta": "2020-01-01"
    }
    resp = _create_employee(client, admin_payload)
    assert resp.status_code == 201
    admin_id = resp.json()["id"]
    assert admin_id == 1

    db = SessionLocal()
    admin = db.query(Empleado).filter(Empleado.id == admin_id).first()
    admin.rol = "ADMIN_RRHH"
    db.commit()
    db.close()

    # 2. Crear MANAGER A (id=2)
    manager_a_payload = {
        "departamento_id": 1,
        "puesto_id": 2,
        "manager_id": admin_id,
        "nombre_completo": "Manager A",
        "email": "manager_a@talentcore.com",
        "fecha_alta": "2019-01-01"
    }
    resp = _create_employee(client, manager_a_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    manager_a_id = resp.json()["id"]
    assert manager_a_id == 2

    db = SessionLocal()
    manager_a = db.query(Empleado).filter(Empleado.id == manager_a_id).first()
    manager_a.rol = "MANAGER"
    db.commit()
    db.close()

    # 3. Crear MANAGER B (id=3)
    manager_b_payload = {
        "departamento_id": 1,
        "puesto_id": 3,
        "manager_id": admin_id,
        "nombre_completo": "Manager B",
        "email": "manager_b@talentcore.com",
        "fecha_alta": "2019-01-01"
    }
    resp = _create_employee(client, manager_b_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    manager_b_id = resp.json()["id"]
    assert manager_b_id == 3

    db = SessionLocal()
    manager_b = db.query(Empleado).filter(Empleado.id == manager_b_id).first()
    manager_b.rol = "MANAGER"
    db.commit()
    db.close()

    # 4. Crear EMPLEADO (id=4) con manager_id = Manager A (id=2)
    fecha_alta_empleado = (date.today() - timedelta(days=365 * 1)).isoformat()
    empleado_payload = {
        "departamento_id": 1,
        "puesto_id": 4,
        "manager_id": manager_a_id,
        "nombre_completo": "Empleado Cuatro",
        "email": "empleado4@talentcore.com",
        "fecha_alta": fecha_alta_empleado
    }
    resp = _create_employee(client, empleado_payload, headers={"X-User-Id": str(admin_id)})
    assert resp.status_code == 201
    empleado_id = resp.json()["id"]
    assert empleado_id == 4

    # 5. El empleado solicita 3 días
    fecha_inicio = (date.today() + timedelta(days=10)).isoformat()
    fecha_fin = (date.today() + timedelta(days=12)).isoformat() # 3 días calendario
    
    solicitud_payload = {
        "empleado_id": empleado_id,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin
    }
    resp = client.post("/api/v1/vacaciones/solicitar", json=solicitud_payload)
    assert resp.status_code == 201
    solicitud_id = resp.json()["id"]
    assert solicitud_id == 1

    # 6. MANAGER B (id=3) intenta aprobar
    revision_payload = {
        "accion": "APPROVE",
        "comentario": "Intento no autorizado"
    }
    resp = client.post(
        f"/api/v1/vacaciones/{solicitud_id}/revisar",
        json=revision_payload,
        headers={"X-User-Id": str(manager_b_id)}
    )
    assert resp.status_code == 403
    assert "Unauthorized: Not the direct manager" in resp.json()["detail"]
