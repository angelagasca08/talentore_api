from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./talentcore.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class EstadoSolicitud(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

class Departamento(Base):
    __tablename__ = "departamentos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)

class Puesto(Base):
    __tablename__ = "puestos"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)

class Empleado(Base):
    __tablename__ = "empleados"
    __table_args__ = (
        CheckConstraint("estado IN ('ACTIVO', 'BAJA')", name="ck_empleados_estado"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    departamento_id = Column(Integer, ForeignKey("departamentos.id"), nullable=False)
    puesto_id = Column(Integer, ForeignKey("puestos.id"), nullable=False)
    manager_id = Column(Integer, ForeignKey("empleados.id", ondelete="SET NULL"), nullable=True)
    nombre_completo = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    fecha_alta = Column(Date, nullable=False)
    estado = Column(String(10), nullable=False, default="ACTIVO")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    manager = relationship("Empleado", remote_side=[id], backref="subordinates")
    solicitudes = relationship(
        "SolicitudVacaciones",
        foreign_keys="[SolicitudVacaciones.empleado_id]",
        back_populates="empleado")


class SolicitudVacaciones(Base):
    __tablename__ = "solicitudes_vacaciones"
    __table_args__ = (
        CheckConstraint("estado IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')", name="ck_solicitudes_estado"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="ck_solicitudes_fechas"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"))
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    dias_habiles_solicitados = Column(Integer, nullable=False)
    estado = Column(String(10), nullable=False, default="PENDING")
    aprobado_por = Column(Integer, ForeignKey("empleados.id"), nullable=True)
    fecha_aprobacion = Column(DateTime, nullable=True)
    comentario_aprobacion = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    empleado = relationship("Empleado", foreign_keys=[empleado_id], back_populates="solicitudes")
    aprobador = relationship("Empleado", foreign_keys=[aprobado_por])


class EmpleadoCreate(BaseModel):
    departamento_id: int
    puesto_id: int
    manager_id: Optional[int] = None
    nombre_completo: str = Field(..., min_length=5, max_length=150)
    email: EmailStr
    fecha_alta: date


class EmpleadoResponse(BaseModel):
    id: int
    departamento_id: int
    puesto_id: int
    manager_id: Optional[int]
    nombre_completo: str
    email: EmailStr
    fecha_alta: date
    estado: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SaldoResponse(BaseModel):
    empleado_id: int
    dias_generados: int
    dias_consumidos_aprobados: int
    dias_congelados_pending: int
    saldo_disponible: int
    antiguedad_anios: int


class SolicitudCreate(BaseModel):
    empleado_id: int
    fecha_inicio: date
    fecha_fin: date

    @property
    def dias_calendario(self) -> int:
        return (self.fecha_fin - self.fecha_inicio).days + 1


class RevisionRequest(BaseModel):
    solicitud_id: int
    accion: str = Field(..., pattern="^(APPROVE|REJECT)$")
    comentario: Optional[str] = Field(None, max_length=500)


class SolicitudResponse(BaseModel):
    id: int
    empleado_id: int
    fecha_inicio: date
    fecha_fin: date
    dias_habiles_solicitados: int
    estado: EstadoSolicitud
    aprobado_por: Optional[int]
    fecha_aprobacion: Optional[datetime]
    comentario_aprobacion: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
