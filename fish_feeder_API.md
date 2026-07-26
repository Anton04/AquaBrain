# Fish Feeder MQTT API

This document is the integration contract for applications that visualize or
control the ESP8266 fish feeder.

## Connection

| Setting | Value |
|---|---|
| Broker | `192.168.0.143` |
| Port | `1883` |
| Authentication | None |
| TLS | No |
| MQTT QoS | `0` |
| Retained messages | No |
| Device keepalive | 20 seconds |

All device publications and commands currently use QoS 0 and
`retain=false`. A frontend must therefore not depend on retained broker state.
The existing external MQTT consumer can persist messages for later display.

## Device identity and base topic

Every feeder uses this base topic:

```text
devices/fishfeeder-XXXX/
```

`XXXX` is the final four hexadecimal characters of the ESP8266 station Wi-Fi
MAC address. The currently installed feeder is:

```text
Base topic: devices/fishfeeder-c78f/
IP address: 192.168.0.161
```

To discover feeders dynamically, subscribe to:

```text
devices/#
```

MQTT wildcards cannot match only part of a topic level, so a subscription such
as `devices/fishfeeder-+/#` is not valid for discovering arbitrary suffixes.
Subscribe to `devices/#` and filter the second topic level for values beginning
with `fishfeeder-`.

In the examples below, `{base}` means:

```text
devices/fishfeeder-c78f/
```

## Property topics

| Topic below `{base}` | Payload | Description |
|---|---|---|
| `properties/status` | Plain text | Current operational state |
| `properties/ip_address` | Plain text IPv4 | Current station IP address |
| `properties/boottime` | Integer text | Device boot time as Unix epoch seconds |
| `properties/localtime` | Plain text | Schedule-local time, `YYYY-MM-DD HH:MM:SS` |
| `properties/countdown` | Integer text or JSON `null` | Seconds until the next enabled schedule event |
| `properties/schedule.json` | JSON object | Complete active daily schedule |
| `properties/feed_counters.json` | JSON object | Persistent daily, weekly and all-time counters |
| `properties/feed_log` | JSON object | One newly completed dose event |
| `properties/mqtt.json` | JSON object | MQTT integration configuration |
| `properties/last_error` | Plain text | Most recent rejected MQTT command or validation error |

### Status

Topic:

```text
{base}properties/status
```

Possible values:

| Value | Meaning |
|---|---|
| `booting` | Application startup is in progress |
| `idle` | Feeder is ready and no servo batch is active |
| `feeding` | One or more doses are being executed |
| `restarting` | A controlled restart was requested |
| `offline` | MQTT Last Will, or a controlled restart is about to occur |

The MQTT Last Will publishes `offline` with `retain=false`. A frontend should
also consider message age because a non-retained Last Will is an event, not a
permanent broker-side snapshot.

For a multi-dose request, `feeding` is published when the batch starts and
`idle` when the complete queue has finished.

### Local time

Topic:

```text
{base}properties/localtime
```

Example:

```text
2026-07-26 18:06:27
```

It is published at MQTT connection and then once per minute. This is the time
the device uses when matching schedule entries.

The schedule currently uses a fixed UTC offset. It does not automatically
change between daylight-saving and standard time.

### Countdown

Topic:

```text
{base}properties/countdown
```

Example:

```text
10413
```

The value is the number of whole seconds until the next enabled daily schedule
event. It wraps to the next day after the final event of the current day.

- Updated once per minute normally.
- Updated once per second during the final minute.
- Published immediately after MQTT connection.
- Published immediately after a successful schedule change.
- Payload is JSON `null` if the schedule is empty or the clock is not ready.

Treat the payload as a nullable integer, not as a formatted duration. The
frontend can render it as days, hours, minutes and seconds.

### Schedule

Property topic:

```text
{base}properties/schedule.json
```

Schema:

