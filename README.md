# Smart Life / Tuya Control PG3x Plugin

Local LAN control of compatible Smart Life and Tuya Wi-Fi devices from Universal Devices eisy / PG3x.

Many devices sold for use with the **Smart Life** app are based on the Tuya platform even when the product, packaging, or instructions do not mention Tuya. This plugin supports compatible devices from either the Smart Life or Tuya Smart ecosystem.

The plugin uses TinyTuya for direct local communication with supported devices. Tuya cloud access is needed to obtain the Device ID and Local Key during setup, but normal plugin operation is over the local LAN.

## Features

### Ceiling fans

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

### Power-monitoring switches

Supported switch controls and measurements:

- Switch On / Off
- Voltage
- Current
- Power
- Accumulated energy
- Fault status
- Online status

The plugin currently supports up to 16 fans and 16 power switches.

## Configuration

Devices are configured using PG3x Custom Parameters.

### Ceiling fans

For fan 1:

- `fan1_name`
- `fan1_id`
- `fan1_ip`
- `fan1_key`
- `fan1_version`

For additional fans use `fan2_*`, `fan3_*`, etc., through `fan16_*`.

The tested fan controller uses Tuya protocol version `3.4`.

### Power-monitoring switches

For switch 1:

- `switch1_name`
- `switch1_id`
- `switch1_ip`
- `switch1_key`
- `switch1_version`

For additional switches use `switch2_*`, `switch3_*`, etc., through `switch16_*`.

The tested Smart Life power-monitoring switch uses Tuya protocol version `3.5`.

### Parameter meanings

`name`
: Display name shown in IoX.

`id`
: Tuya Device ID.

`ip`
: Local IP address of the device.

`key`
: Tuya Local Key.

`version`
: Tuya local protocol version.

Only complete device entries are loaded. Each configured device requires `name`, `id`, `ip`, and `key`.

After changing Custom Parameters, restart the plugin to apply the new configuration.

## Tested Hardware

### Ceiling fan

Tested with a Tuya-based ceiling fan controller:

- Model: FC86B5-5D
- Manufacturer: Shenzhen Funpower General Technology Co., Ltd.
- Tuya protocol: 3.4

Fan DPS mapping:

| DPS | Function |
|---|---|
| 1 | Fan power |
| 2 | Fan mode |
| 3 | Fan speed |
| 8 | Direction |
| 15 | Light power |
| 16 | Light brightness |
| 22 | Stop timer |

Expected fan values:

- Mode: `normal`, `sleep`, `nature`
- Speed: `1` through `6`
- Direction: `forward`, `reverse`
- Timer: `off`, `1hour`, `2hour`, `4hour`, `8hour`

Other ceiling fan controllers may work if they use the same DPS mapping.

### Smart Life power-monitoring switch

Tested with a Smart Life Wi-Fi power-monitoring switch using Tuya protocol 3.5.

Switch DPS mapping:

| DPS | Function |
|---|---|
| 1 | Relay power |
| 17 | Accumulated energy |
| 18 | Current |
| 19 | Power |
| 20 | Voltage |
| 26 | Fault status |
| 66 | Online status |

The tested device reports:

- Energy in thousandths of kWh
- Current in mA
- Power in tenths of a watt
- Voltage in tenths of a volt

The plugin converts these values for display in IoX as kWh, A, W, and V.

Other Smart Life / Tuya power-monitoring switches may work if they use the same DPS mapping.

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

Current version: 1.2.0

## Obtaining Your Smart Life / Tuya Device Information

Each device requires five Custom Parameters. Use the `fan1_*` prefix for
a supported ceiling fan or the `switch1_*` prefix for a supported
power-monitoring switch.

The Device ID and Local Key can be obtained using the TinyTuya setup
wizard. The Tuya cloud is only needed to obtain this information.
Normal operation of the plugin is entirely over the local LAN.

### 1. Pair the Device

The device must first be paired with the Smart Life or Tuya Smart mobile
app.

A product may be advertised only as a **Smart Life** device and may not
mention Tuya. Smart Life devices commonly use the Tuya platform and can
be compatible with this plugin if their local protocol and DPS mapping
are supported.

Make sure the device is working from the mobile app before continuing.

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

### 3. Link Your Smart Life or Tuya Smart App Account

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

When complete, it creates a `devices.json` file in the directory from
which the wizard was run.

This file contains the device information and Local Keys needed by the
plugin. Treat it as a credential file and do not commit or publish it.

### 5. Display the Device Information

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

Find the device you want to configure.

For a ceiling fan, copy its information into:

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

Continue with `fan3_*`, `fan4_*`, etc. for additional fans.

For a power-monitoring switch use:

    switch1_name
    switch1_id
    switch1_ip
    switch1_key
    switch1_version

For additional switches use `switch2_*`, `switch3_*`, etc.

After entering or changing the Custom Parameters, save the changes and
restart the plugin.

### Important Notes

The `fan*_key` and `switch*_key` values are security credentials. Keep
your Tuya Local Keys private and do not post them in logs, screenshots,
support requests, or public repositories.

It is recommended that each device be assigned a DHCP reservation so
its local IP address does not change.

If a Tuya device is reset or removed and re-paired with the mobile app,
its Local Key may change. Run the TinyTuya wizard again to obtain the
new key.

TinyTuya and Tuya are third-party projects/services and their setup
procedures may change over time.
