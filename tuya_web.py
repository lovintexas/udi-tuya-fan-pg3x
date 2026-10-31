import json
import os
import secrets
import threading
import time
from pathlib import Path

import tinytuya
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
ACCOUNTS_FILE = BASE / "tuya_web_accounts.json"
CONFIG_FILE = BASE / "tinytuya.json"
DEVICES_FILE = BASE / "tuya_devices.json"
INVENTORY_FILE = BASE / "tuya_inventory.json"
IDENTITY_FILE = BASE / "tuya_identity.json"


def plugin_api_path(endpoint):
    if not IDENTITY_FILE.exists():
        raise RuntimeError("Node server identity unavailable")

    identity = json.loads(IDENTITY_FILE.read_text())
    profile = str(identity.get("profileNum", ""))

    if not profile.isdigit():
        raise RuntimeError("Invalid node server profile number")

    return f"/api/plugin/{profile}/{endpoint}"



def read_eisy_customparams():
    import socket
    import http.client

    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect("/tmp/eisyui-listener")

    conn = UnixConnection("localhost", timeout=5)
    try:
        conn.request("GET", plugin_api_path("custom/customparams"))
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"eisy-ui returned HTTP {response.status}")
        return json.loads(body)
    finally:
        conn.close()



def request_eisy_plugin(payload, timeout=30000):
    import socket
    import http.client

    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect("/tmp/eisyui-listener")

    conn = UnixConnection("localhost", timeout=(timeout / 1000) + 5)
    try:
        conn.request(
            "POST",
            plugin_api_path("request"),
            body=json.dumps({"payload": payload, "timeout": timeout}),
            headers={"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        body = response.read()

        if response.status != 200:
            raise RuntimeError(
                f"eisy-ui plugin request returned HTTP {response.status}: "
                f"{body.decode(errors='replace')[:300]}"
            )

        result = json.loads(body)
        if result.get("successful") is not True:
            raise RuntimeError("eisy-ui plugin request was unsuccessful")

        return result.get("data")

    finally:
        conn.close()


def write_eisy_customparams(params):
    import socket
    import http.client

    if not isinstance(params, dict):
        raise ValueError("Custom parameters must be a dictionary")

    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect("/tmp/eisyui-listener")

    conn = UnixConnection("localhost", timeout=5)
    try:
        conn.request(
            "POST",
            plugin_api_path("custom/customparams"),
            body=json.dumps(params),
            headers={"Content-Type": "application/json"}
        )
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"eisy-ui returned HTTP {response.status}")
        result = json.loads(body)
        if result.get("successful") is not True:
            raise RuntimeError("eisy-ui rejected custom parameters")
        return result
    finally:
        conn.close()


from contextlib import asynccontextmanager
import asyncio
import signal


@asynccontextmanager
async def web_lifespan(app):
    original_parent = os.getppid()

    async def monitor_parent():
        # A manually launched editor has no managed parent to monitor.
        if os.environ.get("TUYA_MANAGED_WEB") != "1":
            return

        while True:
            await asyncio.sleep(2)

            if os.getppid() != original_parent:
                os.kill(os.getpid(), signal.SIGTERM)
                return

    task = asyncio.create_task(monitor_parent())

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=web_lifespan
)

