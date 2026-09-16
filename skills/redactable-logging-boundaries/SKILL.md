---
name: redactable-logging-boundaries
description: "Use when writing logging, telemetry, trace, or diagnostic output around redactable types to enforce redaction before data reaches sinks."
metadata:
  skillcatalog/display_name: "Redactable Logging Boundaries"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Logging Boundaries

Targets `redactable` 0.13. A sink is anything that leaves normal program memory: logs, traces, error reports, metrics labels, support dumps, CLI output, debug files. Redact before data reaches it.

## `ToRedacted` Is The Boundary

Every derive implements `ToRedacted`. `.to_redacted()` borrows the receiver and returns an owned `RedactedValue`, which a sink reads two ways:

- `.text()` — the redacted text, or the redacted JSON rendered compactly
- `.json()` — the redacted JSON, or `{"message": text}` for a text-only producer

**[guarantee]** Neither accessor can refuse. Redaction finishes when the value is built; the accessors only convert what is stored, and never rerun a policy. `RedactedValue` is opaque: no variants to match, no public constructor, no `From`, no `Deserialize`.

**[guarantee]** JSON production is fail-closed, and it fails coarsely. If serializing the redacted value errors — a map with compound keys, a custom `Serialize` that returns an error — the **entire** value becomes the string `"[REDACTED]"`, not a partial object. The serializer's error text is discarded. A log field that unexpectedly reads `"[REDACTED]"` where an object was expected is this, not a policy. It does not catch panics: a panicking `Serialize` or `Clone` still unwinds.

**[guarantee]** Raw leaves never implement `ToRedacted`. A bare `String`, `u64`, or `Vec<String>` at a `ToRedacted` boundary is a compile error. So is `BypassRedaction<T>`, which deliberately carries raw data without choosing a format.

Good patterns:

- `ToRedacted` bounds on custom pipelines
- `SlogRedacted` / `TracingRedacted` bounds on slog and tracing helpers
- `.slog_redacted_json()` and `.slog_redacted()` for slog
- `.tracing_redacted_debug()` and `.tracing_redacted()` for tracing
- `.redacted_display()` for display text
- a `Bypass*` wrapper for a value declared public

Bad patterns:

- `println!`, `eprintln!`, `dbg!`
- `log::info!` / `tracing::info!` with a raw value
- `format!("{value}")` or `value.to_string()` on a sensitive value
- formatting an error through its ordinary `Display` when the crate pairs `SensitiveDisplay` with `thiserror`
- serializing a value and assuming serde redacted it

## Custom Pipelines

Accept `ToRedacted` at the public boundary and write only the converted value.

```rust
use redactable::ToRedacted;

fn write_field<T: ToRedacted + ?Sized>(sink: &mut dyn LogSink, key: &str, value: &T) {
    let redacted = value.to_redacted();
    if sink.wants_structure() {
        sink.write_json(key, redacted.json());
    } else {
        sink.write_text(key, &redacted.text());
    }
}
```

There is no branch for "the producer did not build what I asked for" — pick the representation the sink wants and the value adapts.

`.to_redacted()` accepts unsized producers, including `&dyn ToRedacted`. Callers choose the wrapper before reaching the boundary:

<!-- harness-setup
use redactable::{BypassDisplayRedaction, ToRedacted};
fn write_field<T: ToRedacted + ?Sized>(sink: &mut dyn LogSink, key: &str, value: &T) {
    let redacted = value.to_redacted();
    if sink.wants_structure() { sink.write_json(key, redacted.json()); }
    else { sink.write_text(key, &redacted.text()); }
}
let mut sink = CapturingSink::default();
let event = User { id: 7, email: "alice@example.com".into() };
let status = 200_u16;
-->
```rust
write_field(&mut sink, "payload", &event);                          // a derived type
write_field(&mut sink, "status", &BypassDisplayRedaction(status));  // declared public

assert_eq!(
    sink.written,
    [r#"payload={"email":"al***@example.com","id":7}"#, "status=200"],
);
```

