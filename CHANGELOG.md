# Changelog

## 1.1.4
- Fan Speed commands now send fan power ON and the requested speed in a single Tuya command, improving reliable speed changes when the fan is off.

## 1.1.3
- Fan Speed commands now automatically turn the fan on before setting the requested speed.
- Improves IoX scene support by allowing a scene to turn on a fan and set its speed with a single responder command.

## 1.1.2
- Added detailed Tuya device setup instructions, including obtaining Device IDs and Local Keys using TinyTuya.
- Changed fan nodes to use the generic controller icon.

## 1.1.1
- Added a setup notice when the plugin has not yet been configured.
- Added MIT license.

## 1.1.0
- Support for up to 16 Tuya ceiling fans
- Configuration through PG3x Custom Parameters
- Local LAN control without Tuya cloud access during normal operation
- Fan power and 6-speed control
- Normal, Sleep, and Natural operating modes
- Forward and reverse direction
- Light power and brightness control
- Stop timer control
- Improved configuration validation and connection status
