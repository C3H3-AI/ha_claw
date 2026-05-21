# Query Tools

## GetLiveContext

Get real-time state of all exposed entities. No params.

```json
{}
```

## EntityQuery

Query single entity state. Supports fuzzy matching.

```json
{"entity_id": "客厅灯"}
{"entity_id": "light.living_room"}
```

## HistoryQuery

Query entity history.

```json
{"entity_id": "sensor.temperature", "hours": 24}
```

## GetSystemIndex

Get system structure (areas/domains/device classes/automations/scripts).

```json
{"force_refresh": false}
```

## SmartDiscovery

Smart entity discovery with filters.

| Param | Description |
|-------|-------------|
| area | Area name |
| domain | Entity domain |
| state | Current state |
| name_contains | Name filter |
| name_pattern | Regex pattern |
| device_class | Device class |
| inferred_type | Inferred type |
| person_name | Person name |
| limit | Max results |

```json
{"area": "living_room", "domain": "light"}
{"name_contains": "温度", "domain": "sensor"}
```

## AreaDevices

Get all devices in area.

```json
{"area": "客厅"}
```

## ListServices

List services for domain.

```json
{"domain": "light"}
```

## ServiceHelp

Get service help.

```json
{"domain": "light", "service": "turn_on"}
```
