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

### Dehumidifiers

Supports compatible Smart Life / Tuya dehumidifiers using protocol 3.5 and the documented DPS mapping.

- Power On / Off
- Target humidity: 30–80% in 5% increments
- Fan speed: Low / High
- Indoor humidity and temperature reporting
- Anion generator and child lock controls
- Countdown timer: Cancel / 1 / 2 / 3 hours
- Filter life and fault status reporting
- Celsius / Fahrenheit display selection
- Filter life and runtime reset commands

**Testing status:** DPS mapping and commands have passed simulated tests. Physical dehumidifier communication has not yet been verified.

### Simple On/Off outlets

Supported outlet controls:

- Outlet On / Off
- Automatic state refresh every 30 seconds

The plugin supports up to 16 devices of each type: ceiling fans, power-monitoring switches, simple On/Off outlets, and dehumidifiers.

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

### Simple On/Off outlets

For outlet 1:

- `outlet1_name`
- `outlet1_id`
- `outlet1_ip`
- `outlet1_key`
- `outlet1_version`

For additional outlets use `outlet2_*`, `outlet3_*`, etc., through `outlet16_*`.

The tested Smart Life On/Off outlet uses Tuya protocol version `3.5`.

### Dehumidifiers

For dehumidifier 1:

- `dehumidifier1_name`
- `dehumidifier1_id`
- `dehumidifier1_ip`
- `dehumidifier1_key`
- `dehumidifier1_version`

For additional dehumidifiers use `dehumidifier2_*` through `dehumidifier16_*`.

The default Tuya protocol version is `3.5`. The `name`, `id`, `ip`, and `key` parameters are required.

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

### Smart Life simple On/Off outlet

Tested with a WP3/5 Smart Life Wi-Fi outlet using Tuya protocol 3.5.

Outlet DPS mapping:

| DPS | Function |
|---|---|
| 1 | Relay power |

The plugin provides local On/Off control and automatically refreshes the
outlet state every 30 seconds.

Other Smart Life / Tuya outlets may work if they use DPS 1 for relay power.

### Smart Life / Tuya dehumidifier (not yet hardware-tested)

The initial implementation targets a Tuya protocol 3.5 dehumidifier with the following DPS mapping, supplied by a device owner.

| DPS | Function |
|---|---|
| 1 | Power |
| 2 | Target humidity |
| 4 | Fan speed (`low`, `high`) |
| 6 | Indoor humidity |
| 7 | Indoor temperature (°C) |
| 10 | Anion generator |
| 16 | Child lock |
| 17 | Countdown (`cancel`, `1h`, `2h`, `3h`) |
| 19 | Fault bitmap |
| 20 | Filter reset |
| 23 | Filter life |
| 24 | Temperature display unit (`c`, `f`) |
| 28 | Runtime reset |

Other dehumidifiers may use different DPS mappings. Compatibility is not guaranteed.

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

Current version: 1.3.0

## Obtaining Your Smart Life / Tuya Device Information

Each device requires five Custom Parameters. Use the `fan1_*` prefix for
a supported ceiling fan, the `switch1_*` prefix for a supported
power-monitoring switch, the `outlet1_*` prefix for a supported simple On/Off outlet,
or the `dehumidifier1_*` prefix for a supported dehumidifier.

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

For a simple On/Off outlet use:

    outlet1_name
    outlet1_id
    outlet1_ip
    outlet1_key
    outlet1_version

For additional outlets use `outlet2_*`, `outlet3_*`, etc.

For a dehumidifier use `dehumidifier1_name`, `dehumidifier1_id`,
`dehumidifier1_ip`, `dehumidifier1_key`, and `dehumidifier1_version`.
Additional dehumidifiers use `dehumidifier2_*` through `dehumidifier16_*`.

After entering or changing the Custom Parameters, save the changes and
restart the plugin.

### Important Notes

The `fan*_key`, `switch*_key`, `outlet*_key`, and `dehumidifier*_key` values are security
credentials. Keep your Tuya Local Keys private and do not post them in
logs, screenshots, support requests, or public repositories.

It is recommended that each device be assigned a DHCP reservation so
its local IP address does not change.

If a Tuya device is reset or removed and re-paired with the mobile app,
its Local Key may change. Run the TinyTuya wizard again to obtain the
new key.

TinyTuya and Tuya are third-party projects/services and their setup
procedures may change over time.
