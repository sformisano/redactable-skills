---
name: redactable-core-model
description: "When writing or reviewing Rust code that uses the redactable crate, apply this mental model to choose correct redaction boundaries, traversal patterns, and policy annotations."
metadata:
  skillcatalog/display_name: "Redactable Core Model"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-05-17T11:10:10Z"
---
# Redactable Core Model

Use this skill when writing or reviewing Rust code that uses the `redactable` crate.

`redactable` is a type-directed redaction crate. It does not log by itself. It gives types a safe redacted form so logs, telemetry, error strings, and debug output do not expose sensitive data.

## The Main Rule

Treat redaction as opt-in. Assume fields remain visible unless one of these **crate constraints** applies:

- the field is annotated with `#[sensitive(Policy)]`
- the field's type implements the relevant redactable traversal trait for the output path
- the field is `serde_json::Value`, which is treated as opaque and fully redacted by default when the `json` feature is enabled

**Authoring guidance (should-do):** If a plain `String` field contains a name, email, token, address, account number, or user-provided text, annotate it with `#[sensitive(Policy)]`. A plain `String` in a `Sensitive` struct is not automatically secret.

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

`SensitiveDisplay` generates `RedactableWithFormatter`, `ToRedactedOutput`, `Debug`, and optional slog/tracing integrations. It does not generate normal Rust `Display` or `Error`. If callers need ordinary `Display` or `Error`, pair it with `thiserror::Error`, `displaydoc::Display`, or the project's normal display/error derive.

## How Traversal Works

Apply these rules when reasoning about `Sensitive` field traversal:

- **[guarantee]** Do not annotate standard leaves (`String`, numbers, booleans, time values) that are not sensitive—the crate passes them through unchanged.
- **[guarantee]** Do not annotate nested types that derive `Sensitive`—the crate applies their own field policies automatically.
- **[guarantee]** Rely on `Option`, `Vec`, `Box`, `Arc`, `Rc`, `Result`, maps, sets, `Cell`, and `RefCell` to delegate to their contents—the crate handles this.
- **[guarantee]** Ignore `PhantomData<T>`—the crate skips it and does not require `T` to implement redactable traits.
- **[heuristic]** Assume nested `SensitiveDisplay` types will be redacted when referenced from `SensitiveDisplay` templates—verify the template actually interpolates them.

### Anti-pattern: annotating a nested Sensitive type

```rust
// WRONG — overrides the nested type's own field-level policies
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

### Anti-pattern: leaking sensitive values through format!/logging

```rust
// WRONG — bypasses redaction; raw email appears in logs
fn log_login(user: &User) {
    println!("Login attempt: {}", user.email);
    tracing::info!("user email: {}", user.email);
}

// CORRECT — use the redacted form at the logging boundary
fn log_login(user: &User) {
    let safe = user.redact();
    tracing::info!("Login attempt: {}", safe.email);
}
```

**Must-do:** Never pass a sensitive field directly to `format!`, `println!`, `dbg!`, `to_string()`, or a logging macro. Always call `.redact()` or `.redacted_display()` first.

If one type needs both structural traversal and redacted display formatting, derive both with `#[sensitive(dual)]`.

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

    // opaque JSON — redacted by default with `json` feature
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

- Every type that may be logged **must** derive one of the redactable derives or be wrapped at the logging boundary.
- Every sensitive leaf **must** have `#[sensitive(Policy)]`.
- Every use of `#[not_sensitive]` **must** be easy to justify.
- Raw `format!`, `to_string()`, `println!`, `dbg!`, and direct logging APIs **must not** carry sensitive values.
- Serialization is not redaction. If redacted JSON is needed, serialize the redacted form.

## Cross-References

- @skill:redactable-derive-selection — use when choosing between Sensitive, SensitiveDisplay, or dual
- @skill:redactable-field-policies — use when selecting or creating a Policy type
- @skill:redactable-logging-boundaries — use when wiring redaction into logging/tracing infrastructure
- @skill:redactable-review-checklist — use for a full pre-merge review pass