**Must-do:** Do not write a handwritten `ToRedacted` for a type that already derives one; that will not compile. Build a handwritten implementation from a `Bypass*` member, or define a separate log-view type.

## slog

```toml
redactable = { version = "0.13", features = ["slog"] }
```

Generated code reaches slog through `redactable`'s own re-export, so a consumer does not need a direct `slog` dependency, and a renamed `redactable` dependency resolves automatically.

The five derives and `SensitiveValue` implement `slog::Value` + `SlogRedacted`. Use `SlogRedacted` as a compile-time gate:

```rust
fn assert_safe<T: redactable::slog::SlogRedacted>(_: &T) {}
```

**Must-do:** Know what this gate does and does not exclude. It rejects raw leaves — that is its value. It **admits** every `NotSensitive` type and the format-selecting wrappers `BypassDisplayRedaction`, `BypassDebugRedaction`, and `BypassJsonRedaction`, all of which emit raw data by design, because each is a declaration that the author said the value is public. And a helper that checks the bound and then formats a raw field still leaks. The bound proves a declaration exists, never that the declaration is correct.

Two members are **not** admitted, and neither is a safety result: `BypassRedaction` and `BypassTextRedaction` implement no `slog::Value`, because neither selects a slog output format. `BypassRedactionMarker<T>` is admitted only when `T: slog::Value`, and then forwards to that implementation. To log a composed summary, convert it first — `BypassTextRedaction(summary).to_redacted()` yields a `RedactedValue`, which is `SlogRedacted`.

**Must-do:** Passing a borrowed `Sensitive` or `SensitiveDual` value **directly** to slog emits the fixed placeholder `"[REDACTED]"`, not its redacted fields. That is the fail-closed direct implementation: it never clones or serializes the raw reference. Use `.slog_redacted_json()` when you want the redacted object.

<!-- harness-setup
let logger = discard_logger();
let event = User { id: 7, email: "alice@example.com".into() };
-->
```rust
use redactable::slog::SlogRedactedExt;

slog::info!(logger, "payment"; "event" => &event);                      // "[REDACTED]"
slog::info!(logger, "payment"; "event" => event.slog_redacted_json());  // redacted JSON

// What each call actually put on the wire:
assert_eq!(capture_slog(&event), serde_json::json!("[REDACTED]"));
assert_eq!(
    capture_slog(&event.slog_redacted_json()),
    serde_json::json!({"id": 7, "email": "al***@example.com"}),
);
```

(`capture_slog` is harness scaffolding, not part of the crate; it records what a
single value emits so the difference above is proven rather than described.)

`SlogRedactedExt` is bounded on `ToRedacted`, so it reaches every producer, including a plain `Sensitive` struct that implements no formatter:

- `.slog_redacted()` — a borrowed adapter emitting the producer's redacted **text**; runs the producer each time slog serializes the record. It additionally requires `Sized`, so it is not available on `&dyn ToRedacted`.
- `.slog_redacted_json()` — runs the producer at the call and returns an owned JSON value; accepts unsized producers.

Structured slog output needs nested-value support through the whole drain stack. Enabling `redactable/slog` enables it on `slog` itself but not on separate drain crates: enable `nested-values` on `slog-async`, `slog-json`, and any other drain you use.

## Tracing

```toml
redactable = { version = "0.13", features = ["tracing"] }
```

| Adapter | Bounds | Emits |
|---|---|---|
| `.tracing_redacted_debug()` | `Redactable + Clone + Debug` | redacted clone as a `Debug` field |
| `.tracing_redacted()` | `ToRedacted` | the producer's text as a display field |
| `.tracing_redacted_valuable()` | `Redactable + Clone + Valuable` | structured `valuable` data |
| `.into_tracing_redacted_debug()` | `Redactable + Debug` | consuming variant, redacts without cloning first |
| `.into_tracing_redacted_valuable()` | `Redactable + Valuable` | consuming variant |

