from pathlib import Path
import os
import json
#!/usr/bin/env python3

import time
import threading
import tinytuya
import udi_interface

LOGGER = udi_interface.LOGGER


MODE_TO_ISY = {
    "normal": 0,
    "sleep": 1,
    "nature": 2,
}

ISY_TO_MODE = {
    0: "normal",
    1: "sleep",
    2: "nature",
}

DIR_TO_ISY = {
    "forward": 0,
    "reverse": 1,
}

ISY_TO_DIR = {
    0: "forward",
    1: "reverse",
}

TIMER_TO_ISY = {
    "off": 0,
    "1hour": 1,
    "2hour": 2,
    "4hour": 3,
    "8hour": 4,
}

ISY_TO_TIMER = {
    0: "off",
    1: "1hour",
    2: "2hour",
    3: "4hour",
    4: "8hour",
}


# IMPORTANT: Every Tuya device must use its own background worker.
# Socket timeouts alone did not prevent offline devices from blocking
# commands to other devices. All network commands and polling must run
# through the device worker, never directly on the PG3x event thread.
# Use ordered commands for multi-function devices (fans/dehumidifiers).
# Also configure TinyTuya socket timeout=3 and retry limit=1.

class TuyaWorker:
    """One background worker per device; latest pending command wins."""

    def __init__(self, name):
        self.name = name
        self._condition = threading.Condition()
        self._pending = None
        self._ordered = []
        self._busy = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, operation):
        with self._condition:
            self._pending = operation
            self._condition.notify()

    def submit_ordered(self, operation):
        with self._condition:
            self._ordered.append(operation)
            self._condition.notify()

    def submit_poll(self, operation):
        with self._condition:
            if not self._busy and self._pending is None and not self._ordered:
                self._pending = operation
                self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._ordered:
                    self._condition.wait()
                if self._ordered:
                    operation = self._ordered.pop(0)
                else:
                    operation = self._pending
                    self._pending = None
                self._busy = True
            try:
                operation()
            except Exception:
                LOGGER.exception("%s: worker operation failed", self.name)
            finally:
                with self._condition:
                    self._busy = False


class TuyaFan(udi_interface.Node):

    id = "tuyafan"

    drivers = [
        {"driver": "ST",  "value": 0, "uom": 25},
        {"driver": "GV1", "value": 1, "uom": 25},
        {"driver": "GV2", "value": 0, "uom": 25},
        {"driver": "GV3", "value": 0, "uom": 25},
        {"driver": "GV4", "value": 0, "uom": 25},
        {"driver": "GV5", "value": 0, "uom": 51},
        {"driver": "GV6", "value": 0, "uom": 25},
    ]

    def __init__(self, polyglot, primary, address, name, device_id, ip, key, version="3.4"):
        super().__init__(polyglot, primary, address, name)

        self.device_id = device_id
        self.ip = ip
        self.key = key
        self.version = float(version)

        self.device = tinytuya.Device(
            self.device_id,
            self.ip,
            self.key
        )
        self.device.set_version(self.version)
        self.device.set_socketTimeout(3)
        self.device.set_socketRetryLimit(1)
        self.device.set_socketPersistent(True)
        self._worker = TuyaWorker(self.name)
        self._worker = TuyaWorker(self.name)

    def query(self, command=None):
        try:
            result = self.device.status()

            if "dps" not in result:
                LOGGER.error(f"{self.name}: bad status response: {result}")
                return False

            dps = result["dps"]

            self.setDriver("ST",  1 if dps.get("1") else 0)
            self.setDriver("GV1", int(dps.get("3", 1)))
            self.setDriver("GV2", MODE_TO_ISY.get(dps.get("2"), 0))
            self.setDriver("GV3", DIR_TO_ISY.get(dps.get("8"), 0))
            self.setDriver("GV4", 1 if dps.get("15") else 0)
            self.setDriver("GV5", int(dps.get("16", 0)))
            self.setDriver("GV6", TIMER_TO_ISY.get(dps.get("22"), 0))

            LOGGER.debug(f"{self.name}: DPS {dps}")
            self.reportDrivers()
            return True

        except Exception as ex:
            LOGGER.error(f"{self.name}: query failed: {ex}")
            return False

    def _set(self, dps, value):
        self._worker.submit_ordered(lambda: self._set_direct(dps, value))

    def _set_direct(self, dps, value):
        try:
            result = self.device.set_value(dps, value)
            LOGGER.debug(f"{self.name}: set DPS {dps}={value}: {result}")
            self.query()
        except Exception as ex:
            LOGGER.error(f"{self.name}: command failed: {ex}")

    def fan_on(self, command):
        self._set(1, True)

    def fan_off(self, command):
        self._set(1, False)

    def set_speed(self, command):
        value = int(float(command.get("value", 1)))
        self._worker.submit_ordered(lambda: self._set_speed_direct(value))

    def _set_speed_direct(self, value):
        try:
            result = self.device.set_multiple_values({
                "1": True,
                "3": value
            })
            LOGGER.debug(f"{self.name}: set fan ON + speed {value}: {result}")
            self.query()
        except Exception as ex:
            LOGGER.error(f"{self.name}: speed command failed: {ex}")

    def set_mode(self, command):
        value = int(float(command.get("value", 0)))
        self._set(2, ISY_TO_MODE[value])

    def set_direction(self, command):
        value = int(float(command.get("value", 0)))
        self._set(8, ISY_TO_DIR[value])

    def light_on(self, command):
        self._set(15, True)

    def light_off(self, command):
        self._set(15, False)

    def set_brightness(self, command):
        value = int(float(command.get("value", 0)))
        self._set(16, value)

    def set_timer(self, command):
        value = int(float(command.get("value", 0)))
        self._set(22, ISY_TO_TIMER[value])

    def query_command(self, command):
        self._worker.submit_poll(self.query)

    commands = {
        "DON": fan_on,
        "DOF": fan_off,
        "SET_SPEED": set_speed,
        "SET_MODE": set_mode,
        "SET_DIRECTION": set_direction,
        "LIGHT_ON": light_on,
        "LIGHT_OFF": light_off,
        "SET_BRIGHTNESS": set_brightness,
        "SET_TIMER": set_timer,
        "QUERY": query_command,
    }


