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

Current version: 1.1.0