from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if not origin:
            return JSONResponse(
                {"detail": "Origin header required"}, status_code=403
            )

        try:
            parsed = urlsplit(origin)
            expected = request.headers.get("host", "")
            valid = (
                parsed.scheme == "https"
                and parsed.netloc == expected
                and parsed.path == ""
                and parsed.query == ""
                and parsed.fragment == ""
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            valid = False

        if not valid:
            return JSONResponse(
                {"detail": "Invalid request origin"}, status_code=403
            )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


security = HTTPBasic()
lock = threading.Lock()

from fastapi import Request, Response
from tuya_auth import read_credentials, check_password
from tuya_sessions import (
    create_session, validate_session,
    revoke_session, revoke_all_sessions,
)

SESSION_COOKIE = "tuya_session"


def authenticate(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    # Background inventory polling must not extend the session.
    refresh = request.headers.get("X-User-Activity") == "1"

    if not validate_session(token, refresh=refresh):
        raise HTTPException(401, "Login required")


class LoginRequest(BaseModel):
    username: str
    password: str


class InitialSetupRequest(BaseModel):
    password: str
    confirm: str


@app.post("/api/auth/setup")
def setup_admin(data: InitialSetupRequest):
    from tuya_auth import create_initial_password

    if data.password != data.confirm:
        raise HTTPException(400, "Passwords do not match")

    try:
        create_initial_password(BASE, data.password)
    except ValueError as ex:
        raise HTTPException(400, str(ex))

    return {"ok": True}


@app.post("/api/auth/login")
def login(data: LoginRequest, response: Response):
    stored = read_credentials(BASE)

    if (
        stored is None
        or not secrets.compare_digest(data.username, "admin")
        or not check_password(data.password, *stored)
    ):
        raise HTTPException(401, "Invalid username or password")

    token = create_session()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@app.post("/api/auth/heartbeat", dependencies=[Depends(authenticate)])
def auth_heartbeat(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not validate_session(token, refresh=True):
        raise HTTPException(401, "Session expired")
    return {"ok": True}


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


@app.post("/api/auth/change", dependencies=[Depends(authenticate)])
def change_admin_password(data: PasswordChangeRequest):
    from tuya_auth import change_password

    if data.new_password != data.confirm_password:
        raise HTTPException(400, "New passwords do not match")

    try:
        change_password(
            BASE,
            data.current_password,
            data.new_password,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    revoke_all_sessions()
    return {"ok": True}


class PasswordRecoveryRequest(BaseModel):
    code: str
    new_password: str
    confirm_password: str


RECOVERY_INTERVAL = 5
_recovery_last_attempt = 0.0
_recovery_lock = threading.Lock()


@app.post("/api/auth/recover")
def recover_admin_password(data: PasswordRecoveryRequest):
    global _recovery_last_attempt
    from tuya_auth import complete_recovery

    with _recovery_lock:
        now = time.monotonic()
        if now - _recovery_last_attempt < RECOVERY_INTERVAL:
            raise HTTPException(
                429, "Please wait 5 seconds before trying again"
            )
        _recovery_last_attempt = now

    if data.new_password != data.confirm_password:
        raise HTTPException(400, "New passwords do not match")

    try:
        complete_recovery(
            BASE,
            data.code,
            data.new_password,
        )
    except ValueError:
        raise HTTPException(
            400, "Invalid or expired recovery code, or invalid password"
        )

    revoke_all_sessions()
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {
        "configured": read_credentials(BASE) is not None,
        "authenticated": validate_session(
            request.cookies.get(SESSION_COOKIE)
        ),
    }


def read_accounts():
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text())
    if CONFIG_FILE.exists():
        d = json.loads(CONFIG_FILE.read_text())
        return {"Default": {
            "apiKey": d.get("apiKey", ""),
            "apiSecret": d.get("apiSecret", ""),
            "apiRegion": d.get("apiRegion", "us"),
            "apiDeviceID": d.get("apiDeviceID", "")
        }}
    return {}


class Account(BaseModel):
    name: str
    apiKey: str
    apiSecret: str
    apiRegion: str = "us"
    apiDeviceID: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.get("/api/accounts", dependencies=[Depends(authenticate)])
def accounts():
    with lock:
        return {"accounts": list(read_accounts().keys())}


@app.post("/api/accounts", dependencies=[Depends(authenticate)])
def save_account(a: Account):
    if not a.name.strip() or not a.apiKey or not a.apiSecret:
        raise HTTPException(400, "Account name, Access ID and Secret required")
    with lock:
        data = read_accounts()
        data[a.name.strip()] = a.model_dump(exclude={"name"})
        tmp = ACCOUNTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(ACCOUNTS_FILE)
    return {"ok": True}



class DeviceConfig(BaseModel):
    type: str
    name: str
    id: str
    ip: str
    key: str
    version: str



def device_customparams(address, device):
    return {
        f"{address}_name": device.name.strip(),
        f"{address}_id": device.id.strip(),
        f"{address}_ip": device.ip.strip(),
        f"{address}_key": device.key,
        f"{address}_version": device.version.strip(),
    }


class DeviceSelection(BaseModel):
    devices: list[DeviceConfig]



@app.get("/api/inventory", dependencies=[Depends(authenticate)])
def get_inventory():
    with lock:
        if not INVENTORY_FILE.exists():
            raise HTTPException(
                503, "Device inventory not yet published by node server"
            )
        data = json.loads(INVENTORY_FILE.read_text())

        saved = {"devices": []}
        if DEVICES_FILE.exists():
            saved = json.loads(DEVICES_FILE.read_text())

        html_addresses = {
            d["address"]: d["id"]
            for d in saved.get("devices", [])
        }

        return {"devices": [
            {"id": d["id"], "name": d["name"], "type": d["type"],
             "address": d["address"],
             "managed_by": (
                 "html"
                 if html_addresses.get(d["address"]) == d["id"]
                 else "eisy-ui"
             )}
            for d in data.get("devices", [])
        ]}



class ReplacementRequest(BaseModel):
    address: str
    type: str
    id: str
    ip: str
    key: str
    version: str


@app.post("/api/restart", dependencies=[Depends(authenticate)])
def restart_node_server():
    import time

    try:
        before = (
            INVENTORY_FILE.stat().st_mtime_ns
            if INVENTORY_FILE.exists() else 0
        )

        result = request_eisy_plugin(
            {"action": "restart_ns"},
            timeout=30000
        )

        if not isinstance(result, dict) or not result.get("restarting"):
            raise RuntimeError("Node server did not confirm restart")

        deadline = time.monotonic() + 45

        while time.monotonic() < deadline:
            if INVENTORY_FILE.exists():
                current = INVENTORY_FILE.stat().st_mtime_ns
                if current > before:
                    return {
                        "ok": True,
                        "message": "Node server restarted and inventory refreshed."
                    }
            time.sleep(0.5)

        raise HTTPException(
            504, "Restart was accepted, but refreshed inventory was not detected."
        )

    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(502, f"Restart failed: {ex}")


@app.post("/api/replace", dependencies=[Depends(authenticate)])
def replace_device(r: ReplacementRequest):
    replacement_file = BASE / "tuya_replacements.json"

    with lock:
        if not INVENTORY_FILE.exists():
            raise HTTPException(503, "Device inventory unavailable")

        inventory = json.loads(INVENTORY_FILE.read_text())
        devices = inventory.get("devices", [])

        target = next(
            (d for d in devices if d["address"] == r.address),
            None
        )

        if target is None:
            raise HTTPException(404, "IoX node not found")

        if target["type"] != r.type:
            raise HTTPException(409, "Replacement device type mismatch")

        if not all((r.id.strip(), r.ip.strip(), r.key, r.version.strip())):
            raise HTTPException(400, "Incomplete replacement credentials")

        if r.version not in ("3.1", "3.3", "3.4", "3.5"):
            raise HTTPException(400, "Unsupported Tuya protocol version")

        # Verify the replacement before changing any saved configuration.
        replacement = None
        try:
            replacement = tinytuya.Device(r.id, r.ip, r.key)
            replacement.set_version(float(r.version))
            replacement.set_socketTimeout(3)
            replacement.set_socketRetryLimit(1)
            response = replacement.status()

            if not isinstance(response, dict) or not isinstance(
                response.get("dps"), dict
            ):
                raise HTTPException(
                    409, "Replacement device did not return valid DPS"
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                409, "Could not connect to replacement device"
            )
        finally:
            if replacement is not None:
                replacement.close()

        if any(
            d["id"] == r.id and d["address"] != r.address
            for d in devices
        ):
            raise HTTPException(409, "Tuya device already assigned to another node")


        response = read_eisy_customparams()
        if response.get("successful") is not True:
            raise HTTPException(503, "Cannot read eisy-ui configuration")

        params = response["data"]
        if not isinstance(params, dict):
            raise HTTPException(503, "Invalid eisy-ui configuration")

        params = params.copy()

        if not params.get(f"{r.address}_id"):
            raise HTTPException(
                409, "Target device is not configured in eisy-ui"
            )

        for device_type in ("fan", "switch", "outlet", "dehumidifier"):
            for n in range(1, 17):
                address = f"{device_type}{n}"
                if address != r.address and params.get(f"{address}_id") == r.id.strip():
                    raise HTTPException(
                        409, "Tuya device already configured at another address"
                    )

        params[f"{r.address}_id"] = r.id.strip()
        params[f"{r.address}_ip"] = r.ip.strip()
        params[f"{r.address}_key"] = r.key
        params[f"{r.address}_version"] = r.version.strip()

        write_eisy_customparams(params)

    return {
        "ok": True,
        "address": r.address,
        "message": "Replacement saved. Restart node server to apply."
    }


@app.get("/api/devices", dependencies=[Depends(authenticate)])
def get_saved_devices():
    with lock:
        if not DEVICES_FILE.exists():
            return {"devices": []}
        return json.loads(DEVICES_FILE.read_text())



@app.post("/api/devices", dependencies=[Depends(authenticate)])
def save_devices(selection: DeviceSelection):
    allowed = {"fan", "switch", "outlet", "dehumidifier"}

    with lock:
        try:
            response = read_eisy_customparams()
            if response.get("successful") is not True:
                raise ValueError("Could not read eisy-ui configuration")

            params = response["data"]
            if not isinstance(params, dict):
                raise ValueError("Invalid eisy-ui configuration")

            params = params.copy()
            occupied = set()
            configured_ids = {}

            if INVENTORY_FILE.exists():
                inventory = json.loads(INVENTORY_FILE.read_text())
                for item in inventory["devices"]:
                    occupied.add(item["address"])

            for device_type in allowed:
                for n in range(1, 17):
                    address = f"{device_type}{n}"
                    device_id = params.get(f"{address}_id")
                    if device_id:
                        if device_id in configured_ids:
                            raise ValueError("Duplicate configured device ID")
                        occupied.add(address)
                        configured_ids[device_id] = address

            submitted_ids = [d.id.strip() for d in selection.devices]
            if len(submitted_ids) != len(set(submitted_ids)):
                raise HTTPException(409, "Duplicate device IDs")

            addresses = {}

            for d in selection.devices:
                if d.type not in allowed:
                    raise HTTPException(400, "Invalid device type")

                if not all((
                    d.name.strip(), d.id.strip(), d.ip.strip(),
                    d.key, d.version.strip()
                )):
                    raise HTTPException(400, "Incomplete device configuration")

                existing_address = configured_ids.get(d.id.strip())

                if existing_address:
                    raise HTTPException(
                        409,
                        f"Device already configured at {existing_address}. "
                        "Use Replace to change its configuration."
                    )
                else:
                    address = next(
                        (f"{d.type}{n}" for n in range(1, 17)
                         if f"{d.type}{n}" not in occupied),
                        None
                    )
                    if address is None:
                        raise HTTPException(
                            409, f"No available {d.type} addresses"
                        )

                occupied.add(address)
                configured_ids[d.id.strip()] = address
                params.update(device_customparams(address, d))
                addresses[d.id] = address

            if selection.devices:
                write_eisy_customparams(params)

            return {
                "ok": True,
                "count": len(selection.devices),
                "addresses": addresses,
                "message": "Saved to eisy-ui. Restart node server to apply."
            }

        except HTTPException:
            raise
        except (ValueError, KeyError, TypeError) as ex:
            raise HTTPException(409, str(ex))
        except Exception as ex:
            raise HTTPException(503, f"eisy-ui configuration error: {ex}")


class DeleteDeviceRequest(BaseModel):
    address: str


@app.post("/api/delete", dependencies=[Depends(authenticate)])
def delete_device(r: DeleteDeviceRequest):
    valid_types = ("fan", "switch", "outlet", "dehumidifier")
    if not isinstance(r.address, str) or not any(
        r.address == f"{device_type}{n}"
        for device_type in valid_types
        for n in range(1, 17)
    ):
        raise HTTPException(400, "Invalid IoX node address")

    with lock:
        if not INVENTORY_FILE.exists():
            raise HTTPException(503, "Node server inventory unavailable")

        try:
            inventory = json.loads(INVENTORY_FILE.read_text())
            installed = [
                d for d in inventory.get("devices", [])
                if d.get("address") == r.address
            ]

            if len(installed) != 1:
                raise HTTPException(
                    409, "Expected exactly one matching device in inventory"
                )

            response = read_eisy_customparams()
            if response.get("successful") is not True:
                raise HTTPException(
                    503, "Could not read eisy-ui custom parameters"
                )

            params = response.get("data")
            if not isinstance(params, dict):
                raise HTTPException(
                    503, "Invalid eisy-ui custom parameter data"
                )

            prefix = r.address + "_"
            fields = [
                prefix + "name",
                prefix + "id",
                prefix + "ip",
                prefix + "key",
                prefix + "version",
            ]

            if not params.get(prefix + "id"):
                raise HTTPException(
                    404, "Device is not configured in eisy-ui"
                )

            replacement_file = BASE / "tuya_replacements.json"
            if replacement_file.exists():
                replacements = json.loads(
                    replacement_file.read_text()
                ).get("replacements", [])
                if any(
                    d.get("address") == r.address
                    for d in replacements
                ):
                    raise HTTPException(
                        409,
                        "Remove pending replacement before deleting this device"
                    )

            try:
                result = request_eisy_plugin(
                    {"action": "delete_node", "address": r.address},
                    timeout=30000,
                )
            except Exception as ex:
                raise HTTPException(
                    502, f"IoX node deletion was not confirmed: {ex}"
                )

            if not isinstance(result, dict) or (
                result.get("address") != r.address
                or result.get("deleted") is not True
            ):
                raise HTTPException(
                    502, "Node server did not confirm node deletion"
                )

            updated = dict(params)
            for field in fields:
                updated.pop(field, None)

            try:
                write_eisy_customparams(updated)
            except Exception as ex:
                raise HTTPException(
                    500,
                    "IoX node was deleted, but eisy-ui configuration "
                    f"could not be cleared. Manual cleanup is required: {ex}"
                )

            return {
                "ok": True,
                "address": r.address,
                "message": "IoX node deleted and eisy-ui configuration cleared."
            }

        except HTTPException:
            raise
        except (ValueError, KeyError, TypeError) as ex:
            raise HTTPException(409, f"Configuration error: {ex}")
        except Exception as ex:
            raise HTTPException(503, f"Deletion failed: {ex}")


@app.get("/api/cloud/{account}", dependencies=[Depends(authenticate)])
def cloud_devices(account: str):
    with lock:
        config = read_accounts().get(account)
    if not config:
        raise HTTPException(404, "Account not found")
    try:
        cloud = tinytuya.Cloud(
            apiRegion=config["apiRegion"],
            apiKey=config["apiKey"],
            apiSecret=config["apiSecret"],
            apiDeviceID=config["apiDeviceID"]
        )
        cloud.use_old_device_list = False
        result = cloud.getdevices()
        if not isinstance(result, list):
            raise ValueError("Invalid cloud response")
        return {"devices": [{
            "name": d.get("name", ""),
            "category": d.get("category", ""),
            "id": d.get("id", ""),
            "ip": d.get("ip", ""),
            "version": d.get("version", ""),
            "key": d.get("key", ""),
            "source": "Cloud"
        } for d in result if isinstance(d, dict)]}
    except Exception:
        raise HTTPException(502, "Cloud retrieval failed; check account credentials")


@app.get("/api/credentials/verify", dependencies=[Depends(authenticate)])
def verify_credentials():
    """Compare configured local keys with Tuya Cloud without changing them."""
    with lock:
        response = read_eisy_customparams()
        if response.get("successful") is not True:
            raise HTTPException(503, "Could not read eisy-ui configuration")

        params = response.get("data")
        if not isinstance(params, dict):
            raise HTTPException(503, "Invalid eisy-ui configuration")

        configured = {}
        for kind in ("fan", "switch", "outlet", "dehumidifier"):
            for n in range(1, 17):
                address = f"{kind}{n}"
                device_id = str(params.get(f"{address}_id") or "").strip()
                if device_id:
                    configured[address] = {
                        "id": device_id,
                        "name": params.get(f"{address}_name") or address,
                        "key": params.get(f"{address}_key") or ""
                    }

        accounts_config = read_accounts()

    cloud_keys = {}
    account_errors = []

    for account_name, config in accounts_config.items():
        try:
            cloud = tinytuya.Cloud(
                apiRegion=config["apiRegion"],
                apiKey=config["apiKey"],
                apiSecret=config["apiSecret"],
                apiDeviceID=config["apiDeviceID"]
            )
            cloud.use_old_device_list = False
            devices = cloud.getdevices()

            if not isinstance(devices, list):
                raise ValueError("Invalid cloud response")

            for device in devices:
                if not isinstance(device, dict):
                    continue

                device_id = str(device.get("id") or "").strip()
                key = device.get("key")

                if not device_id:
                    continue

                record = cloud_keys.setdefault(device_id, {
                    "keys": set(),
                    "invalid": False
                })

                if (
                    not isinstance(key, str)
                    or len(key) != 16
                    or key == device_id
                ):
                    record["invalid"] = True
                else:
                    record["keys"].add(key)

        except Exception:
            account_errors.append(account_name)

    results = []

    for address, device in configured.items():
        device_id = device["id"]
        stored_key = device["key"]
        record = cloud_keys.get(device_id)

        if not record:
            status = "unverified" if account_errors else "not_found"
        elif record["invalid"] or len(record["keys"]) != 1:
            status = "conflict_or_invalid"
        elif stored_key == next(iter(record["keys"])):
            status = "match"
        else:
            status = "mismatch"

        results.append({
            "address": address,
            "name": device["name"],
            "status": status
        })

    return {
        "ok": True,
        "devices": results,
        "account_errors": account_errors,
        "read_only": True
    }



class CredentialRefreshRequest(BaseModel):
    addresses: list[str]


@app.post("/api/credentials/refresh", dependencies=[Depends(authenticate)])
def refresh_credentials(request: CredentialRefreshRequest):
    """Refresh selected mismatched local keys from Tuya Cloud."""
    allowed = {
        f"{kind}{n}"
        for kind in ("fan", "switch", "outlet", "dehumidifier")
        for n in range(1, 17)
    }

    addresses = request.addresses

    if not addresses or len(addresses) != len(set(addresses)):
        raise HTTPException(400, "Select unique devices to refresh")

    if any(address not in allowed for address in addresses):
        raise HTTPException(400, "Invalid device address")

    # Read Cloud accounts without holding the lock during network requests.
    with lock:
        accounts = read_accounts()

    if not accounts:
        raise HTTPException(409, "No Tuya Cloud accounts configured")

    cloud_keys = {}

    for account_name, config in accounts.items():
        try:
            cloud = tinytuya.Cloud(
                apiRegion=config["apiRegion"],
                apiKey=config["apiKey"],
                apiSecret=config["apiSecret"],
                apiDeviceID=config["apiDeviceID"]
            )
            cloud.use_old_device_list = False
            devices = cloud.getdevices()

            if not isinstance(devices, list):
                raise ValueError("Invalid Cloud response")

            for device in devices:
                if not isinstance(device, dict):
                    continue

                device_id = str(device.get("id") or "").strip()
                key = device.get("key")

                if not device_id:
                    continue

                record = cloud_keys.setdefault(
                    device_id, {"keys": set(), "invalid": False}
                )

                if (
                    not isinstance(key, str)
                    or len(key) != 16
                    or key == device_id
                ):
                    record["invalid"] = True
                else:
                    record["keys"].add(key)

        except Exception:
            raise HTTPException(
                502,
                f"Cloud retrieval failed for account {account_name}; "
                "no credentials were changed"
            )

    with lock:
        try:
            response = read_eisy_customparams()

            if response.get("successful") is not True:
                raise HTTPException(503, "Could not read eisy-ui configuration")

            params = response.get("data")

            if not isinstance(params, dict):
                raise HTTPException(503, "Invalid eisy-ui configuration")

            updated = params.copy()
            changed = []

            # Validate every requested device before writing anything.
            for address in addresses:
                device_id = str(params.get(f"{address}_id") or "").strip()
                stored_key = params.get(f"{address}_key") or ""

                if not device_id:
                    raise HTTPException(
                        409, f"{address} is no longer configured"
                    )

                record = cloud_keys.get(device_id)

                if (
                    not record
                    or record["invalid"]
                    or len(record["keys"]) != 1
                ):
                    raise HTTPException(
                        409,
                        f"{address} has no unique valid Cloud key; "
                        "no credentials were changed"
                    )

                cloud_key = next(iter(record["keys"]))

                if stored_key != cloud_key:
                    updated[f"{address}_key"] = cloud_key
                    changed.append(address)

            if changed:
                write_eisy_customparams(updated)

            return {
                "ok": True,
                "updated": changed,
                "count": len(changed),
                "restart_required": bool(changed),
                "message": (
                    "Credentials updated. Restart node server to apply."
                    if changed else "All selected credentials already match."
                )
            }

        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503,
                "Credential refresh failed; check eisy-ui configuration"
            )


@app.get("/api/scan", dependencies=[Depends(authenticate)])
def scan():
    try:
        result = tinytuya.deviceScan(
            verbose=False, color=False
        )
        return {"devices": [{
            "name": d.get("name", ""),
            "id": d.get("gwId") or d.get("id", ""),
            "ip": d.get("ip", ip),
            "version": d.get("version", ""),
            "key": "",
            "source": "LAN"
        } for ip, d in result.items() if isinstance(d, dict)]}
    except Exception:
        raise HTTPException(502, "LAN discovery failed")



class TestDevice(BaseModel):
    id: str
    ip: str
    key: str
    version: str


@app.post("/api/test", dependencies=[Depends(authenticate)])
def test_device(d: TestDevice):
    if not d.id or not d.ip or not d.key:
        raise HTTPException(400, "Device ID, IP and key required")
    if d.version not in ("3.1", "3.3", "3.4", "3.5"):
        raise HTTPException(400, "Unsupported protocol version")

    start = time.monotonic()
    device = None
    try:
        device = tinytuya.Device(d.id, d.ip, d.key)
        device.set_version(float(d.version))
        device.set_socketTimeout(3)
        device.set_socketRetryLimit(1)
        result = device.status()

        elapsed = round((time.monotonic() - start) * 1000)

        if not isinstance(result, dict) or not isinstance(result.get("dps"), dict):
            return {"ok": False, "ms": elapsed,
                    "message": "Device did not return valid DPS"}

        return {"ok": True, "ms": elapsed,
                "message": "Connected",
                "dps_count": len(result["dps"])}
    except Exception:
        return {"ok": False, "message": "Connection failed"}
    finally:
        if device is not None:
            device.close()

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartLife / Tuya Configuration</title>
<style>
body{font:14px Arial,sans-serif;background:#f5f6f8;margin:0;padding:22px;color:#222}
main{max-width:1250px;margin:auto}
section{background:white;border-radius:10px;padding:20px;margin-bottom:18px}
h1{font-size:24px}h2{font-size:18px}
input,select{padding:9px;border:1px solid #bbb;border-radius:5px}
input{width:100%;box-sizing:border-box}
button{padding:9px 13px;border:1px solid #bbb;border-radius:6px;cursor:pointer}
.primary{background:#1769aa;color:white;border-color:#1769aa}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
label{display:block;margin-bottom:5px;font-weight:bold}
table{width:100%;border-collapse:collapse;margin-top:15px}
td,th{text-align:left;border-bottom:1px solid #ddd;padding:9px;font-size:12px}
th{background:#f2f3f5}
.key{font-family:monospace}
.note{color:#666;font-size:12px}
.error{color:#b00020}
.actions{display:flex;gap:9px;flex-wrap:wrap}
.spinner{
 display:inline-block;width:13px;height:13px;
 border:2px solid #ccc;border-top-color:#1769aa;
 border-radius:50%;animation:spin .7s linear infinite;
 vertical-align:middle;margin-right:7px
}
@keyframes spin{to{transform:rotate(360deg)}}
button:disabled{opacity:.55;cursor:wait}

@media(max-width:700px){.grid{grid-template-columns:1fr}section{overflow-x:auto}}

.device-icon {
 display:inline-flex;
 align-items:center;
 justify-content:center;
 width:28px;
 height:28px;
 margin-right:8px;
 vertical-align:middle;
 color:#2563eb;
}
.device-icon svg {
 width:24px;
 height:24px;
 fill:none;
 stroke:currentColor;
 stroke-width:1.8;
 stroke-linecap:round;
 stroke-linejoin:round;
}

#restartModal{
 position:fixed;inset:0;background:rgba(0,0,0,.45);
 display:none;align-items:center;justify-content:center;
 z-index:9999;
}
#restartModal.show{display:flex}
#restartModal .dialog{
 background:white;color:#222;padding:28px;
 border-radius:12px;min-width:300px;max-width:420px;
 text-align:center;box-shadow:0 8px 30px #0004;
}
#restartModal .spinner{
 display:inline-block;margin:12px;
}
#restartModal button{margin-top:16px}

#loginScreen{max-width:400px;margin:10vh auto}
#loginScreen section{box-shadow:0 4px 20px #0001}
#loginScreen input{margin-bottom:14px}
#editor{display:none}
#logoutBtn{float:right}
</style>
</head>
<body>
<div id="setupScreen" style="display:none">
<section style="max-width:400px;margin:10vh auto">
<h1>SmartLife / Tuya First-Time Setup</h1>
<p>Create an administrator password to secure the web interface.</p>
<label>New Password (minimum 12 characters)</label>
<input id="setupPassword" type="password" autocomplete="new-password">
<label>Confirm Password</label>
<input id="setupConfirm" type="password" autocomplete="new-password">
<p id="setupError" class="error"></p>
<button class="primary" onclick="submitInitialSetup()">
Create Administrator Password
</button>
</section>
</div>

<div id="loginScreen" style="display:none">
<section>
<h1>SmartLife / Tuya Login</h1>
<label>Username</label>
<input id="loginUser" value="admin" autocomplete="username">
<label>Password</label>
<input id="loginPassword" type="password"
       autocomplete="current-password">
<button class="primary" onclick="loginUser()">Login</button>
<button type="button" onclick="showRecovery()">Forgot Password?</button>

<div id="recoveryPanel" style="display:none;margin-top:20px">
<h2>Reset Administrator Password</h2>
<p>Recovery requires SSH access to your eisy or Polisy.
You must know your device's SSH username and password.</p>
<p>Connect using SSH and run:</p>
<pre style="white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px">cd ~/tuya-fan &amp;&amp; python3 tuya_auth.py reset</pre>
<p>Enter the recovery code displayed in SSH.
It expires after 15 minutes.</p>
<label>Recovery Code</label>
<input id="recoveryCode" autocomplete="off">
<label>New Password (minimum 12 characters)</label>
<input id="recoveryPassword" type="password">
<label>Confirm New Password</label>
<input id="recoveryConfirm" type="password">
<p id="recoveryError" class="error"></p>
<div class="actions">
<button class="primary" onclick="submitRecovery()">Reset Password</button>
<button onclick="hideRecovery()">Cancel</button>
</div>
</div>
<p id="loginError" class="error"></p>
</section>
</div>
<div id="passwordDialog" style="display:none;position:fixed;inset:0;
background:#0008;z-index:10000;align-items:center;justify-content:center">
<section style="width:min(400px,90vw);margin:15px">
<h2>Change Administrator Password</h2>
<label>Current Password</label>
<input id="currentPassword" type="password" autocomplete="current-password">
<label>New Password (minimum 12 characters)</label>
<input id="newPassword" type="password" autocomplete="new-password">
<label>Confirm New Password</label>
<input id="confirmPassword" type="password" autocomplete="new-password">
<p id="passwordError" class="error"></p>
<div class="actions">
<button class="primary" onclick="submitPasswordChange()">Save Password</button>
<button onclick="closePasswordDialog()">Cancel</button>
</div>
</section>
</div>
<div id="editor">
<main>
<div style="display:flex;justify-content:flex-end;gap:8px">
<button onclick="openPasswordDialog()">Change Password</button>
<button id="logoutBtn" onclick="logoutUser()">Logout</button>
</div>
<h1>SmartLife / Tuya Configuration</h1>
<section>
<h2>Tuya Cloud Accounts</h2>
<p class="note">Cloud credentials are stored on the eisy. Existing PG3x device settings are not changed.</p>
<div class="grid">
<div><label>Account Name</label><input id="name" placeholder="Home or Office"></div>
<div><label>Region</label>
<select id="region"><option value="us">US</option><option value="eu">EU</option>
<option value="eu-w">EU West</option><option value="cn">China</option>
<option value="in">India</option></select></div>
<div><label>Access ID</label><input id="access" autocomplete="off"></div>
<div><label>Access Secret</label><input id="secret" type="password" autocomplete="new-password"></div>
<div><label>Device ID (optional)</label><input id="deviceid"></div>
</div>
<p><button class="primary" onclick="saveAccount()">Save Cloud Account</button></p>
</section>
<section>
<h2>Device Discovery</h2>
<div class="actions">
<select id="accounts"></select>
<button class="primary" onclick="getCloud()">Retrieve Cloud Devices &amp; Keys</button>
<button onclick="scanLAN()">Scan Local Network</button>
<button onclick="verifyCredentials()">Verify Credentials</button>
<button id="restartBtn" onclick="restartNodeServer()">Restart Node Server</button>
<button onclick="toggleKeys()">Show / Hide Keys</button>
</div>
<p id="status" class="note"></p>
<div style="overflow-x:auto">
<table><thead><tr>
<th><input type="checkbox" id="selectall" onclick="selectAll(this.checked)"></th><th>Name</th><th>Type</th><th>Device ID</th><th>IP</th><th>Version</th>
<th>Source</th><th>Local Key</th><th>Action</th>
</tr></thead><tbody id="devices"></tbody></table>
<p class="actions">
 <span id="selectedCount">0 devices selected</span>
 <button class="primary" id="previewBtn" onclick="previewSelected()" disabled>
 Preview Selected Devices
 </button>
 <button class="primary" id="saveBtn"
 onclick="saveSelected()" disabled>
 Save Selected Devices
 </button>
</p>
<pre id="preview" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
</div>
</section>
</main>
</div>
<script>

function showRecovery(){
 document.getElementById("recoveryPanel").style.display="block";
}
function hideRecovery(){
 document.getElementById("recoveryPanel").style.display="none";
 for(const id of ["recoveryCode","recoveryPassword","recoveryConfirm"]){
  document.getElementById(id).value="";
 }
 document.getElementById("recoveryError").textContent="";
}
async function submitRecovery(){
 const code=document.getElementById("recoveryCode").value.trim();
 const password=document.getElementById("recoveryPassword").value;
 const confirm=document.getElementById("recoveryConfirm").value;
 const error=document.getElementById("recoveryError");
 error.textContent="";
 if(password.length<12 || password!==confirm){
  error.textContent="Password must be at least 12 characters and match confirmation.";
  return;
 }
 try{
  const r=await fetch("/api/auth/recover",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    code:code,new_password:password,confirm_password:confirm
   })
  });
  if(!r.ok){
   const d=await r.json();
   throw Error(d.detail||"Recovery failed");
  }
  hideRecovery();
  showLogin("Password reset. Log in with your new password.");
 }catch(e){
  error.textContent=e.message;
 }
}
function openPasswordDialog(){
 document.getElementById("passwordError").textContent="";
 document.getElementById("passwordDialog").style.display="flex";
}

function closePasswordDialog(){
 for(const id of ["currentPassword","newPassword","confirmPassword"]){
  document.getElementById(id).value="";
 }
 document.getElementById("passwordDialog").style.display="none";
}

async function submitPasswordChange(){
 const current=document.getElementById("currentPassword").value;
 const password=document.getElementById("newPassword").value;
 const confirm=document.getElementById("confirmPassword").value;
 const error=document.getElementById("passwordError");

 if(password.length<12){
  error.textContent="Password must contain at least 12 characters.";
  return;
 }
 if(password!==confirm){
  error.textContent="New passwords do not match.";
  return;
 }

 try{
  const r=await fetch("/api/auth/change",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    current_password:current,
    new_password:password,
    confirm_password:confirm
   })
  });
  if(!r.ok){
   const d=await r.json();
   throw Error(d.detail||"Password change failed");
  }
  closePasswordDialog();
  showLogin("Password changed. Please log in with your new password.");
 }catch(e){
  error.textContent=e.message;
 }
}

let authenticated = false;
let lastActivity = 0;
const IDLE_LIMIT = 3600000;

function showSetup(){
 document.getElementById("editor").style.display="none";
 document.getElementById("loginScreen").style.display="none";
 document.getElementById("setupScreen").style.display="block";
 authenticated=false;
}

async function submitInitialSetup(){
 const error=document.getElementById("setupError");
 error.textContent="";

 const password=document.getElementById("setupPassword").value;
 const confirm=document.getElementById("setupConfirm").value;

 if(password.length<12){
  error.textContent="Password must contain at least 12 characters";
  return;
 }

 if(password!==confirm){
  error.textContent="Passwords do not match";
  return;
 }

 try{
  const r=await fetch("/api/auth/setup",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({password,confirm})
  });

  const d=await r.json();
  if(!r.ok)throw Error(d.detail||"Setup failed");

  document.getElementById("setupPassword").value="";
  document.getElementById("setupConfirm").value="";
  document.getElementById("setupScreen").style.display="none";
  showLogin("Administrator password created. Please log in.");
 }catch(e){
  error.textContent=e.message;
 }
}