class TuyaPowerSwitch(udi_interface.Node):

    id = "tuyapowerswitch"

    drivers = [
        {"driver": "ST",  "value": 0, "uom": 25},
        {"driver": "GV1", "value": 0, "uom": 72},
        {"driver": "GV2", "value": 0, "uom": 1},
        {"driver": "GV3", "value": 0, "uom": 73},
        {"driver": "GV4", "value": 0, "uom": 33},
        {"driver": "GV5", "value": 0, "uom": 25},
        {"driver": "GV6", "value": 0, "uom": 25},
    ]

    def __init__(self, polyglot, primary, address, name,
                 device_id, ip, key, version="3.5"):
        super().__init__(polyglot, primary, address, name)

        self.device_id = device_id
        self.ip = ip
        self.key = key
        self.version = float(version)

        self.device = tinytuya.Device(
            self.device_id,
            self.ip,
            self.key
        )
        self.device.set_version(self.version)
        self.device.set_socketTimeout(3)
        self.device.set_socketRetryLimit(1)
        # Do not use persistent sockets for switches. Some Tuya 3.5
        # devices silently expire idle persistent connections.

        self._worker = TuyaWorker(self.name)
        self._poll_timer = None
        self._start_meter_poll()

    def _start_meter_poll(self):
        """Poll changing meter values independently of the PG3x short poll."""
        self._poll_timer = threading.Timer(30.0, self._meter_poll)
        self._poll_timer.daemon = True
        self._poll_timer.start()

    def _meter_poll(self):
        try:
            self._worker.submit_poll(self.query)
        finally:
            self._start_meter_poll()

    def query(self, command=None):
        try:
            result = self.device.status()

            if "dps" not in result:
                LOGGER.error(f"{self.name}: bad status response: {result}")
                return False

            dps = result["dps"]

            if "1" in dps:
                self.setDriver("ST", 1 if dps["1"] else 0)

            if "20" in dps:
                self.setDriver("GV1", float(dps["20"]) / 10.0)

            if "18" in dps:
                self.setDriver("GV2", float(dps["18"]) / 1000.0)

            if "19" in dps:
                self.setDriver("GV3", float(dps["19"]) / 10.0)

            if "17" in dps:
                self.setDriver("GV4", float(dps["17"]) / 1000.0)

            if "26" in dps:
                self.setDriver("GV5", 0 if int(dps["26"]) == 0 else 1)

            if "66" in dps:
                self.setDriver("GV6", 1 if dps["66"] == "online" else 0)

            LOGGER.debug(f"{self.name}: DPS {dps}")
            return True

        except Exception as ex:
            LOGGER.error(f"{self.name}: query failed: {ex}")
            return False

    def _set(self, value):
        try:
            result = self.device.set_value(1, value)
            LOGGER.debug(f"{self.name}: set relay={value}: {result}")

            # Confirm the actual relay state rather than assuming the
            # requested command succeeded. Metering values are refreshed
            # independently by the 30-second meter poll.
            self.query()

        except Exception as ex:
            LOGGER.error(f"{self.name}: command failed: {ex}")

    def switch_on(self, command):
        self._worker.submit(lambda: self._set(True))

    def switch_off(self, command):
        self._worker.submit(lambda: self._set(False))

    def query_command(self, command):
        self._worker.submit_poll(self.query)

    commands = {
        "DON": switch_on,
        "DOF": switch_off,
        "QUERY": query_command,
    }


