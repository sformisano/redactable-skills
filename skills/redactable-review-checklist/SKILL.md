---
name: redactable-review-checklist
description: "Apply when reviewing PRs or Rust code that handles user data, secrets, or telemetry. Finds redactable mistakes: missing policies, unsafe escape hatches, and raw logging bypasses."
metadata:
  skillcatalog/display_name: "Redactable Review Checklist"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-06-29T10:58:00Z"
---
# Redactable Review Checklist

Use this skill when reviewing Rust code that handles user data, secrets, financial data, logs, traces, errors, or telemetry.

Lead with leak risk. A redaction bug is a security and privacy bug.

## Type-Level Checks

Check every type that can be logged, traced, displayed, serialized for diagnostics, or included in an error.

- Verify that sensitive structured types derive `Sensitive`.
- Verify that sensitive text/error types derive `SensitiveDisplay`.
- Verify that sensitive text/error types needing ordinary Rust `Display` or `Error` also use `thiserror::Error`, `displaydoc::Display`, or the project's normal display/error derive.
- Confirm that `NotSensitive` is derived only on truly public structured types where every field is safe.
- Confirm that `NotSensitiveDisplay` is derived only when the `Display` output is safe.
- Confirm that newtypes needing both paths use `#[sensitive(dual)]` (since 0.8, `dual` with only one derive fails to compile for non-generic types, so a compiling non-generic pair is coordinated).
- For generic dual types, confirm tests or local conventions keep `Sensitive` and `SensitiveDisplay` paired; redactable's missing-pair compile guard currently covers non-generic types only.
- Confirm that enum annotations sit on variant *fields*; variant-level `#[sensitive(...)]` is a compile error since 0.8 - and code written against older versions may carry silently-ignored variant annotations that never redacted anything.

Red flag: `NotSensitive` or `NotSensitiveDisplay` on a type with names, emails, addresses, tokens, raw payloads, customer data, account data, financial data, or user input.

Red flag: assuming `#[derive(SensitiveDisplay)]` alone implements normal `Display` or `Error`. It generates redacted display traits and `Debug`; normal Rust formatting still needs the normal project derive or impl.

Red flag: assuming `#[derive(SensitiveDisplay)]` satisfies structural `Redactable` bounds. It implements `ToRedactedOutput`; derive `Sensitive` as well with `#[sensitive(dual)]` when the same type needs `.redact()`.

### Template: correct struct derives

```rust
// WRONG — missing policy, no SensitiveDisplay for error path
#[derive(Debug, Serialize)]
struct UserProfile {
    email: String,
    display_name: String,
    account_id: u64,
}

// CORRECT — derives Sensitive, fields annotated
#[derive(Sensitive)]
struct UserProfile {
    #[sensitive(Email)]
    email: String,
    #[sensitive(Pii)]
    display_name: String,
    // operational field — no annotation needed
    account_id: u64,
}
```

## Field-Level Checks

For each `Sensitive` or `SensitiveDisplay` type:

- Verify that sensitive `String` and `Cow<str>` fields have `#[sensitive(Policy)]`.
- Verify that sensitive scalar fields import `Secret` and use bare `#[sensitive(Secret)]`.
- Confirm that nested types deriving `Sensitive` are unannotated so traversal can walk them.
- Confirm that 0.10+ containers are treated correctly: `VecDeque`, arrays, tuples up to four elements, `Mutex`, and `RwLock` delegate to certified contents; raw leaves inside those containers are still not certified.
- Confirm that `serde_json::Value` fields are understood to fully redact.
- Confirm that `HashMap` and `BTreeMap` keys do not contain sensitive data.
- Confirm that sets are not used where redaction could collapse distinct values and break count-sensitive behavior.

Red flag: unannotated fields named `name`, `email`, `phone`, `address`, `token`, `secret`, `password`, `key`, `payload`, `metadata`, `context`, `message`, or `reason`.

## Escape Hatch Checks

You MUST answer each question for every escape hatch found. Flag the escape hatch if any answer is unclear.

- Why is `#[not_sensitive]` safe here?
- Why is `.not_sensitive_display()` safe here?
- Why is `.not_sensitive_debug()` safe here?
- Does the wrapped value contain user input or a nested sensitive type?
- Is this just silencing a compiler error?

Red flag: `#[not_sensitive]` on a `String`, `serde_json::Value`, nested `Sensitive` type, or broad context object.

## Logging And Telemetry Checks

Search for raw output bypasses:

```text
println!
eprintln!
dbg!
tracing::info!
tracing::debug!
log::info!
format!(
to_string()
serde_json::to_string
```

These are not always wrong, but they need proof that no sensitive value reaches them.

Prefer project logging macros or helpers that require `SlogRedacted`, `TracingRedacted`, or `ToRedactedOutput`.

