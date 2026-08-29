# Tuya Fan PG3x Plugin

Local LAN control of compatible Tuya ceiling fan controllers from Universal Devices eisy / PG3x.

This plugin uses TinyTuya for direct local communication with the fan controller. Tuya cloud access is not required during normal operation once the device ID and local key are known.

## Features

Supported fan controls:

- Fan On / Off
- Fan speed 1 through 6
- Normal / Sleep / Natural mode
- Forward / Reverse direction
- Light On / Off
- Light brightness 0 through 100%
- Stop timer:
  - Off
  - 1 Hour
  - 2 Hours
  - 4 Hours
  - 8 Hours

The plugin supports up to 16 fans.

## Configuration

Each fan is configured using PG3x Custom Parameters.

For fan 1:

- `fan1_name`
- `fan1_id`
- `fan1_ip`
- `fan1_key`
- `fan1_version`

For fan 2:

- `fan2_name`
- `fan2_id`
- `fan2_ip`
- `fan2_key`
- `fan2_version`

Continue the same pattern through:

- `fan16_name`
- `fan16_id`
- `fan16_ip`
- `fan16_key`
- `fan16_version`

### Parameter meanings

`name`
: Display name shown in IoX.

`id`
: Tuya device ID.

`ip`
: Local IP address of the fan controller.

`key`
: Tuya local key.

`version`
: Tuya protocol version. The tested controllers use `3.4`.

Only complete fan entries are loaded. A fan requires at least `name`, `id`, `ip`, and `key`.

After changing Custom Parameters, restart the plugin to apply the new configuration.

## Tested Hardware

Tested with a Tuya-based ceiling fan controller:

- Model: FC86B5-5D
- Manufacturer: Shenzhen Funpower General Technology Co., Ltd.
- Tuya protocol: 3.4

Other Tuya ceiling fan controllers may work if they use the same DPS mapping.

## DPS Mapping

| DPS | Function |
|---|---|
| 1 | Fan power |
| 2 | Fan mode |
| 3 | Fan speed |
| 8 | Direction |
| 15 | Light power |
| 16 | Light brightness |
| 22 | Stop timer |

Expected values:

- Mode: `normal`, `sleep`, `nature`
- Speed: `1` through `6`
- Direction: `forward`, `reverse`
- Timer: `off`, `1hour`, `2hour`, `4hour`, `8hour`

## Requirements

- Universal Devices eisy
- PG3x
- Python 3
- `udi-interface`
- `tinytuya`

Python dependencies are installed from `requirements.txt`.

## Security

The Tuya local key is a credential. Do not publish it, commit it to Git, or include it in support logs.

Configuration is stored in PG3x Custom Parameters rather than in this repository.

## Version

Current version: 1.1.1

## Obtaining Your Tuya Device Information

Each fan requires the following five Custom Parameters:

- `fan1_name` - The name you want displayed for the fan
- `fan1_id` - Tuya Device ID
- `fan1_ip` - Local IP address of the fan controller
- `fan1_key` - Tuya Local Key
- `fan1_version` - Tuya protocol version (3.4 for the tested controller)

The Device ID and Local Key can be obtained using the TinyTuya setup
wizard. The Tuya cloud is only needed to obtain this information.
Normal operation of the plugin is entirely over the local LAN.

### 1. Pair the Fan

The fan must first be paired with a Tuya-compatible mobile app such as
Smart Life or Tuya Smart.

Make sure the fan is working from the mobile app before continuing.

### 2. Create a Tuya Developer Account

Go to:

https://iot.tuya.com/

Create a free Tuya Developer account and log in.

In the Tuya IoT Platform:

1. Select **Cloud**.
2. Select **Create Cloud Project**.
3. Create a Smart Home project.
4. Select the data center/region corresponding to the region used by
   your Smart Life or Tuya Smart account.

After creating the project, open its **Overview** page and locate:

- **Access ID / Client ID**
- **Access Secret / Client Secret**

You will need these two values when running the TinyTuya wizard.

### 3. Link Your Tuya App Account

In your Tuya Cloud project:

1. Open the **Devices** tab.
2. Select **Link Tuya App Account**.
3. Select **Add App Account**.
4. Tuya will display a QR code.
5. Open the Smart Life or Tuya Smart app on your phone.
6. Use the app's QR-code scanner to scan the code.
7. Confirm the account link.

The devices registered in your mobile app should then appear in the
Tuya Cloud project's device list.

### 4. Run the TinyTuya Wizard on eisy

SSH into your eisy and run:

    cd /home/admin
    python3 -m tinytuya wizard

The wizard will ask for information from your Tuya Cloud project,
including:

- API Key - use the **Access ID / Client ID**
- API Secret - use the **Access Secret / Client Secret**
- Region - select the region corresponding to your Tuya project
- Device ID - enter a Device ID from your project, or enter `scan`
  when offered that option

TinyTuya will retrieve the registered devices and their Local Keys.

When complete, it creates:

    /home/admin/devices.json

This file contains the information needed by the Tuya Fan plugin.

### 5. Display the Fan Information

Run:

    cd /home/admin
    python3 - <<'PY'
    import json

    with open("devices.json") as f:
        devices = json.load(f)

    for d in devices:
        print()
        print("Name:    ", d.get("name"))
        print("ID:      ", d.get("id"))
        print("IP:      ", d.get("ip"))
        print("Key:     ", d.get("key"))
        print("Version: ", d.get("version"))
    PY

Find the fan you want to configure.

Copy its information into the plugin's Custom Parameters:

    fan1_name
    fan1_id
    fan1_ip
    fan1_key
    fan1_version

For additional fans use:

    fan2_name
    fan2_id
    fan2_ip
    fan2_key
    fan2_version

Continue with `fan3_*`, `fan4_*`, etc. The plugin supports up to 16
fans.

After entering or changing the Custom Parameters, save the changes and
restart the plugin.

### Important Notes

The `fan*_key` value is a security credential. Keep your Tuya Local
Keys private and do not post them in logs, screenshots, support
requests, or public repositories.

It is recommended that each fan be assigned a DHCP reservation so its
local IP address does not change.

If a Tuya device is reset or removed and re-paired with the mobile app,
its Local Key may change. Run the TinyTuya wizard again to obtain the
new key.

TinyTuya and Tuya are third-party projects/services and their setup
procedures may change over time.
