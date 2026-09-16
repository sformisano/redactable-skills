---
name: redactable-derive-selection
description: "When adding or fixing Rust redactable derives, select the correct derive so redaction, display, debug, and logging traits are generated correctly."
metadata:
  skillcatalog/display_name: "Redactable Derive Selection"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Derive Selection

Targets `redactable` 0.13. Answer these before choosing:

1. Does this type contain sensitive data?
2. Should its redacted output be structured JSON, text, or both?
3. Must it sit inside a `Sensitive` container, a `SensitiveDisplay` template, or both?

## Quick Choice

| Situation | Derive | Also required |
|---|---|---|
| Contains sensitive data, stays structured | `Sensitive` | `Clone`, `Serialize` |
| Contains sensitive data, renders as text | `SensitiveDisplay` | a template; add `thiserror`/`displaydoc` for ordinary `Display` |
| Contains sensitive data, needs both paths | `SensitiveDual` | `Clone`, `Serialize`, a template |
| No sensitive data, used in `Sensitive` containers | `NotSensitive` | `Serialize` |
| No sensitive data, already has `Display` | `NotSensitiveDisplay` | `Display` |

For `Sensitive` and `SensitiveDual`, `Clone` and `Serialize` are not optional convenience bounds: their generated `ToRedacted` clones, redacts, and serializes, and that body is what needs them. `NotSensitive` needs only `Serialize`, and the two display derives need neither. A missing bound is reported on the derive itself.

## `Sensitive`

Use it for domain data, events, request/response payloads, job payloads, records — anything that should keep its Rust shape after redaction.

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct PaymentEvent {
    #[not_sensitive]
    payment_id: u64,
    #[sensitive(redactable::Email)]
    customer_email: String,
    #[sensitive(redactable::CreditCard)]
    card_number: String,
}
```

Expect these generated APIs:

- `Redactable`, so `.redact()` returns the same type with sensitive leaves redacted
- `ToRedacted`, producing **redacted JSON**; read it with `.text()` (compact JSON as text) or `.json()`
- `Debug`, redacted in every build mode
- `slog::Value` + `SlogRedacted` with the `slog` feature
- `TracingRedacted` with the `tracing` feature; `.tracing_redacted_debug()` and `.tracing_redacted()` both apply

**Must-do:** Annotate every field. `Sensitive` checks all of them. An unannotated raw leaf is a compile error naming `Redactable`.

**Must-do:** Do not write a handwritten `ToRedacted` for a type that derives. The generated impl already exists and a second one will not compile. When a different projection is needed, define a separate log-view type.

## `SensitiveDisplay`

Use it for errors, status messages, display-oriented enums, and text output.

```rust
#[derive(thiserror::Error, redactable::SensitiveDisplay)]
enum AuthError {
    #[error("login failed for {email} after {attempts} tries")]
    InvalidLogin {
        #[sensitive(redactable::Email)]
        email: String,
        #[not_sensitive]
        attempts: u32,
    },
}
```

The template comes from `#[error("...")]` (thiserror-style) or a doc comment (displaydoc-style). Annotate the variant's **fields**; `#[sensitive(...)]` on a variant is a compile error.

Expect these generated APIs:

- `RedactableWithFormatter`, so `.redacted_display()` yields redacted text (import the trait to call it)
- `ToRedacted`, producing that same text; `.json()` on it returns `{"message": text}`
- `Debug`, which prints the redacted template text
- feature-gated `slog` and `tracing` support

Only **referenced** fields need a declaration. A field the template omits needs nothing, and a constant template needs no declarations at all.

**Must-do:** Treat this as the one gap in the 0.12 declaration rule. Adding `ssn: String` to an existing `SensitiveDisplay` type produces no error, no annotation requirement, and no prompt — the compiler stops helping precisely where a new sensitive field arrives. Whenever a field is added to a `SensitiveDisplay` type, decide explicitly whether the type should now be `SensitiveDual`, which checks every structural field.

Template rules:
- Named (`{field}`), positional (`{0}`), and debug (`{field:?}`) placeholders are supported.
- Positional placeholders must be contiguous from `0`.
- Dynamic width/precision (`{v:.*}`) and non-Display/Debug specifiers (`{v:x}`) are rejected.
- `{field:?}` on a declared unannotated field uses redacted-display semantics; on a `#[not_sensitive]` field it uses ordinary `Debug`, including quotes and escaping. Prefer `{field}` when plain public text is intended.

Formatting borrows the source and needs no `Clone` on the text/secret path. `RefCell` renders as `<borrowed>` under a conflicting mutable borrow, in both annotated and unannotated positions. `Mutex`/`RwLock` render as `<locked>` under contention, but only on a *declared, unannotated* field — neither accepts `#[sensitive(Policy)]` at all.

