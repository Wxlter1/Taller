"""Crea o cambia la cuenta de administrador de SmartParking.

Uso (desde la carpeta Taller):
    env\\Scripts\\python.exe -m backend.create_admin
"""

import getpass
import sys

from .auth import ADMIN_FILE, load_admin, save_admin

MIN_PASSWORD_LENGTH = 8


def main() -> int:
    current = load_admin()
    if current:
        print(f"Ya existe un administrador: '{current['username']}'. Se reemplazará.")

    username = input("Usuario administrador: ").strip()
    if not username:
        print("El usuario no puede estar vacío.")
        return 1

    password = getpass.getpass("Contraseña: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
        return 1
    if password != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1

    save_admin(username, password)
    print(f"Administrador '{username}' guardado en {ADMIN_FILE}.")
    print("Las sesiones abiertas con otra cuenta dejarán de ser válidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
