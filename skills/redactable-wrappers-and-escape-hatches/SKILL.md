---
name: redactable-wrappers-and-escape-hatches
description: "Apply when derive macros cannot handle a field or a logging boundary needs explicit wrappers, so sensitive values do not leak."
metadata:
  skillcatalog/display_name: "Redactable Wrappers And Escape Hatches"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-05-17T11:10:10Z"
---
# Redactable Wrappers And Escape Hatches

Use this skill when a field cannot be handled cleanly by derive macros, or when a logging boundary needs an explicit safe wrapper.

Escape hatches are useful, but they are also where leaks usually happen. Use the narrowest one that says what you mean.

## `SensitiveValue<T, P>`

Use `SensitiveValue<T, P>` for a sensitive leaf value that should carry its policy in the type.

```rust
use redactable::{Sensitive, SensitiveValue, Token};

#[derive(Clone, Sensitive)]
struct AuthConfig {
    api_key: SensitiveValue<String, Token>,
}
```

Rely on `Debug` and `.redacted()` for redacted output. Call `.expose()` only at boundaries that truly need the raw value.

Prefer `SensitiveValue<T, P>` when accidental raw formatting is a real risk, when the value type comes from another crate, or when a `Sensitive` container needs a leaf with an explicit policy.

## Sensitive Foreign Types

For a sensitive type from another crate, define a local policy, implement `SensitiveWithPolicy<P>` for the foreign type, and store it as `SensitiveValue<ForeignType, LocalPolicy>`.

Use this template only for types you cannot derive on locally:

```rust
#[derive(Clone, Copy)]
struct MerchantPolicy;

impl redactable::RedactionPolicy for MerchantPolicy {
    fn policy() -> redactable::TextRedactionPolicy {
        redactable::TextRedactionPolicy::keep_last(4)
    }
}

impl redactable::SensitiveWithPolicy<MerchantPolicy> for MerchantAccount {
    fn redact_with_policy(self, policy: &redactable::TextRedactionPolicy) -> Self {
        self.with_redacted_id(policy.apply_to(self.id()))
    }

    fn redacted_string(&self, policy: &redactable::TextRedactionPolicy) -> String {
        policy.apply_to(self.id())
    }
}
```

Do not implement a broad policy that preserves fields you have not audited.

## `NotSensitiveValue<T>`

Use `NotSensitiveValue<T>` for a foreign type that is truly non-sensitive and needs to pass through a `Sensitive` container.

```rust
#[derive(Clone, redactable::Sensitive)]
struct Config {
    timeout: redactable::NotSensitiveValue<other_crate::Timeout>,
}
```

Do not use it around a type that contains sensitive fields. It is a passthrough and does not walk nested values.

For local non-sensitive types, prefer `#[derive(NotSensitive)]` or `#[derive(NotSensitiveDisplay)]`.

## `#[not_sensitive]`

Use `#[not_sensitive]` when the field type should pass through unchanged and the field is genuinely safe.

Good uses:

- timestamps
- operational IDs
- retry decisions
- transaction handles
- foreign error/context types whose display is known safe

Bad uses:

- `String` fields with user input
- nested `Sensitive` types
- anything named `name`, `email`, `phone`, `address`, `token`, `secret`, `payload`, `metadata`, or `context` unless you have checked the data source

Remember that `#[not_sensitive]` skips traversal. If you put it on a nested sensitive value, inner sensitive fields will not be redacted.

## Logging Boundary Wrappers

Use these wrappers when a value is safe and you need to satisfy a logging boundary:

| Wrapper | Meaning |
|---|---|
| `.not_sensitive_display()` | log with `Display` |
| `.not_sensitive_debug()` | log with `Debug` |
| `.not_sensitive_json()` | log as raw JSON, requires the `json` feature |
| `.not_sensitive()` | generic wrapper, only useful when the sink knows how to format the inner type |

Use `.not_sensitive_display()` for simple operational values such as counts, enum names, durations, and status codes.

Use `.not_sensitive_debug()` only when the `Debug` output is known not to contain sensitive data.

## Redacted Output Wrappers

Use these when the value itself has redactable support and the sink wants a single output type:

| Wrapper | Meaning |
|---|---|
| `.redacted_output()` | redacts and emits text using redacted `Debug` |
| `.redacted_json()` | redacts and then serializes to JSON |
| `.redacted_display()` | redacted text for `SensitiveDisplay` types |

Prefer `.redacted_json()` for structured telemetry when the type implements `Serialize`.

## Serialization Is Raw Unless You Redact First

Treat serialization as raw output unless you explicitly redact before the boundary.

`SensitiveValue<T, P>` serializes its inner value unchanged when the `json` feature is enabled. This is intentional because APIs, databases, and queues usually need the real value.

Apply the same rule to normal `Sensitive` structs: deriving `Serialize` does not mean serialization is redacted.

If the output must be safe, call `.redact()`, `.redacted_json()`, `.slog_redacted_json()`, or another redacted boundary API before serializing or logging.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-field-policies
- @skill:redactable-logging-boundaries
- @skill:redactable-review-checklist