Do not expect ordinary `Display` or `Error`, and do not expect `Redactable` / `.redact()`. Use `SensitiveDual` when the type also needs structural traversal.

**Must-do:** When pairing with `thiserror::Error`, remember its `Display` renders the **raw** values. Route error logging through `.redacted_display()` or `.to_redacted()`, never `{err}`.

## `SensitiveDual`

Use it when one type needs both `.redact()` and `.redacted_display()`. It is a single derive, not a combination.

```rust
/// login by {email}
#[derive(Clone, serde::Serialize, redactable::SensitiveDual)]
struct Login {
    #[sensitive(redactable::Email)]
    email: String,
    #[not_sensitive]
    accepted: bool,
}
```

Its single `ToRedacted` carries **both** representations: `.text()` is the template, `.json()` is the redacted object. `.slog_redacted()` and `.tracing_redacted()` use the template; `.slog_redacted_json()` uses the object.

`SensitiveDual` checks **every structural field**, including fields the template omits — that is the difference from `SensitiveDisplay`.

<!-- harness-expect: conflicting implementations of trait `ToRedacted` -->
```rust,compile_fail
// Wrong: two derives generate conflicting ToRedacted, Debug, and slog impls.
/// {0}
#[derive(Clone, serde::Serialize, redactable::Sensitive, redactable::SensitiveDisplay)]
struct EmailAddress(#[sensitive(redactable::Email)] String);
```

```rust
// Right: one derive.
use redactable::ToRedacted;

/// {0}
#[derive(Clone, serde::Serialize, redactable::SensitiveDual)]
struct EmailAddress(#[sensitive(redactable::Email)] String);

assert_eq!(
    EmailAddress("alice@example.com".into()).to_redacted().text(),
    "al***@example.com",
);
```

The old `#[sensitive(dual)]` coordination attribute is rejected with a migration diagnostic naming `SensitiveDual`. Delete the attribute and collapse the two derives into one.

## `NotSensitive`

Use it only when the whole type has no sensitive data but must satisfy redactable bounds.

```rust
#[derive(Clone, Debug, serde::Serialize, redactable::NotSensitive)]
struct RetryConfig {
    max_attempts: u32,
}
```

It generates `Redactable` as a no-op passthrough and `ToRedacted` that emits the type's **raw** `Serialize` output — the derive is your declaration that the whole value is public. It generates no `Debug`; derive it yourself. `#[sensitive(...)]` and `#[not_sensitive]` on its fields are rejected, because the declaration already covers the whole type.

```rust
// Wrong: `email` is user data, so the type is not public. This COMPILES —
// `NotSensitive` records a claim, it does not check it — and then logs the
// raw address.
use redactable::ToRedacted;

#[derive(Clone, serde::Serialize, redactable::NotSensitive)]
struct LoginContext {
    email: String,
}

let logged = LoginContext { email: "alice@example.com".into() }.to_redacted();
assert_eq!(logged.json()["email"], "alice@example.com"); // straight into the log
```

```rust
// Right: derive Sensitive and annotate the leaf.
use redactable::ToRedacted;

#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct LoginContext {
    #[sensitive(redactable::Email)]
    email: String,
}

let logged = LoginContext { email: "alice@example.com".into() }.to_redacted();
assert_eq!(logged.json()["email"], "al***@example.com");
```

**Must-do:** Do not reach for `NotSensitive` to silence a compile error. Nothing will fail — the type will just start logging its raw fields, which is why the wrong version above compiles.

### The dangerous shape: `NotSensitive` around a declared type

`NotSensitive` produces its `ToRedacted` value by serializing the **borrowed original**. No redaction step runs at any depth. A nested field's own `Sensitive` derive does not redact through `Serialize`, so its annotations are inert.

```rust
use redactable::{Email, NotSensitive, Sensitive, ToRedacted};

#[derive(Clone, serde::Serialize, Sensitive)]
struct User {
    #[sensitive(Email)]
    email: String,
}

// WRONG — compiles clean, and logs the raw address.
#[derive(Clone, serde::Serialize, NotSensitive)]
struct Envelope {
    user: User,
}

let envelope = Envelope { user: User { email: "alice@example.com".into() } };
assert_eq!(
    envelope.to_redacted().json(),
    serde_json::json!({"user": {"email": "alice@example.com"}}),
);
```

This is worse than `NotSensitive` on a bare `String`, because the nested type visibly carries `#[sensitive(...)]`. A reviewer scanning for annotations sees protection that never runs.