function showLogin(message=""){
 closePasswordDialog();
 document.getElementById("editor").style.display="none";
 document.getElementById("loginScreen").style.display="block";
 document.getElementById("loginError").textContent=message;
 authenticated=false;
}

function showEditor(){
 document.getElementById("loginScreen").style.display="none";
 document.getElementById("editor").style.display="block";
 authenticated=true;
 lastActivity=Date.now();
}

async function loginUser(){
 const error=document.getElementById("loginError");
 error.textContent="";
 try{
  const r=await fetch("/api/auth/login",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    username:document.getElementById("loginUser").value,
    password:document.getElementById("loginPassword").value
   })
  });
  if(!r.ok)throw Error("Invalid username or password");
  document.getElementById("loginPassword").value="";
  showEditor();
  await loadAccounts();
  await loadInventory();
 }catch(e){
  showLogin(e.message);
 }
}

async function logoutUser(){
 try{
  await fetch("/api/auth/logout",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store"
  });
 }finally{
  cloudRecords=[];
  lanRecords=[];
  showLogin();
 }
}

async function initializeAuthentication(){
 try{
  const r=await fetch("/api/auth/status",{
   credentials:"same-origin",cache:"no-store"
  });
  const d=await r.json();
  if(!d.configured){
   showSetup();
  }else if(d.authenticated){
   showEditor();
   await loadAccounts();
   await loadInventory();
  }else{
   showLogin();
  }
 }catch(e){
  showLogin("Unable to contact server");
 }
}

