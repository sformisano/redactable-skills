---
name: redactable-core-model
description: "When writing or reviewing Rust code that uses the redactable crate, apply this mental model to choose correct redaction boundaries, traversal patterns, and policy annotations."
metadata:
  skillcatalog/display_name: "Redactable Core Model"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-06-29T10:58:00Z"
---
# Redactable Core Model

Use this skill when writing or reviewing Rust code that uses the `redactable` crate.

`redactable` is a type-directed redaction crate. It does not log by itself. It gives types a safe redacted form so logs, telemetry, error strings, and debug output do not expose sensitive data.

## The Main Rule

Treat redaction as opt-in. Assume fields remain visible unless one of these **crate constraints** applies:

- the field is annotated with `#[sensitive(Policy)]`
- the field's type implements the relevant redactable traversal trait for the output path
- the field is `serde_json::Value`, which is treated as opaque and fully redacted by default when `redactable/json` is enabled

**Authoring guidance (should-do):** If a plain `String` field contains a name, email, token, address, account number, or user-provided text, annotate it with `#[sensitive(Policy)]`. A plain `String` in a `Sensitive` struct is not automatically secret.

**`Redactable` is the certification (0.9+).** Only types with declared redaction implement it: the derives, `SensitiveValue` / `NotSensitiveValue`, `serde_json::Value`, and std containers of those. Container certification forwards only when the contents are also certified, including `VecDeque`, arrays, tuples up to four elements, `Mutex`, and `RwLock` in 0.10+. A bare `String` or scalar has no `.redact()` and cannot be certified as redacted output — those calls are compile errors that point you at the derives. If the compiler says a value has no declared redaction behavior, derive or wrap; do not hand-implement the hidden machinery traits.

**Annotate fields, not enum variants.** `#[sensitive(...)]` / `#[not_sensitive]` on an enum *variant* is a compile error (before 0.8 it was silently ignored — code migrated from older versions may carry this bug).

## Two Output Paths

Use `Sensitive` for structured data.

```rust
#[derive(Clone, redactable::Sensitive)]
struct User {
    id: u64,
    #[sensitive(redactable::Email)]
    email: String,
}
```

Call `.redact()` to get another `User` with sensitive leaves changed. Use this path for JSON, structured logging, stored events, aggregate data, handler payloads, and values that should keep their shape.

Use `SensitiveDisplay` for text.

```rust
#[derive(thiserror::Error, redactable::SensitiveDisplay)]
enum LoginError {
    #[error("login failed for {email}")]
    Failed {
        #[sensitive(redactable::Email)]
        email: String,
    },
}
```

Call `.redacted_display()` to get redacted text. Use this path for errors, display messages, flat log lines, and anything with a human-readable template.

`SensitiveDisplay` generates `RedactableWithFormatter`, `ToRedactedOutput`, conditional `Debug`, and optional slog/tracing integrations for display output. It does not generate `RedactableWithMapper`, `Redactable`, normal Rust `Display`, or `Error`. If callers need ordinary `Display` or `Error`, pair it with `thiserror::Error`, `displaydoc::Display`, or the project's normal display/error derive.

## How Traversal Works

Apply these rules when reasoning about `Sensitive` field traversal:

- **[guarantee]** Do not annotate standard leaves (`String`, numbers, booleans, time values) that are not sensitive—the crate passes them through unchanged.
- **[guarantee]** Do not annotate nested types that derive `Sensitive`—the crate applies their own field policies automatically.
- **[guarantee]** Rely on `Option`, `Vec`, `VecDeque`, arrays, tuples up to four elements, `Box`, `Arc`, `Rc`, `Result`, maps, sets, `Cell`, `RefCell`, `Mutex`, and `RwLock` to delegate to their contents—the crate handles this.
- **[guarantee]** Ignore `PhantomData<T>`—the crate skips it and does not require `T` to implement redactable traits.
- **[heuristic]** Assume nested `SensitiveDisplay` types will be redacted when referenced from `SensitiveDisplay` templates—verify the template actually interpolates them.

