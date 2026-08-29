#!/usr/bin/env python3

import time
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
            return True

        except Exception as ex:
            LOGGER.error(f"{self.name}: query failed: {ex}")
            return False

    def _set(self, dps, value):
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
        self._set(3, value)

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
        "QUERY": query,
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
            "Tuya Fan Controller",
        )

        self.poly = polyglot
        self.fans = []
        self.params = {}

    def configure(self, params):
        self.params = {
            str(key).strip(): value
            for key, value in dict(params).items()
            if str(key).strip()
        }
        LOGGER.info("Tuya Fan configuration updated; restart required to apply changes")

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

            if not fan_configs:
                LOGGER.warning(
                    "No complete Tuya fan configuration found in Custom Parameters"
                )

                self.poly.Notices["setup"] = (
                    "Tuya Fan setup required. Complete the fan1_name, fan1_id, "
                    "fan1_ip, fan1_key, and fan1_version Custom Parameters below. "
                    "Use fan2_*, fan3_*, etc. for additional fans, up to fan16_*. "
                    "The tested Tuya protocol version is 3.4. Restart the plugin "
                    "after saving changes. See Documentation for instructions on "
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

                    connected = fan.query()

                    LOGGER.info(
                        "%s initialized successfully",
                        config["name"]
                    )

                    if connected:
                        self.setDriver("ST", 1)

                    # Give PG3x/IoX time to finish registering this node
                    # before submitting the next child node.
                    time.sleep(1)

                except Exception:
                    LOGGER.exception(
                        "Failed to initialize %s",
                        config["name"]
                    )

        except Exception as ex:
            LOGGER.error(f"Controller start failed: {ex}")
            self.setDriver("ST", 0)

    def query(self, command=None):
        for fan in self.fans:
            try:
                fan.query()
            except Exception:
                LOGGER.exception("Failed to query %s", fan.name)

    commands = {
        "QUERY": query,
    }




controller = None
pending_params = {}


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
    LOGGER.info("Tuya Fan plugin stopping")
    polyglot.stop()


if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])

        polyglot.start("1.1.1")

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