["pointerdown","keydown"].forEach(eventName=>{
 document.addEventListener(eventName,()=>{
  if(authenticated)lastActivity=Date.now();
 },{passive:true});
});

setInterval(async ()=>{
 if(!authenticated)return;
 if(Date.now()-lastActivity>=60000)return;
 try{
  const r=await fetch("/api/auth/heartbeat",{
   method:"POST",
   credentials:"same-origin",
   cache:"no-store"
  });
  if(r.status===401)showLogin("Session expired. Please log in again.");
 }catch(e){}
},30000);

setInterval(()=>{
 if(authenticated && Date.now()-lastActivity>=IDLE_LIMIT){
  logoutUser();
 }
},30000);

let cloudRecords = [];
let lanRecords = [];
let showKeys = false;
const selectedDevices = new Set();
const deviceTypes = new Map();
let currentDevices = new Map();
const configuredDevices = new Map();

let replacementTarget = null;
let testedReplacementId = null;

function cancelReplacement(){
 replacementTarget = null;
 testedReplacementId = null;
 render();
 status("Replacement cancelled.");
}

function startReplacement(target){
 alert(
  "Replacement Mode\n\n"+
  "1. Click Scan Local Network to discover available devices.\n"+
  "2. Click Test Connection beside the replacement device.\n"+
  "3. Click Use as Replacement after a successful test."
 );
 replacementTarget = target;
 testedReplacementId = null;
 selectedDevices.clear();
 render();
 status(
  `Replacing ${target.name} (${target.address}). `+
  `Click "Scan Local Network" first, then use "Test Connection" `+
  `beside an eligible replacement device.`
 );
}