class TuyaOutlet(udi_interface.Node):

    id = "tuyaoutlet"

    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
    ]

    def __init__(self, polyglot, primary, address, name,
                 device_id, ip, key, version="3.5"):
        super().__init__(polyglot, primary, address, name)

        self.device_id = device_id
        self.ip = ip
        self.key = key
        self.version = float(version)

        self.device = tinytuya.Device(
            self.device_id,
            self.ip,
            self.key
        )
        self.device.set_version(self.version)
        self.device.set_socketTimeout(3)
        self.device.set_socketRetryLimit(1)

        # Do not use persistent sockets. Some Tuya 3.5 devices
        # silently expire idle persistent connections.

        self._worker = TuyaWorker(self.name)
        self._poll_timer = None
        self._start_outlet_poll()

    def _start_outlet_poll(self):
        """Poll outlet state independently of the PG3x short poll."""
        self._poll_timer = threading.Timer(30.0, self._outlet_poll)
        self._poll_timer.daemon = True
        self._poll_timer.start()

    def _outlet_poll(self):
        try:
            self._worker.submit_poll(lambda: self.query())
        finally:
            self._start_outlet_poll()

    def query(self, command=None):
        try:
            result = self.device.status()

            if "dps" not in result:
                LOGGER.error(f"{self.name}: bad status response: {result}")
                return False

            dps = result["dps"]

            if "1" in dps:
                self.setDriver("ST", 1 if dps["1"] else 0)

            LOGGER.debug(f"{self.name}: DPS {dps}")
            return True

        except Exception as ex:
            LOGGER.error(f"{self.name}: query failed: {ex}")
            return False

    def _set(self, value):
        try:
            result = self.device.set_value(1, value)
            LOGGER.debug(f"{self.name}: set relay={value}: {result}")

            # Confirm the actual relay state rather than assuming
            # the requested command succeeded.
            self.query()

        except Exception as ex:
            LOGGER.error(f"{self.name}: command failed: {ex}")

    def switch_on(self, command):
        self._worker.submit(lambda: self._set(True))

    def switch_off(self, command):
        self._worker.submit(lambda: self._set(False))

    def query_command(self, command):
        self._worker.submit_poll(self.query)

    commands = {
        "DON": switch_on,
        "DOF": switch_off,
        "QUERY": query_command,
    }


