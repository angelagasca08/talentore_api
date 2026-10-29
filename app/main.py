from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import (
    Base,
    Empleado,
    EmpleadoCreate,
    EmpleadoResponse,
    RevisionRequest,
    SaldoResponse,
    SolicitudCreate,
    SolicitudResponse,
    SolicitudVacaciones,
    engine,
    get_db,
)

app = FastAPI(title="TalentCore API")

# Crear tablas en SQLite
Base.metadata.create_all(bind=engine)


def calcular_saldo(emp: Empleado, db: Session) -> tuple[int, int, int]:
    fecha = emp.fecha_alta
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
    anios = (datetime.utcnow().date() - fecha).days // 365
    dias_totales = 12 if anios < 1 else min(12 + 2 * (anios - 1), 20)
    dias_aprobados = (
        db.query(SolicitudVacaciones)
        .filter(
            SolicitudVacaciones.empleado_id == emp.id,
            SolicitudVacaciones.estado == "APPROVED",
        )
        .count()
    )
    saldo_disponible = dias_totales - dias_aprobados
    return dias_totales, dias_aprobados, saldo_disponible


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/empleados", status_code=201, response_model=EmpleadoResponse)
def crear_empleado(
    payload: EmpleadoCreate,
    x_user_id: Optional[int] = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    total_empleados = db.query(Empleado).count()

    # Validación de permisos RBAC
    if total_empleados > 0:
        if x_user_id is None:
            raise HTTPException(status_code=403, detail="Missing X-User-Id header")
        admin = db.query(Empleado).filter(Empleado.id == x_user_id).first()
        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found")
        
        es_admin = (admin.id == 1) or (getattr(admin, "rol", None) == "ADMIN_RRHH")
        if not es_admin:
            raise HTTPException(status_code=403, detail="Only ADMIN_RRHH can create employees")

    # Inserción de departamentos y puestos por defecto
    try:
        db.execute(text("INSERT OR IGNORE INTO departamentos (id, nombre) VALUES (:id, 'General')"), {"id": payload.departamento_id})
        db.execute(text("INSERT OR IGNORE INTO puestos (id, nombre) VALUES (:id, 'General')"), {"id": payload.puesto_id})
        db.commit()
    except Exception:
        db.rollback()

    # Determinar rol asignado
    rol_solicitado = getattr(payload, "rol", None)
    if total_empleados == 0:
        rol_final = "ADMIN_RRHH"
    elif rol_solicitado:
        rol_final = rol_solicitado
    else:
        rol_final = "MANAGER" if payload.manager_id is None else "EMPLEADO"

    emp = Empleado(
        departamento_id=payload.departamento_id,
        puesto_id=payload.puesto_id,
        manager_id=payload.manager_id,
        nombre_completo=payload.nombre_completo,
        email=payload.email,
        fecha_alta=payload.fecha_alta,
    )
    
    if hasattr(emp, "rol"):
        setattr(emp, "rol", rol_final)

    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@app.get("/api/v1/vacaciones/saldo/{empleado_id}", response_model=SaldoResponse)
def obtener_saldo(empleado_id: int, db: Session = Depends(get_db)):
    emp = db.query(Empleado).filter(Empleado.id == empleado_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    dias_totales, dias_aprobados, saldo_disponible = calcular_saldo(emp, db)
    fecha = emp.fecha_alta
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
    anios = (datetime.utcnow().date() - fecha).days // 365

    return SaldoResponse(
        empleado_id=empleado_id,
        dias_generados=dias_totales,
        dias_consumidos_aprobados=dias_aprobados,
        dias_congelados_pending=0,
        saldo_disponible=saldo_disponible,
        antiguedad_anios=anios,
    )


@app.post("/api/v1/vacaciones/solicitar", status_code=201, response_model=SolicitudResponse)
def solicitar_vacaciones(payload: SolicitudCreate, db: Session = Depends(get_db)):
    emp = db.query(Empleado).filter(Empleado.id == payload.empleado_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    _, _, saldo_disponible = calcular_saldo(emp, db)
    dias_solicitados = payload.dias_calendario
    if dias_solicitados > saldo_disponible:
        raise HTTPException(status_code=400, detail="Insufficient vacation balance")

    solicitud = SolicitudVacaciones(
        empleado_id=payload.empleado_id,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        dias_habiles_solicitados=dias_solicitados,
        estado="PENDING",
    )
    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)
    return solicitud


@app.post("/api/v1/vacaciones/{solicitud_id}/revisar", response_model=SolicitudResponse)
def revisar_solicitud(
    solicitud_id: int,
    payload: RevisionRequest,
    x_user_id: int = Header(..., alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    solicitud = db.query(SolicitudVacaciones).filter(SolicitudVacaciones.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Request not found")

    manager = db.query(Empleado).filter(Empleado.id == x_user_id).first()
    if not manager:
        raise HTTPException(status_code=404, detail="Manager not found")

    empleado = db.query(Empleado).filter(Empleado.id == solicitud.empleado_id).first()
    if empleado.manager_id != x_user_id:
        raise HTTPException(status_code=403, detail="Unauthorized: Not the direct manager")

    if solicitud.estado != "PENDING":
        raise HTTPException(status_code=400, detail="Request already processed")

    if payload.accion == "APPROVE":
        solicitud.estado = "APPROVED"
    elif payload.accion == "REJECT":
        solicitud.estado = "REJECTED"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    solicitud.aprobado_por = x_user_id
    solicitud.fecha_aprobacion = datetime.utcnow()
    solicitud.comentario_aprobacion = payload.comentario
    db.commit()
    db.refresh(solicitud)
    return solicitud