<!-- harness-setup
let account = User { id: 7, email: "alice@example.com".into() };
let event = User { id: 8, email: "bob@example.com".into() };
-->
```rust
use redactable::tracing::{TracingRedactedDebugExt, TracingRedactedExt};

tracing::info!(
    account = %account.tracing_redacted(),     // text: template, or compact JSON
    payload = event.tracing_redacted_debug(),  // redacted Debug
    "publishing safe telemetry"
);
```

`.tracing_redacted()` works on **every** producer, including structural `Sensitive` types — it renders their JSON as compact text. Use `.tracing_redacted_debug()` when you want the redacted Rust shape instead.

For `valuable`, enable `tracing-valuable`, compile with `RUSTFLAGS="--cfg tracing_unstable"`, and use a subscriber that supports it. Bind the wrapper first:

<!-- harness-skip: requires RUSTFLAGS="--cfg tracing_unstable" and the
tracing-valuable feature, which the harness does not build with. The crate
marks its own equivalent example `ignore` for the same reason. -->
```rust,ignore
use redactable::tracing::TracingValuableExt;

let redacted = event.tracing_redacted_valuable();
tracing::info!(event = tracing::field::valuable(&redacted));
```

`TracingRedactedValue` is constructed only through those adapters, is not `Clone`, and is read through the consuming `into_inner(self)`. It redacts once, at construction, and forwards borrowed projections of the redacted object — a caller that can mutate through such a projection can change what a later projection observes.

## Cloning And Panics

The producer decides what work happens inside an adapter:

| Producer | Behavior |
|---|---|
| `Sensitive`, `SensitiveDual` | clone, redact the clone, serialize it |
| `SensitiveDisplay` | format the borrowed value through the crate's formatter |
| `NotSensitiveDisplay` | use the type's own `Display` |
| `NotSensitive` | serialize the borrowed value |

**[guarantee]** Structural producers inherit every `Clone` panic. A traversed `RefCell` with a live mutable borrow panics at the log call, through `.slog_redacted()`, `.slog_redacted_json()`, `.tracing_redacted()`, and `.tracing_redacted_debug()`. `SensitiveDisplay` renders such a cell as `<borrowed>` instead.

**[guarantee]** The consuming `into_tracing_*` adapters call `.redact()` on the owned value instead of cloning first, but traversal itself still clones an `Arc`/`Rc` referent and a map or set hasher — so a live mutable `RefCell` borrow behind shared ownership can still panic. Prefer `Box` for values you log.

## Test-Mode Debug

**[guarantee]** No build mode disables policy masking in generated `Debug`: not production, not your crate's `cfg(test)`, and not redactable's own `testing` feature, which enables test helpers without raw exposure. A test asserting that an *annotated* field shows its raw value in `Debug` will fail.

That is a statement about annotated fields only. `#[not_sensitive]` fields and unannotated opaque leaves such as `serde_json::Value` print raw in every mode by design, so a test asserting raw output for those passes and should. See @skill:redactable-core-model for what each derive's `Debug` actually prints — it is not one shape.

Use `testing::assert_json_shape` to check that a redacted value keeps the shape of its plain serialization:

```toml
redactable = { version = "0.13", features = ["testing"] }
```

<!-- harness-setup
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Decision {
    #[sensitive(redactable::Secret)]
    owner: String,
    #[not_sensitive]
    approved: bool,
}
let decision = Decision { owner: "Ada".into(), approved: true };
-->
```rust
use redactable::{testing::assert_json_shape, ToRedacted};

let plain = serde_json::to_value(&decision).unwrap();
let value = decision.to_redacted();
assert_json_shape(&plain, &value, &[]);
assert_eq!(value.json(), serde_json::json!({"owner": "[REDACTED]", "approved": true}));
```

It compares object keys, array lengths and positions, and scalar JSON kinds; strict JSON Pointer paths mark opaque nodes. **Must-do:** Pair it with an independently written expected value. A matching shape does not prove correct masking.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-review-checklist