### Anti-pattern: annotating a nested Sensitive type

```rust
// WRONG — tries to apply one policy to the nested type instead of walking it
#[derive(Clone, redactable::Sensitive)]
struct Account {
    #[sensitive(redactable::Pii)]  // Do NOT do this
    user: User,
}

// CORRECT — let User's own annotations govern its fields
#[derive(Clone, redactable::Sensitive)]
struct Account {
    user: User,  // unannotated; User's policies apply
}
```

Current redactable usually rejects the wrong pattern with a `PolicyApplicable` trait-bound error because nested `Sensitive` structs are not policy-applicable leaves. Do not treat that error as a reason to add a wrapper or escape hatch; remove the outer annotation so the nested type's own `Sensitive` traversal runs.

### Anti-pattern: leaking sensitive values through format!/logging

```rust
// WRONG — bypasses redaction; raw email appears in logs
fn log_login(user: &User) {
    println!("Login attempt: {}", user.email);
    tracing::info!("user email: {}", user.email);
}

// CORRECT — use the tracing helper for structural Sensitive values
use redactable::tracing::TracingRedactedDebugExt;

fn log_login(user: &User) {
    tracing::info!(user = user.tracing_redacted_debug(), "login attempt");
}
```

**Must-do:** Never pass a sensitive field directly to `format!`, `println!`, `dbg!`, `to_string()`, or a logging macro. Always call `.redact()`, `.redacted_display()`, or the tracing-specific `.tracing_redacted_debug()` helper first.

If one type needs both structural traversal and redacted display formatting, derive both with `#[sensitive(dual)]`. The missing-pair compile-time guard works for non-generic types; generic dual types need convention and tests because that guard does not currently fire the same way.

## Template

Copy and adapt this skeleton for new structs:

```rust
#[derive(Clone, redactable::Sensitive)]
struct MyRecord {
    // visible leaf
    id: u64,

    #[sensitive(redactable::Pii)]
    full_name: String,

    #[sensitive(redactable::Email)]
    backup_email: Option<String>,

    // nested Sensitive type — unannotated
    address: Address,

    #[sensitive(redactable::Pii)]
    aliases: Vec<String>,

    // opaque JSON — redacted by default with redactable/json
    metadata: serde_json::Value,
}

// Dual derive: both .redact() and .redacted_display() available
/// Address in {country}
#[derive(Clone, redactable::Sensitive, redactable::SensitiveDisplay)]
#[sensitive(dual)]
struct Address {
    #[sensitive(redactable::Pii)]
    street: String,
    country: String,
}
```

## Where Redaction Belongs

Redact at the boundary where data leaves normal program flow:

- logging
- telemetry
- error display
- debug output
- generated support dumps
- ad hoc diagnostic output

**Must-do:** Do not replace raw application data with redacted data before persistence, API calls, queues, or business logic unless that is the actual product behavior. Redaction is for safe output, not for mutating source-of-truth data.

## What To Check

When writing or reviewing code (must-do unless noted):

- Every type that may be logged **must** derive the appropriate redactable derive for its output path or be wrapped at the logging boundary.
- Every sensitive leaf **must** have `#[sensitive(Policy)]`.
- Every use of `#[not_sensitive]` **must** be easy to justify.
- Raw `format!`, `to_string()`, `println!`, `dbg!`, and direct logging APIs **must not** carry sensitive values.
- Structural `Sensitive` values logged through tracing **must** use `.tracing_redacted_debug()` or an equivalent redacted wrapper; raw `String` values do not satisfy that helper's bounds.
- Serialization is not redaction. If redacted JSON is needed, serialize the redacted form.

## Cross-References

- @skill:redactable-derive-selection — use when choosing between Sensitive, SensitiveDisplay, or dual
- @skill:redactable-field-policies — use when selecting or creating a Policy type
- @skill:redactable-logging-boundaries — use when wiring redaction into logging/tracing infrastructure
- @skill:redactable-review-checklist — use for a full pre-merge review pass
