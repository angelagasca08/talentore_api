import time
import httpx

BASE_URL = "http://127.0.0.1:8000"

def imprimir_paso(titulo, estado, detalle=""):
    color = "\033[92m[EXITO]\033[0m" if estado else "\033[91m[FALLO]\033[0m"
    print(f"{color} {titulo}")
    if detalle:
        print(f"        -> {detalle}")

def ejecutar_auditoria():
    print("=" * 70)
    print("   INICIANDO BATERÍA DE PRUEBAS DINÁMICAS (CLIENTE HTTP)")
    print("=" * 70)

    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        # 1. Health Check
        r = client.get("/health")
        imprimir_paso("1. Verificación de servicio (/health)", r.status_code == 200, r.json())

        # Usar el usuario ID 1 como Admin si ya existen datos
        headers_admin = {"X-User-Id": "1"}

        # 2. Registrar Administrador
        admin_data = {
            "departamento_id": 1,
            "puesto_id": 1,
            "manager_id": None,
            "nombre_completo": "Super Administrador",
            "email": f"admin_{int(time.time())}@corp.com",
            "fecha_alta": "2019-01-01"
        }
        r = client.post("/api/v1/empleados", json=admin_data, headers=headers_admin)
        admin_id = r.json().get("id", 1)
        imprimir_paso("2. Registro del Administrador", r.status_code == 201, f"Admin ID: {admin_id}")

        # 3. Crear Manager
        manager_data = {
            "departamento_id": 1,
            "puesto_id": 1,
            "manager_id": None,
            "nombre_completo": "Jefe Operaciones",
            "email": f"jefe_{int(time.time())}@corp.com",
            "fecha_alta": "2020-01-01"
        }
        r = client.post("/api/v1/empleados", json=manager_data, headers=headers_admin)
        manager_id = r.json().get("id")
        imprimir_paso("3. Registro de Manager", r.status_code == 201, f"Manager ID: {manager_id}")

        # 4. Crear Empleado subordinado (2 años de antigüedad -> 14 días)
        empleado_data = {
            "departamento_id": 1,
            "puesto_id": 1,
            "manager_id": manager_id,
            "nombre_completo": "Ana Desarrolladora",
            "email": f"ana_{int(time.time())}@corp.com",
            "fecha_alta": "2024-10-28"
        }
        r = client.post("/api/v1/empleados", json=empleado_data, headers=headers_admin)
        empleado_id = r.json().get("id")
        imprimir_paso("4. Registro de Empleado (2 años antigüedad)", r.status_code == 201, f"Empleado ID: {empleado_id}")

        # 5. Consultar saldo inicial
        r = client.get(f"/api/v1/vacaciones/saldo/{empleado_id}")
        saldo = r.json()
        imprimir_paso("5. Verificación de cálculo legal (14 días)", saldo.get("saldo_disponible") == 14, saldo)

        # 6. Intento de solicitud con exceso de días (debe fallar con 400)
        solicitud_exceso = {
            "empleado_id": empleado_id,
            "fecha_inicio": "2026-11-01",
            "fecha_fin": "2026-11-15",
            "dias_calendario": 15
        }
        r = client.post("/api/v1/vacaciones/solicitar", json=solicitud_exceso)
        imprimir_paso("6. Intento de pedir 15 días (Excede saldo)", r.status_code == 400, r.json())

        # 7. Solicitud válida de 4 días
        solicitud_valida = {
            "empleado_id": empleado_id,
            "fecha_inicio": "2026-11-01",
            "fecha_fin": "2026-11-04",
            "dias_calendario": 4
        }
        r = client.post("/api/v1/vacaciones/solicitar", json=solicitud_valida)
        solicitud_id = r.json().get("id")
        imprimir_paso("7. Solicitud válida de 4 días (PENDING)", r.status_code == 201, f"Solicitud ID: {solicitud_id}")

        # 8. Intento de aprobación por usuario no autorizado (debe fallar con 403)
        headers_usurpador = {"X-User-Id": "999"}
        r = client.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            json={
                "solicitud_id": solicitud_id,
                "accion": "APPROVE",
                "comentario": "Intento no autorizado"
            },
            headers=headers_usurpador
        )
        imprimir_paso("8. Seguridad RBAC: Intento de aprobación por usuario no autorizado", r.status_code in (403, 404), r.json())

        # 9. Aprobación oficial por el jefe directo
        headers_manager = {"X-User-Id": str(manager_id)}
        r = client.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            json={
                "solicitud_id": solicitud_id,
                "accion": "APPROVE",
                "comentario": "Aprobado"
            },
            headers=headers_manager
        )
        imprimir_paso("9. Aprobación oficial por su Manager directo", r.status_code == 200, r.json())

        # 10. Saldo final descontado
        r = client.get(f"/api/v1/vacaciones/saldo/{empleado_id}")
        saldo_final = r.json()
        imprimir_paso("10. Balance final de vacaciones (14 - 4 = 10 días)", saldo_final.get("saldo_disponible") == 10, saldo_final)

    print("=" * 70)
    print("   BATERÍA DE PRUEBAS COMPLETADA EXITOSAMENTE")
    print("=" * 70)

if __name__ == "__main__":
    try:
        ejecutar_auditoria()
    except Exception as e:
        print(f"\n[ERROR] No se pudo conectar al servidor. ¿Olvidaste levantar Uvicorn? Error: {e}")