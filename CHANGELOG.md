# Changelog

## 1.4.1

- Added verification of configured Local Keys against Tuya Cloud.
- Added confirmed repair of mismatched Local Keys without changing
  device IDs, IP addresses, names, or IoX node addresses.
- Added safeguards against missing, invalid, or conflicting Cloud keys.
- Improved LAN discovery reliability using TinyTuya's default scan settings.
- Enlarged progress indicators and improved verification results.
- Updated web configuration and Store documentation.

## 1.4.0

- Added an HTTPS web configuration interface on port 8767.
- Added first-time administrator password creation through the browser.
- Added administrator login, logout, password changes, and SSH-assisted recovery.
- Added secure password hashing, session cookies, and one-hour idle expiration.
- Added request-origin validation and protection for configuration-changing requests.
- Added automatic web-interface startup and shutdown with the PG3x node server.
- Added automatic HTTPS certificate selection based on the installed PG3x slot.
- Added cloud account management, device discovery, local-network scanning,
  device inventory, configuration management, device testing, and node-server restart.
- Added FastAPI and Uvicorn to installation requirements.

## 1.3.3

- Fixed fan status reporting compatibility with IoX 6.1.2.
- Explicitly republish fan node drivers after querying device status.
- No changes to polling intervals, socket handling, or device commands.

## 1.3.2

- Fixed offline devices blocking other Tuya devices using independent background workers.
- Added nonblocking commands, polling, and startup queries.
- Preserved ordered commands for fans and dehumidifiers.
- Reduced socket timeouts and retries.
- Tested fans and outlets, including both fans offline; other device types await testing.


## 1.3.1

- Added eight individual dehumidifier fault indicators:
  Tank Full, Clean Filter, E1 Error, Low Temperature,
  High Temperature, Low Humidity, Coil Fault, and Motor Fault.
- Decode each fault independently from DPS 19, supporting
  multiple simultaneous faults.
- Retained the original Fault Bitmap for diagnostics.
- No changes to device control commands.
- Individual fault indicators await hardware validation.

## 1.3.0
- Added Smart Life / Tuya dehumidifier support using `dehumidifier1_*` through `dehumidifier16_*` Custom Parameters.
- Added power control, target humidity adjustment, and low/high fan speed control.
- Added reporting of indoor humidity, temperature, filter life, and fault status.
- Added controls for the anion generator, child lock, countdown timer, and temperature display units.
- Added filter-life and runtime reset commands.
- Added independent dehumidifier polling and IoX node profiles.
- Tested DPS mapping and commands with simulated device responses; physical dehumidifier testing is pending.


## 1.2.1
- Added support for simple Smart Life / Tuya On/Off outlets using the `outlet1_*` through `outlet16_*` Custom Parameters.
- Added independent 30-second state polling for simple outlets.
- Added independent 30-second metering and state polling for power-monitoring switches.
- Power switches and outlets now confirm the actual relay state after On/Off commands.
- Disabled persistent TinyTuya sockets for protocol 3.5 switches and outlets to avoid stale idle connections; persistent sockets remain enabled for ceiling fans.

## 1.2.0
- Renamed the user-facing plugin to Smart Life / Tuya Control to make compatibility clearer for devices sold for use with the Smart Life app.
- Added support for Smart Life / Tuya power-monitoring switches using the `switch1_*` through `switch16_*` Custom Parameters.
- Added local relay On/Off control.
- Added voltage, current, power, accumulated energy, fault, and online status reporting.
- Added support for the tested Tuya protocol 3.5 power-monitoring switch while retaining existing protocol 3.4 ceiling fan support.
- Added persistent TinyTuya sockets to reduce repeated connection setup and investigate intermittent local-interface lockups.
- Added protection against accidentally committing TinyTuya credential and discovery files.

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