class TuyaDehumidifier(udi_interface.Node):
    id = "tuyadehumidifier"
    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
        {"driver": "GV1", "value": 50, "uom": 51},
        {"driver": "GV2", "value": 0, "uom": 51},
        {"driver": "GV3", "value": 0, "uom": 4},
        {"driver": "GV4", "value": 0, "uom": 25},
        {"driver": "GV5", "value": 0, "uom": 25},
        {"driver": "GV6", "value": 0, "uom": 25},
        {"driver": "GV7", "value": 0, "uom": 25},
        {"driver": "GV8", "value": 0, "uom": 56},
        {"driver": "GV9", "value": 0, "uom": 51},
        {"driver": "GV10", "value": 0, "uom": 25},
        {"driver": "GV11", "value": 0, "uom": 25},
        {"driver": "GV12", "value": 0, "uom": 25},
        {"driver": "GV13", "value": 0, "uom": 25},
        {"driver": "GV14", "value": 0, "uom": 25},
        {"driver": "GV15", "value": 0, "uom": 25},
        {"driver": "GV16", "value": 0, "uom": 25},
        {"driver": "GV17", "value": 0, "uom": 25},
        {"driver": "GV18", "value": 0, "uom": 25},
    ]
    SPEEDS = {"low": 0, "high": 1}
    TIMERS = {"cancel": 0, "1h": 1, "2h": 2, "3h": 3}
    UNITS = {"c": 0, "f": 1}

    def __init__(self, polyglot, primary, address, name, device_id, ip, key, version="3.5"):
        super().__init__(polyglot, primary, address, name)
        self.device_id, self.ip, self.key = device_id, ip, key
        self.version = float(version)
        self.device = tinytuya.Device(device_id, ip, key)
        self.device.set_version(self.version)
        self.device.set_socketTimeout(3)
        self.device.set_socketRetryLimit(1)
        self._worker = TuyaWorker(self.name)
        # Nonpersistent sockets are safer with devices that expire idle sessions.

    def query(self, command=None):
        try:
            result = self.device.status()
            if not isinstance(result, dict) or not isinstance(result.get("dps"), dict):
                LOGGER.error(f"{self.name}: bad status response: {result}")
                return False
            d = result["dps"]
            mapping = (
                ("1", "ST", lambda v: int(bool(v))),
                ("2", "GV1", int),
                ("6", "GV2", int),
                ("7", "GV3", int),
                ("4", "GV4", lambda v: self.SPEEDS[v]),
                ("10", "GV5", lambda v: int(bool(v))),
                ("16", "GV6", lambda v: int(bool(v))),
                ("17", "GV7", lambda v: self.TIMERS[v]),
                ("19", "GV8", int),
                ("23", "GV9", int),
                ("24", "GV10", lambda v: self.UNITS[v]),
            )
            for dp, driver, converter in mapping:
                if dp in d:
                    try:
                        self.setDriver(driver, converter(d[dp]))
                    except (ValueError, TypeError, KeyError) as ex:
                        LOGGER.warning(f"{self.name}: invalid DPS {dp} value {d[dp]!r}: {ex}")
            if "19" in d:
                try:
                    bitmap = int(d["19"])
                    for bit in range(8):
                        self.setDriver(
                            f"GV{11 + bit}",
                            int(bool(bitmap & (1 << bit)))
                        )
                except (ValueError, TypeError) as ex:
                    LOGGER.warning(
                        f"{self.name}: invalid fault bitmap {d['19']!r}: {ex}"
                    )
            LOGGER.debug(f"{self.name}: DPS {d}")
            return True
        except Exception as ex:
            LOGGER.error(f"{self.name}: query failed: {ex}")
            return False

    def _set(self, dp, value):
        self._worker.submit_ordered(lambda: self._set_direct(dp, value))

    def _set_direct(self, dp, value):
        self._worker.submit_ordered(lambda: self._set_direct(dp, value))

    def _set_direct(self, dp, value):
        try:
            result = self.device.set_value(dp, value)
            LOGGER.debug(f"{self.name}: set DPS {dp}={value}: {result}")
            if isinstance(result, dict) and result.get("Error"):
                LOGGER.error(f"{self.name}: device rejected DPS {dp}: {result}")
                return
            self.query()
        except Exception as ex:
            LOGGER.error(f"{self.name}: command failed: {ex}")

    @staticmethod
    def _value(command):
        return int(float(command["value"]))

    def power_on(self, command): self._set(1, True)
    def power_off(self, command): self._set(1, False)

    def set_humidity(self, command):
        value = self._value(command)
        if 30 <= value <= 80 and value % 5 == 0:
            self._set(2, value)
        else:
            LOGGER.error(f"{self.name}: invalid target humidity {value}")

    def set_speed(self, command): self._set(4, {0: "low", 1: "high"}[self._value(command)])
    def set_anion(self, command): self._set(10, bool(self._value(command)))
    def set_lock(self, command): self._set(16, bool(self._value(command)))
    def set_timer(self, command): self._set(17, {v: k for k, v in self.TIMERS.items()}[self._value(command)])
    def set_unit(self, command): self._set(24, {v: k for k, v in self.UNITS.items()}[self._value(command)])
    def reset_filter(self, command): self._set(20, True)
    def reset_runtime(self, command): self._set(28, True)

    def query_command(self, command):
        self._worker.submit_poll(self.query)

    commands = {
        "DON": power_on, "DOF": power_off,
        "SET_HUMIDITY": set_humidity, "SET_DH_SPEED": set_speed,
        "SET_ANION": set_anion, "SET_LOCK": set_lock,
        "SET_DH_TIMER": set_timer, "SET_TEMP_UNIT": set_unit,
        "RESET_FILTER": reset_filter, "RESET_RUNTIME": reset_runtime,
        "QUERY": query_command,
    }