```json
{
  "utc_offset_hours": 2,
  "feedings": [
    {
      "time_of_the_day": "14:00",
      "doses": 1,
      "enabled": true
    },
    {
      "time_of_the_day": "18:00",
      "doses": 5,
      "enabled": true
    }
  ]
}
```

Rules:

- `utc_offset_hours` must be an integer from `-12` through `14`.
- `feedings` must be an array.
- `time_of_the_day` must use 24-hour `HH:MM`.
- `doses` must be an integer from `1` through `10`.
- `enabled` is optional and defaults to `true`.
- Duplicate enabled times are rejected.
- The field name `time` is reserved for Unix timestamps.

Accepted schedule changes are published immediately on the property topic and
loaded into the active scheduler.

### Feed counters

Topic:

```text
{base}properties/feed_counters.json
```

Example:

```json
{
  "all_time": 102,
  "daily": 13,
  "weekly": 80,
  "day_epoch": 1785016800,
  "week_epoch": 1784498400,
  "updated_time": 1785081829
}
```

Counter meanings:

- `daily`: completed doses since the latest local midnight.
- `weekly`: completed doses since local Monday midnight.
- `all_time`: completed doses since counters were created or manually reset.
- `day_epoch`: Unix epoch for the start of the active local day.
- `week_epoch`: Unix epoch for the start of the active local week.
- `updated_time`: Unix epoch when the counter document was last written.

Counters increase only after a complete out-and-back servo cycle. A request
for `5` doses produces five individual increments.

### Incremental feed log

Topic:

```text
{base}properties/feed_log
```

One message is published for every completed dose:

```json
{
  "time": 1785081603,
  "doses": 1,
  "source": "schedule",
  "all_time_counter": 98,
  "daily_counter": 9,
  "weekly_counter": 76
}
```

Fields:

| Field | Type | Meaning |
|---|---|---|
| `time` | Integer | Completion time as Unix epoch seconds |
| `doses` | Integer | Completed doses represented by this event, normally `1` |
| `source` | String | `schedule`, `mqtt`, `button`, `repl`, `mixed` or `daily_reset` |
| `all_time_counter` | Integer | Counter value after this event |
| `daily_counter` | Integer | Counter value after this event |
| `weekly_counter` | Integer | Counter value after this event |

The complete local day-log file is deliberately not published over MQTT.
Only new events are published on this topic.

`daily_reset` is a zero-dose event written at local midnight:

```json
{
  "time": 1785016800,
  "doses": 0,
  "source": "daily_reset",
  "all_time_counter": 89,
  "daily_counter": 0,
  "weekly_counter": 67
}
```

### Error

Topic:

```text
{base}properties/last_error
```

The payload is readable plain text, for example:

```text
duplicate feeding time: 18:00
```

Errors are non-retained. Associate them with the most recently submitted
command in the frontend.

## Command topics

All commands are published below the plural `commands/` branch.

| Command topic below `{base}` | Payload |
|---|---|
| `commands/feed` | Integer text from `1` through `10` |
| `commands/add_feed_event` | One schedule-entry JSON object |
| `commands/clear_schedule` | Any payload |
| `commands/reset_counters` | Any payload |
| `commands/schedule/` | Complete schedule JSON document |
| `commands/restart` | Any payload |

Commands use QoS 0 and `retain=false`. Do not retain command messages, because
a retained feed or restart command could be executed after a reconnect.

### Feed now

Topic:

```text
{base}commands/feed
```

Payload for three doses:

```text
3
```

Valid values are canonical integer strings from `1` through `10`. The command
returns immediately after adding doses to the non-blocking queue.

Observe:

1. `properties/status` becomes `feeding`.
2. `properties/feed_log` publishes one completion event per dose.
3. `properties/feed_counters.json` updates per completed dose.
4. `properties/status` returns to `idle`.

### Add one schedule event

Topic:

```text
{base}commands/add_feed_event
```

Payload:

```json
{
  "time_of_the_day": "20:30",
  "doses": 2
}
```

The event is validated and appended to the existing daily schedule.
`enabled` is set to `true`. On success, the complete updated schedule is
published immediately on:

