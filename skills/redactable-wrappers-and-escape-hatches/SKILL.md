---
name: redactable-wrappers-and-escape-hatches
description: "Apply when derive macros cannot handle a field or a logging boundary needs explicit wrappers, so sensitive values do not leak."
metadata:
  skillcatalog/display_name: "Redactable Wrappers And Escape Hatches"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Wrappers And Escape Hatches

Targets `redactable` 0.13. Use when a field cannot be handled by a derive, or when a logging boundary needs an explicit wrapper.

Choose the narrowest wrapper that states the intended behavior. Treat every bypass as a leak risk until the call site proves otherwise.

## Choosing

| Need | Use |
|---|---|
| Sensitive leaf carrying its own policy | `SensitiveValue<T, P>` |
| Public field in a struct you own, including a foreign type | `#[not_sensitive]` on the field |
| Foreign value at a `Redactable`-bounded boundary, whose whole content is reviewed public | `BypassRedaction<T>` |
| Public value logged through `Display` | `BypassDisplayRedaction<T>` |
| Public value logged through `Debug` | `BypassDebugRedaction<T>` |
| Borrowed public value logged as raw JSON | `BypassJsonRedaction<'_, T>` |
| Author-composed summary text | `BypassTextRedaction(String)` |
| Public value using slog's native typed output | `BypassRedactionMarker<T>` |

**Must-do:** A foreign field inside a struct you own does **not** need a wrapper. Annotate it `#[not_sensitive]` — the declaration sits on the field it describes and the field keeps its own type. Reach for `BypassRedaction<T>` only when an API demands `Redactable` on a value you cannot annotate.

Every `Bypass*` member is a tuple struct with a public field. Construction is the declaration: `BypassDebugRedaction(&value)`, `BypassTextRedaction(summary)`. There are no extension-method constructors.

## `SensitiveValue<T, P>`

Use it for a sensitive leaf that should carry its policy in the type.

```rust
use redactable::{Sensitive, SensitiveValue, Token};

#[derive(Clone, serde::Serialize, Sensitive)]
struct AuthConfig {
    api_key: SensitiveValue<String, Token>,   // unannotated: the wrapper declares itself
}

let key = SensitiveValue::<String, Token>::from("sk-secret-key".to_owned());
assert_eq!(key.redacted(), "*********-key");
```

- `Debug` shows the **policy-redacted** value, not a flat placeholder.
- It has no `Display`, so accidental `{}` formatting does not compile.
- `.redacted()` returns the policy text; `.to_redacted()` carries that same text.
- It implements `ToRedacted`, `slog::Value` + `SlogRedacted`, and `TracingRedacted`.
- `Serialize` and `Deserialize` pass the **raw** inner value through, for transport and storage.

Three accessors hand back the raw value: `.expose()`, `.expose_mut()`, and the consuming `.into_inner()`. Call any of them only when crossing a boundary that must consume raw data — an outbound API request, a database write, a queue message, a signing call. Before adding one, verify the value is not formatted, logged, put into an error, or serialized for diagnostics on the same path. `.into_inner()` deserves the most scrutiny: it drops the wrapper, so nothing downstream carries the policy any more.

Prefer `SensitiveValue<T, P>` when accidental raw formatting is a real risk, when the value type comes from another crate, or when a leaf needs an explicit policy that follows it around.

## Sensitive Foreign Types

For a sensitive type from another crate, define a local policy, implement `SensitiveWithPolicy<P>` for the foreign type, and store it as `SensitiveValue<ForeignType, LocalPolicy>`. The orphan rule is satisfied because the policy is local.

```rust
use redactable::{RedactionPolicy, SensitiveWithPolicy, TextPolicyKind, TextRedactionPolicy};

#[derive(Clone, Copy)]
struct MerchantPolicy;

impl RedactionPolicy for MerchantPolicy {
    type Kind = TextPolicyKind;

    fn policy() -> TextRedactionPolicy {
        TextRedactionPolicy::keep_last(4)
    }
}

impl SensitiveWithPolicy<MerchantPolicy> for MerchantAccount {
    fn redact_with_policy(self, policy: &TextRedactionPolicy) -> Self {
        Self { id: policy.apply_to(&self.id), ..self }
    }

    fn redacted_string(&self, policy: &TextRedactionPolicy) -> String {
        policy.apply_to(&self.id)
    }
}
```

`SensitiveWithPolicy` powers `SensitiveValue<T, P>` only. It does not make a bare `#[sensitive(P)]` field of that type compile — direct annotated fields use separate policy-application traits.

`SensitiveValue` treats `T` as an atomic leaf and does not walk its fields. **Must-do:** Do not write a `redact_with_policy` that preserves fields you have not audited; a partial implementation looks redacted and is not.

## `BypassRedaction<T>`

Use it only to satisfy a `Redactable` bound on a value you do not own.