For structural `Sensitive` values in tracing fields, suggest `use redactable::tracing::TracingRedactedDebugExt;` and `.tracing_redacted_debug()`. The helper redacts a clone before recording a `Debug` field, and raw `String` does not satisfy its bounds.

For custom `ToRedactedOutput` sinks, raw `String` must not compile. Callers should pass a `SensitiveDisplay` value, `SensitiveValue`, `.redacted_output()`, `.redacted_json()` when `redactable/json` is enabled, or an explicit `.not_sensitive_*()` wrapper. Since 0.9 the compiler enforces most of this: raw leaves implement neither `Redactable` nor `ToRedactedOutput`, so the redacted-output methods do not exist on them. Review effort goes to the escape hatches (`.not_sensitive_*()`, `#[not_sensitive]`, `.expose()`), not to hunting raw-value certification.

## Serialization Checks

Serialization is not redaction.

Check for:

- serializing a `Sensitive` value without calling `.redact()` first
- serializing `SensitiveValue<T, P>` directly
- sending raw diagnostic JSON to logs or traces
- writing test fixtures that contain unredacted `Debug` output

Use `.redacted_json()` or `.slog_redacted_json()` when `redactable/json` is enabled, or `.redact()` before diagnostic serialization.

### Anti-pattern: serializing without redaction

```rust
// WRONG — leaks sensitive fields into log
let json = serde_json::to_string(&user_profile)?;
tracing::info!(payload = %json, "processed request");

// CORRECT — redact before serializing for diagnostics
let redacted = serde_json::to_string(&user_profile.clone().redact())?;
tracing::info!(payload = %redacted, "processed request");
// (.redacted_json() yields a slog-oriented wrapper without Display;
// use it with slog fields or ToRedactedOutput sinks, not tracing's %.)
```

## Error Message Checks

For error types:

- Verify that `SensitiveDisplay` is used when any variant may contain sensitive data.
- Verify that normal `Display` or `Error` is derived separately when callers use ordinary Rust formatting.
- Verify that fields referenced in templates are annotated when sensitive.
- Confirm that `#[not_sensitive]` is used only when raw display/debug output is safe.
- Confirm that source errors are not blindly displayed if their messages may contain user data.

### Template: correct error enum

```rust
use redactable::{Email, SensitiveDisplay};

// WRONG — email leaks through Display
#[derive(Debug, thiserror::Error)]
enum AccountError {
    #[error("failed for {email}")]
    LookupFailed { email: String },
}

// CORRECT — SensitiveDisplay redacts; thiserror provides normal Error impl
#[derive(SensitiveDisplay, thiserror::Error)]
enum AccountError {
    #[error("failed for {email}")]
    LookupFailed {
        #[sensitive(Email)]
        email: String,
    },
}
```

## Tests To Expect

Ask for focused tests when the change adds or changes redaction behavior.

Useful tests:

- `.redact()` changes sensitive fields and preserves operational fields
- `.redacted_display()` redacts template fields
- nested structs are walked without outer annotations
- 0.10+ containers (`VecDeque`, arrays, tuples up to four elements, `Mutex`, `RwLock`) delegate only when their contents are certified
- `serde_json::Value` payloads redact to `[REDACTED]`
- tracing `.tracing_redacted_debug()` captures redacted text and excludes raw sensitive bytes
- logging helpers reject raw `String` or accept only redacted wrappers when compile-fail tests are available

### Template: redaction test

```rust
#[test]
fn redact_replaces_sensitive_fields() {
    let profile = UserProfile {
        email: "alice@example.com".into(),
        display_name: "Alice".into(),
        account_id: 42,
    };
    let redacted = profile.redact();
    // Assert the policy-shaped output, not a generic placeholder:
    // Email keeps the first 2 local chars and the domain; Pii keeps the last 2.
    assert_eq!(redacted.email, "al***@example.com");
    assert_eq!(redacted.display_name, "***ce");
    assert_eq!(redacted.account_id, 42); // operational field preserved
}
```

Also cover the fail-closed edge when short values are possible: keep-based policies fully mask values at or below their keep window (0.8+), so a 2-character `display_name` under `Pii` becomes `**`, not the raw name.

Do not rely only on generated `Debug` in tests: your crate's `cfg(test)` builds (and redactable's own `testing` feature) intentionally show raw values for `Sensitive` and `SensitiveDisplay`. Asserting production-redacted `Debug` requires the type to live in a non-test fixture crate.

## Review Finding Template

When reporting findings, use this format for consistency:

```
**Finding:** <what is wrong>
**Leak path:** <how sensitive data reaches output>
**Required policy:** <derive or annotation needed>
**Expected test:** <assertion that would catch regression>
```

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-field-policies
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-logging-boundaries
