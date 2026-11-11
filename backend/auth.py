"""Autenticación del administrador.

- La contraseña se guarda como hash scrypt en ``backend/admin.json`` (nunca en texto plano).
  Se crea o cambia con:  env\\Scripts\\python.exe -m backend.create_admin
- Al iniciar sesión se entrega un token firmado con HMAC-SHA256 que expira
  (por defecto 8 horas). La clave de firma se toma de ``AUTH_SECRET`` o se genera
  una vez y se guarda en ``backend/.auth_secret``.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Header, HTTPException, Query, status

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent)))
ADMIN_FILE = DATA_DIR / "admin.json"
SECRET_FILE = DATA_DIR / ".auth_secret"
DETECTOR_KEY_FILE = DATA_DIR / ".detector_key"
TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL", str(8 * 60 * 60)))

_SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}

# Bloqueo simple contra fuerza bruta: tras MAX_FAILURES intentos fallidos
# desde una misma IP, se rechazan los intentos durante LOCKOUT_SECONDS.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
_failed_attempts: dict[str, list[float]] = {}


# ---------- Contraseñas ----------

def hash_password(password: str) -> dict:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT_PARAMS)
    return {
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
        **_SCRYPT_PARAMS,
    }


def _verify_password(password: str, stored: dict) -> bool:
    try:
        salt = base64.b64decode(stored["salt"])
        expected = base64.b64decode(stored["hash"])
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=stored["n"], r=stored["r"], p=stored["p"],
        )
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def load_admin() -> dict | None:
    if not ADMIN_FILE.exists():
        return None
    try:
        return json.loads(ADMIN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_admin(username: str, password: str) -> None:
    data = {"username": username, "password": hash_password(password)}
    ADMIN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------- Tokens ----------

def _get_secret() -> bytes:
    env_secret = os.getenv("AUTH_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding="utf-8")
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(username: str) -> tuple[str, int]:
    expires_at = int(time.time()) + TOKEN_TTL_SECONDS
    payload = _b64(json.dumps({"sub": username, "exp": expires_at}).encode("utf-8"))
    signature = _b64(hmac.new(_get_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}", expires_at


def verify_token(token: str | None) -> str | None:
    """Devuelve el usuario si el token es válido y no expiró; si no, None."""
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    expected = _b64(hmac.new(_get_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("exp", 0) < time.time():
        return None
    admin = load_admin()
    if not admin or data.get("sub") != admin.get("username"):
        return None
    return data["sub"]


# ---------- Login ----------

def _check_lockout(client_ip: str) -> None:
    now = time.time()
    recent = [t for t in _failed_attempts.get(client_ip, []) if now - t < LOCKOUT_SECONDS]
    _failed_attempts[client_ip] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Espera un minuto e inténtalo de nuevo.",
        )


def authenticate(username: str, password: str, client_ip: str) -> str:
    """Valida las credenciales y devuelve el nombre de usuario, o lanza HTTPException."""
    _check_lockout(client_ip)
    admin = load_admin()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El inicio de sesión no está disponible en este momento.",
        )
    username_ok = hmac.compare_digest(username.encode("utf-8"), admin["username"].encode("utf-8"))
    password_ok = _verify_password(password, admin.get("password", {}))
    if not (username_ok and password_ok):
        _failed_attempts.setdefault(client_ip, []).append(time.time())
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario o contraseña incorrectos.")
    _failed_attempts.pop(client_ip, None)
    return admin["username"]


# ---------- Clave del detector ----------

def get_detector_key() -> str:
    """Clave compartida con el detector. Se toma de DETECTOR_API_KEY o, si no
    existe, se genera una vez y se guarda en backend/.detector_key, desde donde
    la leen los scripts del detector que corren en el mismo servidor."""
    env_key = os.getenv("DETECTOR_API_KEY")
    if env_key:
        return env_key.strip()
    if not DETECTOR_KEY_FILE.exists():
        DETECTOR_KEY_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        try:
            os.chmod(DETECTOR_KEY_FILE, 0o600)
        except OSError:
            pass
    return DETECTOR_KEY_FILE.read_text(encoding="utf-8").strip()


def _is_valid_detector_key(key: str | None) -> bool:
    return bool(key) and hmac.compare_digest(key.encode("utf-8"), get_detector_key().encode("utf-8"))


# ---------- Dependencias de FastAPI ----------

def require_detector(x_detector_key: str | None = Header(default=None)) -> None:
    """Protege los endpoints que solo debe usar el detector (cabecera X-Detector-Key)."""
    if not _is_valid_detector_key(x_detector_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clave de detector inválida.")


def require_admin_or_detector(
    authorization: str | None = Header(default=None),
    x_detector_key: str | None = Header(default=None),
) -> None:
    """Acepta la sesión del administrador o la clave del detector."""
    if _is_valid_detector_key(x_detector_key):
        return
    if authorization and authorization.lower().startswith("bearer ") and verify_token(authorization[7:].strip()):
        return
    raise _unauthorized()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Se requiere iniciar sesión como administrador.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """Protege un endpoint: exige 'Authorization: Bearer <token>'."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = verify_token(token)
    if not user:
        raise _unauthorized()
    return user


def require_admin_query(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    """Igual que require_admin, pero acepta también ?token=... (necesario para
    <img src> del stream MJPEG, que no puede enviar cabeceras)."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = verify_token(token)
    if not user:
        raise _unauthorized()
    return user