class Controller(udi_interface.Node):

    id = "tuyafanctrl"

    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
    ]

    def __init__(self, polyglot):
        super().__init__(
            polyglot,
            "controller",
            "controller",
            "Smart Life / Tuya Controller",
        )

        self.poly = polyglot
        self.fans = []
        self.switches = []
        self.outlets = []
        self.dehumidifiers = []
        self.params = {}

    def configure(self, params):
        self.params = {
            str(key).strip(): value
            for key, value in dict(params).items()
            if str(key).strip()
        }
        LOGGER.info("Smart Life / Tuya configuration updated; restart required to apply changes")

    def start(self):
        try:
            fan_configs = []

            # Prefer PG3x Custom Parameters.
            for num in range(1, 17):
                prefix = f"fan{num}_"

                name = self.params.get(prefix + "name")
                device_id = self.params.get(prefix + "id")
                ip = self.params.get(prefix + "ip")
                key = self.params.get(prefix + "key")
                version = self.params.get(prefix + "version", "3.4")

                # Trim ordinary text fields. Do not modify the Tuya local key.
                if isinstance(name, str):
                    name = name.strip()
                if isinstance(device_id, str):
                    device_id = device_id.strip()
                if isinstance(ip, str):
                    ip = ip.strip()
                if isinstance(version, str):
                    version = version.strip()

                values = (name, device_id, ip, key)

                if any(values) and not all(values):
                    LOGGER.warning(
                        "Incomplete configuration for fan%d; "
                        "name, id, ip and key are required",
                        num
                    )
                    continue

                if all(values):
                    fan_configs.append({
                        "name": name,
                        "address": f"fan{num}",
                        "id": device_id,
                        "ip": ip,
                        "key": key,
                        "version": version or "3.4",
                    })

            switch_configs = []

            for num in range(1, 17):
                prefix = f"switch{num}_"

                name = self.params.get(prefix + "name")
                device_id = self.params.get(prefix + "id")
                ip = self.params.get(prefix + "ip")
                key = self.params.get(prefix + "key")
                version = self.params.get(prefix + "version", "3.5")

                # Trim ordinary text fields. Do not modify the Tuya local key.
                if isinstance(name, str):
                    name = name.strip()
                if isinstance(device_id, str):
                    device_id = device_id.strip()
                if isinstance(ip, str):
                    ip = ip.strip()
                if isinstance(version, str):
                    version = version.strip()

                values = (name, device_id, ip, key)

                if any(values) and not all(values):
                    LOGGER.warning(
                        "Incomplete configuration for switch%d; "
                        "name, id, ip and key are required",
                        num
                    )
                    continue

                if all(values):
                    switch_configs.append({
                        "name": name,
                        "address": f"switch{num}",
                        "id": device_id,
                        "ip": ip,
                        "key": key,
                        "version": version or "3.5",
                    })

            outlet_configs = []

            for num in range(1, 17):
                prefix = f"outlet{num}_"

                name = self.params.get(prefix + "name")
                device_id = self.params.get(prefix + "id")
                ip = self.params.get(prefix + "ip")
                key = self.params.get(prefix + "key")
                version = self.params.get(prefix + "version", "3.5")

                # Trim ordinary text fields. Do not modify the Tuya local key.
                if isinstance(name, str):
                    name = name.strip()
                if isinstance(device_id, str):
                    device_id = device_id.strip()
                if isinstance(ip, str):
                    ip = ip.strip()
                if isinstance(version, str):
                    version = version.strip()

                values = (name, device_id, ip, key)

                if any(values) and not all(values):
                    LOGGER.warning(
                        "Incomplete configuration for outlet%d; "
                        "name, id, ip and key are required",
                        num
                    )
                    continue

                if all(values):
                    outlet_configs.append({
                        "name": name,
                        "address": f"outlet{num}",
                        "id": device_id,
                        "ip": ip,
                        "key": key,
                        "version": version or "3.5",
                    })

            dehumidifier_configs = []
            for num in range(1, 17):
                prefix = f"dehumidifier{num}_"
                name = self.params.get(prefix + "name")
                device_id = self.params.get(prefix + "id")
                ip = self.params.get(prefix + "ip")
                key = self.params.get(prefix + "key")
                version = self.params.get(prefix + "version", "3.5")
                if isinstance(name, str): name = name.strip()
                if isinstance(device_id, str): device_id = device_id.strip()
                if isinstance(ip, str): ip = ip.strip()
                if isinstance(version, str): version = version.strip()
                values = (name, device_id, ip, key)
                if any(values) and not all(values):
                    LOGGER.warning("Incomplete configuration for dehumidifier%d", num)
                    continue
                if all(values):
                    dehumidifier_configs.append({
                        "name": name, "address": f"dehumidifier{num}",
                        "id": device_id, "ip": ip, "key": key,
                        "version": version or "3.5",
                    })


            # Merge devices saved by the discovery web interface.
            # PG3x Custom Parameters take precedence.
            config_lists = {
                "fan": fan_configs,
                "switch": switch_configs,
                "outlet": outlet_configs,
                "dehumidifier": dehumidifier_configs,
            }

            json_file = Path(__file__).resolve().parent / "tuya_devices.json"

            try:
                if json_file.exists():
                    data = json.loads(json_file.read_text())
                    if not isinstance(data, dict) or not isinstance(
                        data.get("devices"), list
                    ):
                        raise ValueError("Invalid device configuration format")

                    existing_ids = {
                        str(c["id"])
                        for configs in config_lists.values()
                        for c in configs
                    }

                    for device in data["devices"]:
                        try:
                            if not isinstance(device, dict):
                                raise ValueError("Device entry must be an object")

                            device_type = device.get("type")
                            if device_type not in config_lists:
                                raise ValueError("Unsupported device type")

                            device_id = str(device.get("id") or "").strip()
                            name = str(device.get("name") or "").strip()
                            ip = str(device.get("ip") or "").strip()
                            key = device.get("key")
                            version = str(device.get("version") or "").strip()

                            if not all((device_id, name, ip, key, version)):
                                raise ValueError("Incomplete device entry")

                            if device_id in existing_ids:
                                LOGGER.info(
                                    "Skipping already configured Tuya device %s",
                                    name
                                )
                                continue

                            configs = config_lists[device_type]
                            used_addresses = {
                                c["address"] for c in configs
                            }

                            address = device.get("address")
                            if not isinstance(address, str):
                                raise ValueError("Missing permanent IoX address")

                            valid_addresses = {
                                f"{device_type}{n}" for n in range(1, 17)
                            }
                            if address not in valid_addresses:
                                raise ValueError("Invalid IoX address")

                            if address in used_addresses:
                                LOGGER.warning(
                                    "IoX address %s already occupied; skipping %s",
                                    address, name
                                )
                                continue

                            configs.append({
                                "name": name,
                                "address": address,
                                "id": device_id,
                                "ip": ip,
                                "key": key,
                                "version": version,
                            })

                            existing_ids.add(device_id)

                            LOGGER.info(
                                "Added %s from discovery configuration: %s",
                                device_type, name
                            )

                        except Exception as ex:
                            LOGGER.warning(
                                "Skipping invalid discovery device: %s", ex
                            )

            except Exception as ex:
                LOGGER.error(
                    "Could not load discovery device configuration: %s", ex
                )

            # Apply replacement credentials without changing IoX node identity.
            replacements_file = (
                Path(__file__).resolve().parent / "tuya_replacements.json"
            )

            if replacements_file.exists():
                try:
                    replacements = json.loads(replacements_file.read_text())
                    entries = replacements["replacements"]
                    if not isinstance(entries, list):
                        raise ValueError("Invalid replacements list")

                    valid_types = set(config_lists)
                    addresses = {}
                    for dtype, configs in config_lists.items():
                        for config in configs:
                            addresses[config["address"]] = (dtype, config)

                    seen = set()
                    updates = []
                    for entry in entries:
                        dtype = entry["type"]
                        address = entry["address"]

                        if dtype not in valid_types or address not in addresses:
                            raise ValueError("Unknown replacement target")
                        if addresses[address][0] != dtype:
                            raise ValueError("Replacement type mismatch")
                        if address in seen:
                            raise ValueError("Duplicate replacement address")
                        seen.add(address)

                        fields = ("id", "ip", "key", "version")
                        if any(
                            not isinstance(entry.get(k), str) or not entry[k]
                            for k in fields
                        ):
                            raise ValueError("Incomplete replacement credentials")

                        updates.append((addresses[address][1], entry))

                    final_ids = {
                        config["address"]: config["id"]
                        for configs in config_lists.values()
                        for config in configs
                    }
                    for config, entry in updates:
                        final_ids[config["address"]] = entry["id"]
                    if len(final_ids.values()) != len(set(final_ids.values())):
                        raise ValueError("Duplicate Tuya device ID")

                    for config, entry in updates:
                        for field in fields:
                            config[field] = entry[field]

                    LOGGER.info(
                        "Applied %d Tuya device replacements", len(updates)
                    )

                except Exception:
                    LOGGER.exception(
                        "Replacement configuration invalid; using original settings"
                    )

            if not fan_configs and not switch_configs and not outlet_configs and not dehumidifier_configs:
                LOGGER.warning(
                    "No complete Tuya device configuration found in Custom Parameters"
                )

                self.poly.Notices["setup"] = (
                    "Smart Life / Tuya setup required. Configure fan1_* for "
                    "ceiling fans, switch1_* for power-monitoring switches, or "
                    "outlet1_* for simple On/Off outlets, or dehumidifier1_* "
                    "for dehumidifiers. Each device requires "
                    "name, id, ip, key, and version. Use fan2_*, switch2_*, or "
                    "outlet2_* for additional devices. Restart the plugin after "
                    "saving changes. See Documentation for instructions on "
                    "obtaining the Tuya Device ID and Local Key."
                )

                self.setDriver("ST", 0)
                return

            self.poly.Notices.delete("setup")

            for config in fan_configs:
                try:
                    fan = TuyaFan(
                        self.poly,
                        "controller",
                        config["address"],
                        config["name"],
                        config["id"],
                        config["ip"],
                        config["key"],
                        config["version"],
                    )

                    self.poly.addNode(fan)
                    self.fans.append(fan)

                    fan._worker.submit_poll(fan.query)

                    LOGGER.info(
                        "%s initialized successfully",
                        config["name"]
                    )


                    # Give PG3x/IoX time to finish registering this node
                    # before submitting the next child node.
                    time.sleep(1)

                except Exception:
                    LOGGER.exception(
                        "Failed to initialize %s",
                        config["name"]
                    )

            for config in switch_configs:
                try:
                    switch = TuyaPowerSwitch(
                        self.poly,
                        "controller",
                        config["address"],
                        config["name"],
                        config["id"],
                        config["ip"],
                        config["key"],
                        config["version"],
                    )

                    self.poly.addNode(switch)
                    self.switches.append(switch)

                    switch._worker.submit_poll(switch.query)

                    LOGGER.info(
                        "%s initialized successfully",
                        config["name"]
                    )


                    time.sleep(1)

                except Exception:
                    LOGGER.exception(
                        "Failed to initialize %s",
                        config["name"]
                    )

            for config in outlet_configs:
                try:
                    outlet = TuyaOutlet(
                        self.poly,
                        "controller",
                        config["address"],
                        config["name"],
                        config["id"],
                        config["ip"],
                        config["key"],
                        config["version"],
                    )

                    self.poly.addNode(outlet)
                    self.outlets.append(outlet)

                    outlet._worker.submit_poll(outlet.query)

                    LOGGER.info(
                        "%s initialized successfully",
                        config["name"]
                    )


                    time.sleep(1)

                except Exception:
                    LOGGER.exception(
                        "Failed to initialize %s",
                        config["name"]
                    )

            for config in dehumidifier_configs:
                try:
                    node = TuyaDehumidifier(
                        self.poly, "controller", config["address"], config["name"],
                        config["id"], config["ip"], config["key"], config["version"]
                    )
                    self.poly.addNode(node)
                    self.dehumidifiers.append(node)
                    node._worker.submit_poll(node.query)
                    LOGGER.info("%s dehumidifier initialized", config["name"])
                    time.sleep(1)
                except Exception:
                    LOGGER.exception("Failed to initialize %s", config["name"])

            try:
                # Publish a key-free inventory for the discovery web interface.
                inventory = []
                for device_type, configs in config_lists.items():
                    for config in configs:
                        inventory.append({
                            "type": device_type,
                            "name": config["name"],
                            "id": config["id"],
                            "address": config["address"],
                        })

                inventory_file = Path(__file__).resolve().parent / "tuya_inventory.json"
                temp_file = inventory_file.with_suffix(".tmp")
                temp_file.write_text(json.dumps({"devices": inventory}, indent=2))
                os.chmod(temp_file, 0o600)
                temp_file.replace(inventory_file)

                LOGGER.info("Published inventory of %d configured devices", len(inventory))
            except Exception:
                LOGGER.exception("Could not publish device inventory")

            self.setDriver("ST", 1)

        except Exception as ex:
            LOGGER.error(f"Controller start failed: {ex}")
            self.setDriver("ST", 0)

    def query(self, command=None):
        for fan in self.fans:
            try:
                fan._worker.submit_poll(fan.query)
            except Exception:
                LOGGER.exception("Failed to query %s", fan.name)

        for switch in self.switches:
            try:
                switch._worker.submit_poll(switch.query)
            except Exception:
                LOGGER.exception("Failed to query %s", switch.name)

        for outlet in self.outlets:
            try:
                outlet._worker.submit_poll(outlet.query)
            except Exception:
                LOGGER.exception("Failed to query %s", outlet.name)

        for node in self.dehumidifiers:
            try:
                node._worker.submit_poll(node.query)
            except Exception:
                LOGGER.exception("Failed to query %s", node.name)

    commands = {
        "QUERY": query,
    }