**Must-do:** `NotSensitive` means *every field at every depth* is public. If any field's type declares redaction, the outer type is not public — derive `Sensitive` instead and leave the nested field unannotated.

## `NotSensitiveDisplay`

Use it for non-sensitive types that already implement `Display`, especially operational enums and typed IDs.

```rust
#[derive(Clone, Debug, displaydoc::Display, redactable::NotSensitiveDisplay)]
enum RetryDecision {
    /// retry
    Retry,
    /// abort
    Abort,
}
```

It works in both paths: passthrough inside `Sensitive` containers, `Redactable` as an explicit public declaration, `Display`-based formatting inside `SensitiveDisplay` templates, and `ToRedacted` emitting the `Display` text. It generates no `Debug`.

Avoid it when the `Display` output could carry user data or secrets. Use `SensitiveDisplay` and annotate the template fields instead.

## Generic Types

A generic type must state its field capabilities at the definition. The compiler checks even when no method is ever called.

| Field use | Required bound |
|---|---|
| Unannotated structural `value: T` | `T: Redactable` |
| Unannotated field referenced by the template | `T: __private::DeclaredFormatting` on the complete field type |
| `#[sensitive(P)]` field used as `{value}` | `T: PolicyDisplay<P>` |
| `#[sensitive(P)]` field used as `{value:?}` | `T: PolicyDebug<P>` |
| `#[sensitive(P)]` field used both ways | both bounds |
| `#[sensitive(P)]` field on a generic `SensitiveDual` | also `__private::PolicyField<P>` for the structural half |
| Explicitly public template field | ordinary `Display`, `Debug`, or both |

```rust
use redactable::{PolicyDisplay, Redactable, Secret, Sensitive, SensitiveDisplay};

#[derive(Clone, serde::Serialize, Sensitive)]
struct Envelope<T: Redactable> {
    value: T,
}

#[derive(SensitiveDisplay)]
#[error("{value}")]
struct Reading<T: PolicyDisplay<Secret>> {
    #[sensitive(Secret)]
    value: T,
}
```

`PolicyDisplay<P>` and `PolicyDebug<P>` describe the policy's *redacted output*, so the payload itself need not implement ordinary `Display` or `Debug`, and a policy field does not need `T: Redactable`. Concrete supported types include scalars under `Secret` and bare typed IPs under `IpAddress`.

For a generic `Sensitive` or `SensitiveDual`, the generated `ToRedacted` needs `Clone + Serialize` on the complete type; `.redact()` can still be available when those bounds are unmet.

## Fixing Compile Errors

**`has no declared redaction behavior` / `Redactable is not implemented`** — a structural field is undeclared.

The diagnostic ends with *"use `SensitiveValue<T, P>` or deliberately declare it public with `BypassRedaction<T>`"*. **That second suggestion is wrong for a field in a struct you own** — it changes the field's type for the sake of a declaration that belongs on the field. Use `#[not_sensitive]`. Decide on the data:

- local sensitive type → derive `Sensitive` or `SensitiveDual` on it
- local public type → derive `NotSensitive` or `NotSensitiveDisplay` on it
- raw leaf → `#[sensitive(Policy)]` or `#[not_sensitive]`
- foreign sensitive leaf → `SensitiveValue<T, P>`
- foreign public field in a struct you own → `#[not_sensitive]`

**`has no declared redacted formatting`** — a referenced template field is undeclared. Same decision, with `SensitiveDisplay` / `NotSensitiveDisplay` on the local types and `#[not_sensitive]` where raw `Display` is safe.

**`PolicyField<P> is not satisfied`** — a policy is annotated on something that is not a policy-applicable leaf, usually a nested derived struct. Remove the annotation.

**`the trait bound X: Serialize/Clone is not satisfied` on the derive** — add the missing `Clone` or `Serialize`.

**`conflicting implementations of trait ToRedacted`** — two derives on one type, or a handwritten `ToRedacted` beside a derive. Use `SensitiveDual`, or move the alternate projection to a separate type.

**`overflow evaluating the requirement` (E0275) on a self-referential field** — the derive inferred a cyclic bound. A procedural macro on stable Rust cannot tell that a crate-qualified, alias-hidden, or mutually recursive field type is the type being derived. Add `#[redactable(recursive)]` to that field; it suppresses the inferred predicate for that field only and still checks the field's actual operations. The diagnostic does not name the attribute, so recognising it is the whole fix.

## Cross-References

- @skill:redactable-core-model
- @skill:redactable-field-policies
- @skill:redactable-wrappers-and-escape-hatches
- @skill:redactable-logging-boundaries