let inventoryLoaded = false;

async function loadInventory(){
 const pending = [...configuredDevices.values()]
  .filter(d=>d.pendingRestart);

 try{
  const data = await request("/api/inventory");
  const fresh = new Map();

  for(const d of data.devices||[]){
   if(d.id)fresh.set(d.id,d);
  }

  // Preserve pending devices only until the node server publishes them.
  for(const d of pending){
   if(!fresh.has(d.id))fresh.set(d.id,d);
  }

  configuredDevices.clear();
  for(const [id,d] of fresh)configuredDevices.set(id,d);

  inventoryLoaded = true;
  render();
 }catch(e){
  status("Could not load configured-device inventory: "+e.message,true);
 }
}

async function refreshAfterChange(message, removeIds=[]){
 await loadInventory();

 for(const id of removeIds){
  configuredDevices.delete(id);
 }

 const account=val("accounts");
 if(account){
  try{
   const data=await request("/api/cloud/"+encodeURIComponent(account));
   cloudRecords=data.devices||[];
  }catch(e){
   status(message+" Cloud refresh failed: "+e.message,true);
  }
 }

 render();
 status(message);
}

function val(id){return document.getElementById(id).value}
function status(msg,error=false,busy=false){
 const e=document.getElementById("status");
 e.replaceChildren();
 e.className=error?"error":"note";
 e.style.fontSize=busy?"22px":"";
 e.style.fontWeight=busy?"bold":"";
 e.style.padding=busy?"12px 0":"";
 if(busy){
  const spinner=document.createElement("span");
  spinner.className="spinner";e.appendChild(spinner);
 }
 e.appendChild(document.createTextNode(msg));
}
async function request(url,options={}){
 const headers=new Headers(options.headers||{});

 const r=await fetch(url,{
  ...options,
  cache:"no-store",
  credentials:"same-origin",
  headers
 });
 if(r.status===401){
  showLogin("Session expired. Please log in again.");
  throw Error("Session expired");
 }
 const d=await r.json();
 if(!r.ok)throw Error(d.detail||"Request failed");
 return d;
}
async function loadAccounts(){
 const d=await request("/api/accounts");
 const s=document.getElementById("accounts");
 s.replaceChildren();
 for(const name of d.accounts){
  const o=document.createElement("option");o.value=name;o.textContent=name;s.appendChild(o);
 }
}
async function saveAccount(){
 try{
  await request("/api/accounts",{method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    name:val("name"),apiKey:val("access"),apiSecret:val("secret"),
    apiRegion:val("region"),apiDeviceID:val("deviceid")
   })});
  document.getElementById("secret").value="";
  await loadAccounts();status("Cloud account saved.");
 }catch(e){status(e.message,true)}
}
async function getCloud(){
 try{
  status("Retrieving cloud devices...",false,true);
  const name=val("accounts");
  if(!name)throw Error("Select a cloud account");
  const d=await request("/api/cloud/"+encodeURIComponent(name));
  cloudRecords=d.devices;render();
  status(`${cloudRecords.length} cloud devices retrieved.`);
 }catch(e){status(e.message,true)}
}