controller = None
pending_params = {}

pending_deletions = {}
pending_deletions_lock = threading.Lock()


def delete_node_done(result):
    if not isinstance(result, dict):
        return

    address = result.get("address")
    if not isinstance(address, str):
        return

    with pending_deletions_lock:
        event = pending_deletions.get(address)

    if event is not None:
        event.set()


def custom_request_handler(request):
    if not isinstance(request, dict):
        return

    request_id = request.get("requestId")
    payload = request.get("payload")

    if not isinstance(request_id, str) or not isinstance(payload, dict):
        return

    if payload.get("action") == "restart_ns":
        LOGGER.info(
            "Restart requested for this node server "
            "(UUID=%s, slot=%s)",
            polyglot.uuid, polyglot.profileNum
        )

        polyglot.customResponse(
            request_id,
            {"restarting": True, "profileNum": polyglot.profileNum}
        )

        polyglot.send({"restart": {}}, "system")
        return

    if payload.get("action") != "delete_node":
        polyglot.customResponseError(
            request_id, errorMessage="Unsupported request", status=400
        )
        return

    address = payload.get("address")
    valid_types = ("fan", "switch", "outlet", "dehumidifier")

    if not isinstance(address, str) or not any(
        address == f"{device_type}{n}"
        for device_type in valid_types
        for n in range(1, 17)
    ):
        polyglot.customResponseError(
            request_id, errorMessage="Invalid node address", status=400
        )
        return

    if address not in polyglot.nodes_internal:
        polyglot.customResponseError(
            request_id, errorMessage="Node not found", status=404
        )
        return

    event = threading.Event()

    with pending_deletions_lock:
        if address in pending_deletions:
            polyglot.customResponseError(
                request_id, errorMessage="Deletion already in progress",
                status=409
            )
            return
        pending_deletions[address] = event

    try:
        polyglot.delNode(address)

        if not event.wait(20):
            polyglot.customResponseError(
                request_id,
                errorMessage="Timed out waiting for IoX node deletion",
                status=504
            )
            return

        # Update the web-interface inventory after confirmed IoX deletion.
        inventory_file = Path(__file__).resolve().parent / "tuya_inventory.json"
        inventory = json.loads(inventory_file.read_text())
        devices = inventory.get("devices")

        if not isinstance(devices, list):
            raise ValueError("Invalid Tuya inventory")

        remaining = [
            device for device in devices
            if device.get("address") != address
        ]

        if len(remaining) == len(devices):
            raise ValueError(f"{address} missing from inventory")

        inventory["devices"] = remaining

        temp_file = inventory_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(inventory, indent=2))
        os.chmod(temp_file, 0o600)
        temp_file.replace(inventory_file)

        LOGGER.info("Removed %s from Tuya inventory", address)

        polyglot.customResponse(
            request_id, {"address": address, "deleted": True}
        )

    except Exception as ex:
        LOGGER.exception("Failed to delete node %s", address)
        polyglot.customResponseError(
            request_id, errorMessage="Node deletion failed", status=500
        )
    finally:
        with pending_deletions_lock:
            pending_deletions.pop(address, None)