```text
{base}properties/schedule.json
```

### Replace the complete schedule

The trailing slash is part of the command topic:

```text
{base}commands/schedule/
```

Payload:

```json
{
  "utc_offset_hours": 2,
  "feedings": [
    {
      "time_of_the_day": "14:00",
      "doses": 1,
      "enabled": true
    },
    {
      "time_of_the_day": "18:00",
      "doses": 5,
      "enabled": true
    },
    {
      "time_of_the_day": "21:00",
      "doses": 5,
      "enabled": true
    }
  ]
}
```

The complete document is validated before the active file is replaced.
Invalid JSON or invalid entries leave the previous schedule active and publish
an error.

### Clear the schedule

Topic:

```text
{base}commands/clear_schedule
```

Any payload clears all daily entries while preserving `utc_offset_hours`.
Confirm success by waiting for:

```json
{
  "utc_offset_hours": 2,
  "feedings": []
}
```

on `{base}properties/schedule.json`.

### Reset counters

Topic:

```text
{base}commands/reset_counters
```

Any payload resets `daily`, `weekly` and `all_time` to zero. Historical feed
logs are retained. Confirm success through
`{base}properties/feed_counters.json`.

### Restart

Topic:

```text
{base}commands/restart
```

Any payload requests a restart. The expected status sequence is:

```text
restarting
offline
booting
idle
```

Network timing may cause an observer to see only part of this sequence.

## Command descriptions

Whenever MQTT connects, the feeder publishes short plain-text usage
instructions on:

```text
{base}commands/feed/description/text
{base}commands/add_feed_event/description/text
{base}commands/clear_schedule/description/text
{base}commands/reset_counters/description/text
{base}commands/schedule/description/text
{base}commands/restart/description/text
```

These messages are also non-retained.

## Generic `/data` publications

Files below `/data` are mapped to MQTT without the `/data` prefix:

```text
/data/name/last_msg.txt
  -> {base}name/last_msg.txt

/data/properties/schedule.json
  -> {base}properties/schedule.json
```

A file named `last_msg.txt` is additionally published on its parent-directory
topic. The current name file therefore produces:

```text
{base}name/last_msg.txt
{base}name
```

with this payload:

```json
{
  "en": "Fisk feeder",
  "sv": "Fisk mataren"
}
```

Files under the local `feed_log` directory are the exception: complete files
are not published. Only their new entries use `{base}properties/feed_log`.

## Frontend synchronization recommendations

1. Subscribe to `devices/#` before sending commands.
2. Filter device IDs beginning with `fishfeeder-`.
3. Build the device card from `status`, `ip_address`, `boottime`, `localtime`,
   `countdown`, `schedule.json` and `feed_counters.json`.
4. Store every `feed_log` event by its `time` and counter values.
5. After a schedule command, wait for a new `properties/schedule.json` message
   before showing success.
6. After a feed command, use `feeding`, incremental log events and the final
   `idle` as confirmation.
7. Show `last_error` close to the command form that caused it.
8. Treat old status values as stale even if the persisted consumer still has
   them; display the timestamp of the latest received message.
9. Do not republish persisted command messages.

## Example subscriptions and publications

Subscribe with Mosquitto:

```bash
mosquitto_sub -h 192.168.0.143 -p 1883 -t "devices/#" -v
```

Feed one dose:

```bash
mosquitto_pub -h 192.168.0.143 -p 1883 \
  -t "devices/fishfeeder-c78f/commands/feed" -m "1"
```

Add a schedule event:

```bash
mosquitto_pub -h 192.168.0.143 -p 1883 \
  -t "devices/fishfeeder-c78f/commands/add_feed_event" \
  -m '{"time_of_the_day":"20:30","doses":2}'
```

Clear the schedule:

```bash
mosquitto_pub -h 192.168.0.143 -p 1883 \
  -t "devices/fishfeeder-c78f/commands/clear_schedule" -m "clear"
```