function showRestartModal(message,busy){
 const modal=document.getElementById("restartModal");
 document.getElementById("restartModalMessage").textContent=message;
 document.getElementById("restartModalSpinner").style.display=
  busy?"inline-block":"none";
 document.getElementById("restartModalOK").style.display=
  busy?"none":"inline-block";
 modal.classList.add("show");
}
function closeRestartModal(){
 document.getElementById("restartModal").classList.remove("show");
}

async function restartNodeServer(){
 if(!confirm(
  "Restart the Smart Life / Tuya node server?\n\n"+
  "All devices will temporarily go offline."
 ))return;

 const btn=document.getElementById("restartBtn");
 btn.disabled=true;

 try{
  status("Restarting node server. Please wait...",false,true);
  showRestartModal("Restarting node server. Please wait...",true);

  const result=await request("/api/restart",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:"{}"
  });

  selectedDevices.clear();
  await loadInventory();
  render();
  status(result.message);
  showRestartModal(result.message,false);
 }catch(e){
  status("Restart: "+e.message,true);
  showRestartModal("Restart failed: "+e.message,false);
 }finally{
  btn.disabled=false;
 }
}


async function verifyCredentials(){
 try{
  status("Verifying configured device credentials...",false,true);
  const result=await request("/api/credentials/verify");

  const devices=result.devices||[];
  const mismatches=devices.filter(d=>d.status==="mismatch");
  const errors=result.account_errors||[];

  const lines=devices.map(d=>
   `${d.name} (${d.address}): ${d.status}`
  );

  const summary=lines.join("\n")+
   (errors.length?"\nCloud account errors: "+errors.join(", "):"");

  alert("Credential Verification (read-only)\n\n"+summary);

  status(`${devices.length} devices checked; ${mismatches.length} mismatches.`);

  if(errors.length){
   status("Cloud account errors detected. Credential refresh unavailable.",true);
   return;
  }

  if(!mismatches.length)return;

  const names=mismatches.map(d=>`${d.name} (${d.address})`).join("\n");

  if(!confirm(
   "Refresh credentials for these devices?\n\n"+
   names+
   "\n\nOnly their local keys will be updated. "+
   "A node server restart will be required."
  ))return;

  status("Refreshing device credentials...",false,true);

  const refreshed=await request("/api/credentials/refresh",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    addresses:mismatches.map(d=>d.address)
   })
  });

  alert(
   `Credential Refresh\n\n${refreshed.message}\n`+
   `Keys updated: ${refreshed.count}`
  );

  status(refreshed.message);

 }catch(e){
  status("Credential verification/refresh: "+e.message,true);
 }
}