def custom_params_handler(params):
    global pending_params

    LOGGER.info("Received custom parameters")
    pending_params = dict(params)

    if controller is not None:
        controller.configure(pending_params)



def poll_handler(poll_type):
    if poll_type != "shortPoll":
        return

    if controller is None:
        return

    try:
        controller.query()
    except Exception as ex:
        LOGGER.error(f"Poll failed: {ex}")


def stop_handler():
    LOGGER.info("Smart Life / Tuya plugin stopping")
    polyglot.stop()


if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])

        # Publish this instance's PG3x identity for the web interface.
        identity_file = Path(__file__).resolve().parent / "tuya_identity.json"
        identity = {
            "uuid": polyglot.uuid,
            "profileNum": str(polyglot.profileNum)
        }
        temp_file = identity_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(identity))
        os.chmod(temp_file, 0o600)
        temp_file.replace(identity_file)

        LOGGER.info(
            "Published web interface identity: UUID=%s, slot=%s",
            polyglot.uuid, polyglot.profileNum
        )

        polyglot.start("1.3.3")

        polyglot.subscribe(
            polyglot.CUSTOMPARAMS,
            custom_params_handler
        )

        polyglot.subscribe(
            polyglot.POLL,
            poll_handler
        )

        polyglot.subscribe(
            polyglot.STOP,
            stop_handler
        )

        polyglot.subscribe(
            polyglot.CUSTOMREQUEST,
            custom_request_handler
        )

        polyglot.subscribe(
            polyglot.DELNODEDONE,
            delete_node_done
        )

        polyglot.ready()
        polyglot.updateProfile()

        controller = Controller(polyglot)
        controller.configure(pending_params)
        polyglot.addNode(controller)

        time.sleep(1)

        controller.start()

        polyglot.runForever()

    except (KeyboardInterrupt, SystemExit):
        pass

    except Exception:
        LOGGER.exception("Unhandled exception")
