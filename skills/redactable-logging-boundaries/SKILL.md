---
name: redactable-logging-boundaries
description: "Use when writing logging, telemetry, trace, or diagnostic output around redactable types to enforce redaction before data reaches sinks."
metadata:
  skillcatalog/display_name: "Redactable Logging Boundaries"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-05-17T11:10:10Z"
---
# Redactable Logging Boundaries

Treat every logging path as a sink boundary. A sink is anything that leaves normal program memory: logs, traces, error reports, metrics labels, support dumps, CLI output, or debug files. Redact before data reaches that boundary.

## Safe Boundaries

Use boundaries that require redactable marker traits or redacted output wrappers. Deviate only when an existing project wrapper enforces the same redaction contract or when the value is explicitly marked non-sensitive before it crosses the boundary.

Good patterns:

- `SlogRedacted` bounds for slog fields
- `TracingRedacted` bounds for tracing adapters
- `ToRedactedOutput` for custom logging pipelines that require explicit redacted or non-sensitive wrappers
- `.redacted_json()` or `.slog_redacted_json()` before structured JSON logging
- `.redacted_display()` for display text
- `.not_sensitive_display()` for known-safe operational values

Bad patterns:

- direct `println!`, `eprintln!`, or `dbg!`
- direct `log::info!` or `tracing::info!` with raw values
- `format!("{value}")` or `value.to_string()` on a sensitive value
- serializing a sensitive value and assuming serde will redact it

Do not rely on serde serialization as a redaction boundary. `Serialize` sees the value it is given; if the caller did not convert through a redactable wrapper or helper first, runtime output can expose raw fields.

Replace raw sink calls with wrapper-based calls before values reach the sink.

```rust
// Bad: raw value reaches the tracing sink.
tracing::info!(user = ?user, "created account");

// Good: caller chooses the redacted representation first.
tracing::info!(user = ?user.tracing_redacted(), "created account");
```

## Slog

Enable the `slog` feature when using slog.

```toml
redactable = { version = "...", features = ["slog"] }
```

Types deriving `Sensitive`, `SensitiveDisplay`, `NotSensitive`, and `NotSensitiveDisplay` implement `SlogRedacted` when the feature is enabled.

Use `SlogRedacted` as a compile-time gate in logging helpers.

```rust
fn assert_safe<T: redactable::slog::SlogRedacted>(_: &T) {}
```

For structured data, use `Sensitive` to emit redacted JSON through slog. For display data, use `SensitiveDisplay` to emit the redacted display string.

If `redactable-derive` cannot find a top-level `slog` crate, set `REDACTABLE_SLOG_CRATE` to the path of the re-exported slog crate, such as `my_logging::slog`.

## Tracing

Enable the `tracing` feature for tracing marker support.

Use `.tracing_redacted()` for display-string output.

Use `.tracing_redacted_valuable()` when the `tracing-valuable` feature is enabled and the subscriber supports `valuable`. This keeps structured data shape after redaction.

Do not pass raw values directly to tracing fields unless the project has its own wrapper that enforces redactable safety.

## Custom Pipelines

Accept `ToRedactedOutput` at custom sink boundaries when callers must pass an explicit redacted or non-sensitive wrapper.

Treat `RedactedOutput` as the only payload shape the sink may receive:

- `Text(String)`
- `Json(serde_json::Value)` when the `json` feature is enabled

Prefer `ToRedactedOutput` over `Display`, `Debug`, or `Serialize` because it requires a redacted representation or an explicit non-sensitive wrapper.

Use this boundary template for custom sinks. Keep the wrapper requirement at the public boundary and write only the converted `RedactedOutput` to the sink.

```rust
use redactable::{RedactedOutput, ToRedactedOutput};

fn write_safe_field<T>(sink: &mut dyn LogSink, key: &str, value: T)
where
    T: ToRedactedOutput,
{
    match value.to_redacted_output() {
        RedactedOutput::Text(text) => sink.write_text(key, &text),
        #[cfg(feature = "json")]
        RedactedOutput::Json(json) => sink.write_json(key, &json),
    }
}
```

Require callers to choose the wrapper before calling the boundary.

```rust
write_safe_field(&mut sink, "user_id", user_id.not_sensitive_display());
write_safe_field(&mut sink, "payload", payload.redacted_json());
```

Reject raw strings at custom sink boundaries. Raw strings do not implement `ToRedactedOutput`; they only pass through the lower-level `RedactableWithFormatter` path used inside redacted display templates. If a string is safe for a custom sink, require `.not_sensitive_display()`, `.not_sensitive_debug()`, `.not_sensitive_json()`, or a project wrapper with the same explicit meaning.

## Non-Sensitive Values

Make operational values explicit at logging boundaries when the boundary enforces safety.

Use:

- `.not_sensitive_display()` for counts, booleans, status codes, enum names, and safe IDs
- `.not_sensitive_debug()` only when the debug shape has been checked
- `.not_sensitive_json()` only when the full JSON is safe

Do not wrap user-provided strings as non-sensitive just because a log statement will not compile.

## Redacted JSON

Use redacted JSON helpers when the sink needs structure.

```rust
use redactable::RedactedJsonExt;

info!("event"; "payload" => payload.redacted_json());
```

For slog, use `.slog_redacted_json()` to redact first and then serialize. Treat serialization errors as placeholder strings instead of reasons to fall back to raw output.

## Test-Mode Debug

Remember that `Sensitive` and `SensitiveDisplay` generate unredacted `Debug` in tests and with the `testing` feature. Do not write raw debug output from tests to shared logs or committed fixtures.

Expect generated `Debug` to be redacted in production builds.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-review-checklist