<!-- harness-setup
let foreign_config = ForeignConfig { timeout_ms: 500 };
-->
```rust
use redactable::{BypassRedaction, Redactable};

fn audit<T: Redactable>(value: T) -> T { value.redact() }

// `ForeignConfig` is from another crate and implements nothing of ours.
let checked = audit(BypassRedaction(foreign_config));
assert_eq!(checked.0.timeout_ms, 500); // passthrough: nothing was redacted
```

It is a passthrough: `.redact()` returns the value unchanged, and `Serialize` emits the raw inner value. It does **not** implement `ToRedacted` — it carries raw data without choosing a logging format. To log the value, wrap it in `BypassJsonRedaction` or a sibling instead.

**Must-do:** Do not use it around a type that contains sensitive fields. It does not walk nested values.

## `#[not_sensitive]`

`#[not_sensitive]` declares the field public and skips traversal entirely.

Good uses: timestamps, operational IDs, retry decisions, transaction handles, status codes, foreign types whose complete output is known safe.

Bad uses: `String` fields with user input, nested sensitive types, and anything named `name`, `email`, `phone`, `address`, `token`, `secret`, `payload`, `metadata`, or `context` unless you have checked the data source.

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Signup {
    #[not_sensitive]
    email: String,  // Bad: this leaks the raw email into every redacted output.
}
```

Since 0.12 the compiler requires a declaration on every field, so `#[not_sensitive]` now appears on ordinary operational fields too. **Must-do:** Do not let that volume dull review. A `#[not_sensitive]` on `u64 id` is routine; the same annotation on a `String` or a nested struct is a finding until justified.

Remember that `#[not_sensitive]` skips traversal: on a nested sensitive value, its inner fields are never redacted.

## Bypass Wrappers At Logging Boundaries

Use these only when the value's complete output is public and the sink needs a format selected.

| Wrapper | Emits | Notes |
|---|---|---|
| `BypassDisplayRedaction(v)` | the `Display` text | owns or borrows; `into_inner()`; raw Serde |
| `BypassDebugRedaction(v)` | the `Debug` text | owns or borrows; `into_inner()`; raw Serde |
| `BypassJsonRedaction(&v)` | the `Serialize` form as JSON | borrowed only |
| `BypassTextRedaction(s)` | the string you composed | validates nothing, allows empty text |
| `BypassRedactionMarker(v)` | nothing of its own | no `ToRedacted`; forwards to slog's typed emitter, and accepts a type with neither `Display` nor `Debug` |

<!-- harness-setup
let status = 200_u16;
let elapsed = std::time::Duration::from_millis(12);
-->
```rust
use redactable::{BypassDebugRedaction, BypassDisplayRedaction, ToRedacted};

tracing::info!(
    status = %BypassDisplayRedaction(status),
    elapsed = %BypassDebugRedaction(elapsed).to_redacted().text(),
    "request complete"
);

assert_eq!(BypassDisplayRedaction(status).to_redacted().text(), "200");
assert_eq!(BypassDebugRedaction(elapsed).to_redacted().text(), "12ms");
```

**Must-do:** Do not use `BypassDebugRedaction` on request bodies, error contexts, metadata maps, or any value whose `Debug` output can include user input.

**Must-do:** `BypassTextRedaction` makes no promise that the summary is complete or safe. Assert the intended summary in a logging test.

The Serde implementations of `BypassDisplayRedaction`, `BypassDebugRedaction`, and `BypassRedaction` expose the **raw** inner value for transport and storage. That is not redaction.

## Logging A Slice

A container does not inherit `ToRedacted` from its elements: `Vec<T>` is not a logging value even when `T` is. Use `RedactedList` for a slice of producers.

<!-- harness-setup
let events = [
    User { id: 1, email: "alice@example.com".into() },
    User { id: 2, email: "bob@example.com".into() },
    User { id: 3, email: "carol@example.com".into() },
];
-->
```rust
use std::num::NonZeroUsize;
use redactable::{RedactedList, ToRedacted};

let value = RedactedList::new(&events, NonZeroUsize::new(2).unwrap()).to_redacted();

assert_eq!(
    value.json(),
    serde_json::json!({
        "items": [
            {"id": 1, "email": "al***@example.com"},
            {"id": 2, "email": "bo*@example.com"},
        ],
        "omitted": 1,
    }),
);
```

Only the included producers run, once each, in order. The omitted count is deliberately visible. The limit bounds item count only — not bytes, depth, or policy cost.

## Serialization Is Raw Unless You Redact First

**[guarantee]** `Serialize` on a `Sensitive` struct, on `SensitiveValue<T, P>`, and on `BypassRedaction<T>` emits the raw value. Deriving `Serialize` does not make serialization redacted; `Sensitive` requires `Serialize` precisely so it can serialize the redacted **clone** it builds internally.

Use raw serialization for APIs, databases, and queues that need the real value. When the output must be safe, go through `.to_redacted().json()`, `.redact()`, or a named logging adapter first.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-derive-selection
- @skill:redactable-field-policies
- @skill:redactable-logging-boundaries
- @skill:redactable-review-checklist