async function scanLAN(){
 try{
  status("Scanning local network...",false,true);
  const d=await request("/api/scan");
  lanRecords=d.devices;render();
  status(`${lanRecords.length} LAN devices discovered.`);
 }catch(e){status(e.message,true)}
}
function toggleKeys(){showKeys=!showKeys;render()}
function addCell(tr,value){
 const td=document.createElement("td");
 td.textContent=value==null?"":String(value);tr.appendChild(td);return td;
}

const deviceIcons = {
 Fan:'<circle cx="12" cy="12" r="2"/><path d="M12 10C7 2 2 5 5 10M14 12c8-5 9 2 4 4M11 14c-2 9-9 6-8 1"/>',
 Switch:'<path d="M3 17V7M8 17V12M13 17V4M18 17V9M22 20H2"/>',
 Outlet:'<path d="M8 3v6M16 3v6M7 9h10v4a5 5 0 0 1-10 0V9ZM12 18v3"/>',
 Dehumidifier:'<path d="M12 3C9 8 5 12 5 16a7 7 0 0 0 14 0c0-4-4-8-7-13Z"/><path d="M9 17a3 3 0 0 0 3 3"/>'
};

function deviceIcon(type){
 const span=document.createElement("span");
 span.className="device-icon";
 const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
 svg.setAttribute("viewBox","0 0 24 24");
 svg.innerHTML=deviceIcons[type]||deviceIcons.Switch;
 span.appendChild(svg);
 return span;
}

function detectDeviceType(d){
 const category=String(d.category||"").toLowerCase();

 if(["fs"].includes(category))return "Fan";
 if(["cs"].includes(category))return "Dehumidifier";

 // Tuya sockets may or may not support power monitoring.
 // Don't assume every socket has metering.
 if(["cz"].includes(category))return "Outlet";

 // Switch category alone doesn't establish metering support.
 return "Switch";
}

function render(){
 const byId=new Map();
 for(const d of cloudRecords)if(d.id)byId.set(d.id,{...d});
 for(const d of lanRecords){
  if(!d.id)continue;
  const old=byId.get(d.id);
  byId.set(d.id,old?{
   ...old,ip:d.ip||old.ip,version:d.version||old.version,
   name:old.name||d.name,source:"Cloud + LAN"
  }:{...d});
 }
 currentDevices=byId;
 for(const id of [...selectedDevices]){
  const d=byId.get(id);
  if(!d||!d.ip||!d.version||!d.key)selectedDevices.delete(id);
 }
 const body=document.getElementById("devices");body.replaceChildren();
 for(const d of byId.values()){
  const tr=document.createElement("tr");

  const selectTd=document.createElement("td");
  const cb=document.createElement("input");
  cb.type="checkbox";
  cb.checked=selectedDevices.has(d.id);
  const configured=configuredDevices.has(d.id);
  cb.disabled=!!replacementTarget||!inventoryLoaded||configured||
    !(d.id&&d.ip&&d.version&&d.key);
  if(configured)selectedDevices.delete(d.id);
  cb.onchange=()=>{
   if(cb.checked)selectedDevices.add(d.id);
   else selectedDevices.delete(d.id);
   updateSelection();
  };
  selectTd.appendChild(cb);
  tr.appendChild(selectTd);

  const nameTd=document.createElement("td");
  const initialType=deviceTypes.get(d.id)||detectDeviceType(d);
  const icon=deviceIcon(initialType);
  nameTd.appendChild(icon);
  nameTd.appendChild(document.createTextNode(d.name||"Unnamed"));
  tr.appendChild(nameTd);

  const typeTd=document.createElement("td");
  const typeSelect=document.createElement("select");
  for(const type of ["Fan","Switch","Outlet","Dehumidifier"]){
   const option=document.createElement("option");
   option.value=type;
   option.textContent=type==="Switch"?"Power Monitor":type;
   typeSelect.appendChild(option);
  }
  const detected=deviceTypes.get(d.id)||detectDeviceType(d);
  typeSelect.value=detected;
  typeSelect.onchange=()=>{
   deviceTypes.set(d.id,typeSelect.value);
   icon.replaceWith(deviceIcon(typeSelect.value));
  };
  typeTd.appendChild(typeSelect);
  tr.appendChild(typeTd);
  addCell(tr,d.id);
  addCell(tr,d.ip);
  addCell(tr,d.version);
  const configuredInfo=configuredDevices.get(d.id);
  addCell(tr,configured
   ? d.source+(configuredInfo.pendingRestart
      ? " — Saved — Restart Required"
      : " — Already Configured")
   : d.source);
  const key=d.key||"";
  addCell(tr,showKeys?key:(key?"••••••••••••••••":"Unavailable")).className="key";
  const td=document.createElement("td");
  const b=document.createElement("button");
  b.textContent="Copy Key";b.disabled=!key;
  b.onclick=async()=>{
   try{await navigator.clipboard.writeText(key);b.textContent="Copied"}
   catch{b.textContent="Copy failed"}
  };
  td.appendChild(b);

  const test=document.createElement("button");
  test.textContent="Test Connection";
  test.style.marginLeft="6px";
  const eligibleReplacement=!!replacementTarget &&
   !configured &&
   (deviceTypes.get(d.id)||detectDeviceType(d)).toLowerCase()===
    replacementTarget.type &&
   !!(d.id&&d.ip&&d.version&&key);

  test.disabled=replacementTarget
   ? !eligibleReplacement
   : !(d.id&&d.ip&&d.version&&key);

  const testWrapper=document.createElement("span");
  testWrapper.style.display="inline-block";
  testWrapper.style.marginLeft="6px";

  if(test.disabled){
   testWrapper.title=replacementTarget
    ? "Only unconfigured devices of the same type can be tested as replacements."
    : !d.ip
      ? 'Click "Scan Local Network" first to discover the device.'
      : !key
        ? "Local key unavailable. Retrieve the device through Smart Life cloud discovery."
        : "Device information incomplete. Scan the local network.";
  }

  if(replacementTarget){
   const isReplacementTarget=d.id===replacementTarget.id;
   tr.style.opacity=(eligibleReplacement||isReplacementTarget)?"1":"0.35";
   typeSelect.disabled=true;
   b.disabled=true;
  }

  test.onclick=async()=>{
   test.disabled=true;
   test.replaceChildren();
   const spinner=document.createElement("span");
   spinner.className="spinner";
   test.appendChild(spinner);
   test.appendChild(document.createTextNode("Testing..."));

   try{
    const result=await request("/api/test",{
     method:"POST",
     headers:{"Content-Type":"application/json"},
     body:JSON.stringify({
      id:d.id,ip:d.ip,key:key,version:String(d.version)
     })
    });
    if(result.ok && replacementTarget && eligibleReplacement){
     testedReplacementId=d.id;
     test.textContent="Use as Replacement";
     test.disabled=false;
     test.onclick=()=>confirmReplacement(d);
    }else{
     test.textContent=result.ok
       ? "Connected ("+result.ms+" ms)"
       : result.message;
    }
   }catch(e){
    test.textContent="Test failed";
   }finally{
    if(!(replacementTarget && testedReplacementId===d.id)){
     setTimeout(()=>{
      if(!test.isConnected)return;
      if(replacementTarget){
       if(!eligibleReplacement)return;
       test.disabled=false;
      }else{
       test.disabled=!(d.id&&d.ip&&d.version&&key);
      }
      test.textContent="Test Connection";
     },4000);
    }
   }
  };

  test.style.marginLeft="0";
  testWrapper.appendChild(test);
  td.appendChild(testWrapper);

  if(configured && inventoryLoaded && !replacementTarget){
   const replace=document.createElement("button");
   replace.textContent="Replace";
   replace.style.marginLeft="6px";
   replace.onclick=()=>startReplacement(configuredDevices.get(d.id));
   td.appendChild(replace);
  }

  if(configured && !replacementTarget){
   const info=configuredDevices.get(d.id);
   const wrapper=document.createElement("span");
   wrapper.style.marginLeft="6px";

   const del=document.createElement("button");
   del.textContent="Delete";
   del.onclick=()=>deleteHtmlDevice(info);
   wrapper.title="Delete the IoX node and clear its eisy-ui configuration.";

   wrapper.appendChild(del);
   td.appendChild(wrapper);
  }

  if(replacementTarget && d.id===replacementTarget.id){
   const cancel=document.createElement("button");
   cancel.textContent="Cancel Replacement";
   cancel.style.marginLeft="6px";
   cancel.onclick=cancelReplacement;
   td.appendChild(cancel);
  }

  tr.appendChild(td);
  body.appendChild(tr);
 }
 updateSelection();
}



