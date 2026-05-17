---
name: redactable-derive-selection
description: "When adding or fixing Rust redactable derives, select the correct derive so redaction, display, debug, and logging traits are generated correctly."
metadata:
  skillcatalog/display_name: "Redactable Derive Selection"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-05-17T11:10:10Z"
---
# Redactable Derive Selection

Use this skill when adding or fixing redactable derives on Rust structs or enums.

Answer these questions before choosing a derive:

1. Does this type contain sensitive data?
2. Should redacted output stay structured, or become text?
3. Must this type participate in a `Sensitive` container, a `SensitiveDisplay` template, or both?

## Quick Choice

| Situation | Use |
|---|---|
| Type contains sensitive data and should remain structured | `#[derive(Clone, Sensitive)]` |
| Type contains sensitive data and formats as text | `#[derive(SensitiveDisplay)]`, plus normal display/error derive when needed |
| Type contains no sensitive data but must work in `Sensitive` containers | `#[derive(Clone, NotSensitive)]` |
| Type contains no sensitive data and already has `Display` | `#[derive(Clone, NotSensitiveDisplay)]` |
| Newtype needs both structured traversal and redacted display | derive both with `#[sensitive(dual)]` |

Use this selection template for each type:

```text
Type:
Contains sensitive data: yes/no
Required redacted shape: structured/text/both
Used inside Sensitive containers: yes/no
Used inside SensitiveDisplay templates: yes/no
Foreign fields that cannot derive redactable traits:
Chosen derive:
Required field annotations:
```

## `Sensitive`

Prefer `Sensitive` for domain data, events, request/response payloads, job payloads, records, and any value that should keep its Rust shape after redaction.

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct PaymentEvent {
    payment_id: u64,
    #[sensitive(redactable::Email)]
    customer_email: String,
    #[sensitive(redactable::CreditCard)]
    card_number: String,
}
```

Expect these generated APIs:

- `.redact()` returns the same type with sensitive leaves redacted
- `Debug` is redacted in normal builds
- `Debug` is unredacted in `cfg(test)` or with the `testing` feature
- `slog::Value` and `SlogRedacted` exist when the `slog` feature is enabled
- `TracingRedacted` exists when the `tracing` feature is enabled

Require `Clone` for normal use because redaction consumes and returns the value.

Avoid deriving `Sensitive` only because a type appears in a display template. Use `SensitiveDisplay` when the redacted contract is text output.

## `SensitiveDisplay`

Use `SensitiveDisplay` for errors, status messages, display-oriented enums, and text output.

```rust
#[derive(thiserror::Error, redactable::SensitiveDisplay)]
enum AuthError {
    #[error("login failed for {email}")]
    InvalidLogin {
        #[sensitive(redactable::Email)]
        email: String,
    },
}
```

Take the redacted display template from `#[error("...")]` or from a doc comment.

Expect these generated APIs:

- `RedactableWithFormatter`
- `ToRedactedOutput`
- redacted `Debug`, plus feature-gated `slog` and `tracing` support matching `Sensitive`

Do not expect normal Rust `Display` or `Error`. Pair `SensitiveDisplay` with `thiserror::Error`, `displaydoc::Display`, or the project's normal display/error derive when ordinary Rust formatting is required.

Do not use `SensitiveDisplay` when the type must be traversed as a structured field in a `Sensitive` container. If a display newtype also needs structural traversal, derive both with `#[sensitive(dual)]`.

## `NotSensitive`

Use `NotSensitive` only when the whole type has no sensitive data, but must satisfy redactable trait bounds.

```rust
#[derive(Clone, Debug, serde::Serialize, redactable::NotSensitive)]
struct RetryConfig {
    max_attempts: u32,
}
```

Do not use `NotSensitive` just to silence a compiler error.

```rust
// Wrong: `email` is user data and needs a redaction policy.
#[derive(Clone, redactable::NotSensitive)]
struct LoginContext {
    email: String,
}

// Right: derive `Sensitive` and annotate the sensitive leaf.
#[derive(Clone, redactable::Sensitive)]
struct LoginContext {
    #[sensitive(redactable::Email)]
    email: String,
}
```

## `NotSensitiveDisplay`

Use `NotSensitiveDisplay` for non-sensitive types that already implement `Display`, especially operational enums and typed IDs.

```rust
#[derive(Clone, Debug, displaydoc::Display, redactable::NotSensitiveDisplay)]
enum RetryDecision {
    /// retry
    Retry,
    /// abort
    Abort,
}
```

Expect `NotSensitiveDisplay` to work in both paths:

- it passes through unchanged in `Sensitive` containers
- it formats through `Display` in `SensitiveDisplay` templates

Add `#[derive(Debug)]` yourself when `Debug` is needed.

Avoid `NotSensitiveDisplay` when raw `Display` would expose user data or secrets. Use `SensitiveDisplay` and annotate sensitive template fields instead.

## Dual Derive

Use `#[sensitive(dual)]` when a type needs both `.redact()` and `.redacted_display()`.

```rust
/// {0}
#[derive(Clone, redactable::Sensitive, redactable::SensitiveDisplay)]
#[sensitive(dual)]
struct EmailAddress(#[sensitive(redactable::Email)] String);
```

Add `#[sensitive(dual)]` whenever both derives are present on the same type. `Sensitive` handles the structured path, and `SensitiveDisplay` handles the display path.

Do not derive both without `#[sensitive(dual)]`.

```rust
// Wrong: the generated implementations conflict.
#[derive(Clone, redactable::Sensitive, redactable::SensitiveDisplay)]
struct EmailAddress(#[sensitive(redactable::Email)] String);

// Right: opt into dual mode.
#[derive(Clone, redactable::Sensitive, redactable::SensitiveDisplay)]
#[sensitive(dual)]
struct EmailAddress(#[sensitive(redactable::Email)] String);
```

If the type also needs normal `Display`, add a normal display derive or manual impl. `SensitiveDisplay` only controls redacted display output.

## Fixing Compile Errors

If a `Sensitive` type fails because a field does not implement `RedactableWithMapper`, fix the field based on ownership and sensitivity:

- derive `Sensitive` on local sensitive types
- derive `NotSensitive` or `NotSensitiveDisplay` on local non-sensitive types
- use `#[not_sensitive]` only for a truly non-sensitive foreign field
- use `SensitiveValue<T, P>` for sensitive foreign leaf values

```text
error[E0277]: the trait bound `RetryConfig: RedactableWithMapper` is not satisfied
```

```rust
// Wrong: the local field type has no redactable derive.
#[derive(Clone, redactable::Sensitive)]
struct Job {
    retry: RetryConfig,
}

// Right: derive the matching non-sensitive trait on the local field type.
#[derive(Clone, redactable::NotSensitive)]
struct RetryConfig {
    max_attempts: u32,
}
```

If a `SensitiveDisplay` type fails because a template field does not implement `RedactableWithFormatter`, fix the template field based on its display safety:

- derive `SensitiveDisplay` on local sensitive display types
- derive `NotSensitiveDisplay` on local non-sensitive display types
- use `#[not_sensitive]` only when raw `Display` or raw `Debug` is safe

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-field-policies
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-logging-boundaries
