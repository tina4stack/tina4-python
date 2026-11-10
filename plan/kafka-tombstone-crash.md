# Task: Kafka tombstone (null-value) record crashes the consumer (#303)

A Kafka tombstone — a record whose value is `null` (Debezium deletes, log-compacted
delete markers) — kills the consumer. The confluent path decodes `msg.value().decode()`,
and for a tombstone `msg.value()` is `None`, so `None.decode()` raises `AttributeError`,
which is NOT in the `except`. The exception escapes `consume()` and the consumer thread
dies. Because the tombstone sits at the committed offset it is a **poison pill**: every
restart re-reads it and re-crashes.

## Scope
- [x] Read the confluent decode site (`queue_backends/kafka_backend.py:174`)
- [x] Confirm the protocol path (`:686`) is ALREADY tombstone-safe (`_decode_first_record`
      returns None for `value_len <= 0`), so it needs no change — guarding it is harmless
      but must not imply it was broken.
- [x] Guard the null value before decode on the confluent path
- [x] Real tombstone regression test (live broker, no mock)

## Parity
| Port   | Path            | Tombstone handling (before) | Status |
|--------|-----------------|-----------------------------|--------|
| Python | confluent (lib) | `None.decode()` → crash     | ❌ FIX HERE |
| Ruby   | rdkafka (lib)   | `JSON.parse(nil)` → crash   | ❌ twin (tina4-ruby) |
| PHP    | pure-protocol   | guards `valueLen <= 0`      | ✅ safe |
| Node   | pure-protocol   | guards `valLen >= 0`        | ✅ safe |

## Tests (written first, real — no mocks, live Kafka via TINA4_KAFKA_BROKERS)
- [x] a tombstone at the committed offset does NOT crash the consumer; it is skipped and
      a following real record is delivered (mutation-proof: fails without the guard)
- [x] a topic holding ONLY a tombstone returns None (no job) without raising

## Verification (real broker, no mock)
- Broker: single-node Redpanda (Kafka API) in Docker on 127.0.0.1:9092; confluent-kafka 2.16.1.
- `tests/test_queue_kafka_tombstone.py` + `tests/test_queue_kafka_offset_and_raw.py`:
  **11 passed** against the live broker.
- Mutation proof: reverting the `is None` guard makes both tombstone tests fail with the
  exact reported `AttributeError: 'NoneType' object has no attribute 'decode'` at
  `kafka_backend.py:174`.

## Bugs
- [x] (#303) confluent `_dequeue` crashes on a null-value record — AttributeError

## Commits
- (fix/kafka-tombstone-crash) guard null value before decode + live tombstone regression

## Status: Complete (Python) — Ruby twin fixed in tina4-ruby/plan/kafka-tombstone-crash.md