async function deleteHtmlDevice(info){
 if(!confirm(
  `Delete ${info.name} (${info.address})?\n\n`+
  `This will request removal of the IoX node and clear its eisy-ui configuration.`
 ))return;

 try{
  const result=await request("/api/delete",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({address:info.address})
  });
  await refreshAfterChange(result.message);
 }catch(e){
  status("Deletion failed: "+e.message,true);
 }
}

async function confirmReplacement(d){
 const target=replacementTarget;
 if(!target || testedReplacementId!==d.id)return;

 if(!confirm(
  `Replace ${target.name}?\n\n`+
  `IoX node: ${target.address} (preserved)\n`+
  `Replacement: ${d.name||"Unnamed"}\n\n`+
  `The existing IoX node will not be deleted.`
 ))return;

 try{
  status("Saving replacement...",false,true);
  const result=await request("/api/replace",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({
    address:target.address,
    type:target.type,
    id:d.id,
    ip:d.ip,
    key:d.key,
    version:String(d.version)
   })
  });

  configuredDevices.delete(target.id);
  configuredDevices.set(d.id,{
   id:d.id,
   name:target.name,
   type:target.type,
   address:target.address,
   managed_by:"eisy-ui",
   pendingRestart:true
  });
  replacementTarget=null;
  testedReplacementId=null;
  await refreshAfterChange(
   `Replacement saved for ${result.address}. Restart the node server to apply.`,
   [target.id]
  );
 }catch(e){
  status("Replacement failed: "+e.message,true);
 }
}

function selectAll(checked){
 selectedDevices.clear();
 if(checked){
  for(const d of currentDevices.values()){
   if(inventoryLoaded&&!configuredDevices.has(d.id)&&
      d.id&&d.ip&&d.version&&d.key)selectedDevices.add(d.id);
  }
 }
 render();
}

function updateSelection(){
 const count=selectedDevices.size;
 document.getElementById("selectedCount").textContent=
  count+" device"+(count===1?"":"s")+" selected";
 document.getElementById("previewBtn").disabled=
  !!replacementTarget||!inventoryLoaded||count===0;
 document.getElementById("saveBtn").disabled=
  !!replacementTarget||!inventoryLoaded||count===0;

 const eligible=[...currentDevices.values()].filter(
  d=>inventoryLoaded&&!configuredDevices.has(d.id)&&d.id&&d.ip&&d.version&&d.key
 );
 document.getElementById("selectall").checked=
  eligible.length>0&&eligible.every(d=>selectedDevices.has(d.id));
}


async function saveSelected(){
 const devices=[];

 for(const id of selectedDevices){
  const d=currentDevices.get(id);
  if(!inventoryLoaded||configuredDevices.has(id)||!d||!d.ip||!d.version||!d.key)continue;

  devices.push({
   type:(deviceTypes.get(id)||detectDeviceType(d)).toLowerCase(),
   name:d.name||"Unnamed",
   id:d.id,
   ip:d.ip,
   key:d.key,
   version:String(d.version)
  });
 }

 if(!devices.length){
  status("No complete devices selected.",true);
  return;
 }

 if(!confirm("Save "+devices.length+
   " selected device(s) to local configuration?"))return;

 const btn=document.getElementById("saveBtn");
 btn.disabled=true;

 try{
  status("Saving device configuration...",false,true);
  const result=await request("/api/devices",{
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body:JSON.stringify({devices})
  });
  for(const d of devices){
   selectedDevices.delete(d.id);
   configuredDevices.set(d.id,{
    id:d.id,
    name:d.name,
    type:d.type,
    address:result.addresses[d.id],
    managed_by:"html",
    pendingRestart:true
   });
  }
  await refreshAfterChange(
   "Saved successfully. "+result.count+
   " total devices in configuration. Restart node server to apply."
  );
 }catch(e){
  status("Save failed: "+e.message,true);
 }finally{
  btn.disabled=false;
 }
}

function previewSelected(){
 const counters={Fan:0,Switch:0,Outlet:0,Dehumidifier:0};
 const prefixes={Fan:"fan",Switch:"switch",
                 Outlet:"outlet",Dehumidifier:"dehumidifier"};
 const output={};

 for(const id of selectedDevices){
  const d=currentDevices.get(id);
  if(!d)continue;

  const type=deviceTypes.get(id)||"Switch";
  counters[type]++;

  if(counters[type]>16){
   status("Maximum 16 devices per type",true);
   return;
  }

  const prefix=prefixes[type]+counters[type]+"_";
  output[prefix+"name"]=d.name||"Unnamed";
  output[prefix+"id"]=d.id;
  output[prefix+"ip"]=d.ip;
  output[prefix+"key"]=d.key;
  output[prefix+"version"]=String(d.version);
 }

 // Do not display local keys in the preview.
 const safe={...output};
 for(const k of Object.keys(safe)){
  if(k.endsWith("_key"))safe[k]="[HIDDEN]";
 }

 document.getElementById("preview").textContent=
  JSON.stringify(safe,null,2);

 status("Configuration preview generated. No PG3x settings changed.");
}

initializeAuthentication();

// Reconcile pending configuration with the live node-server inventory.
setInterval(() => {
 if(inventoryLoaded)loadInventory();
}, 15000);
</script>

<div id="restartModal" role="dialog" aria-modal="true"
     aria-labelledby="restartModalMessage">
 <div class="dialog">
  <div id="restartModalSpinner" class="spinner"></div>
  <p id="restartModalMessage"></p>
  <button id="restartModalOK" class="primary"
          onclick="closeRestartModal()" style="display:none">OK</button>
 </div>
</div>

</body>
</html>
"""

if __name__ == "__main__":
    identity = json.loads(IDENTITY_FILE.read_text())
    profile = str(identity.get("profileNum", ""))

    if not profile.isdigit():
        raise RuntimeError("Invalid PG3x profile number")

    cert = BASE / f"plugin_{profile}.cert"
    key = BASE / f"plugin_{profile}.key"

    if not cert.is_file() or not key.is_file():
        raise RuntimeError(f"HTTPS certificate or key missing for slot {profile}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8767,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
        access_log=False
    )
