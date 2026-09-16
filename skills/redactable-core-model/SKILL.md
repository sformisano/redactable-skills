---
name: redactable-core-model
description: "When writing or reviewing Rust code that uses the redactable crate, apply this mental model to choose correct redaction boundaries, traversal patterns, and policy annotations."
metadata:
  skillcatalog/display_name: "Redactable Core Model"
  skillcatalog/author: "Salvatore Formisano"
  skillcatalog/created_at: "2026-04-29T15:18:46Z"
  skillcatalog/updated_at: "2026-09-16T00:00:00Z"
---
# Redactable Core Model

Targets `redactable` 0.13. Earlier versions differ on almost every point below; see [Migrating Old Code](#migrating-old-code).

`redactable` is a type-directed redaction crate. It does not log by itself. It gives types a safe redacted form so logs, telemetry, error strings, and debug output do not expose sensitive data.

## The Main Rule

**Every field must declare what redaction means for it.** Redaction is not opt-in: a field with no declaration is a compile error, not a passthrough.

A field satisfies the rule in one of three ways:

- `#[sensitive(Policy)]` — apply a policy to this leaf
- `#[not_sensitive]` — this field is public; pass it through unchanged
- its type declares its own behavior — a nested derive, `SensitiveValue<T, P>`, `BypassRedaction<T>`, `serde_json::Value`, or a supported container of those

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct User {
    #[not_sensitive]          // required: u64 has no declared behavior on its own
    id: u64,
    #[sensitive(redactable::Email)]
    email: String,
}
```

**Must-do:** Do not read `#[not_sensitive]` as noise you can drop. It is the author's recorded decision that the value is safe to log, and it is the one annotation a reviewer must always challenge.

`Sensitive` and `SensitiveDual` check **every** structural field. `SensitiveDisplay` checks only the fields its template **references**; unreferenced fields need no declaration.

## The Five Derives

| Derive | Produces | Requires |
|---|---|---|
| `Sensitive` | redacted JSON | `Clone + Serialize` |
| `SensitiveDisplay` | redacted template text | a template |
| `SensitiveDual` | both | `Clone + Serialize` and a template |
| `NotSensitive` | raw JSON, declared public | `Serialize` |
| `NotSensitiveDisplay` | raw `Display` text, declared public | `Display` |

All five implement `ToRedacted`. Call `.to_redacted()` at a logging boundary and read the result with `.text()` or `.json()`; both always answer, converting when the producer built only the other representation.

```rust
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Payment {
    #[not_sensitive]
    id: u64,
    #[sensitive(redactable::CreditCard)]
    card: String,
}
```

`.redact()` returns another `Payment` with sensitive leaves changed. `.to_redacted().json()` returns the redacted JSON. Use `Sensitive` for structured data: events, payloads, records, anything that should keep its Rust shape.

```rust
#[derive(thiserror::Error, redactable::SensitiveDisplay)]
#[error("login failed for {email}")]
struct LoginError {
    #[sensitive(redactable::Email)]
    email: String,
}
```

`.redacted_display()` returns redacted text. Use `SensitiveDisplay` for errors, display messages, and flat log lines.

**Must-do:** `SensitiveDisplay` does not generate ordinary `Display` or `Error`. Pair it with `thiserror::Error` or `displaydoc::Display` when callers need those — and see [Errors Leak Through Ordinary Display](#errors-leak-through-ordinary-display), because that pairing creates a raw output path.

## Generated Debug Is Redacted Everywhere

**[guarantee]** The three sensitive derives generate `Debug`. That `Debug` is redacted in every build mode: production, your crate's `cfg(test)`, and with redactable's own `testing` feature. There is no build that reveals raw values through it.

**[guarantee]** The shape differs by derive, and only one of them is a flat placeholder:

| Derive | Generated `Debug` |
|---|---|
| `Sensitive` | struct shape, with a fixed `"[REDACTED]"` per annotated field — whatever the policy |
| `SensitiveDisplay` | the rendered redacted **template** |
| `SensitiveDual` | the rendered redacted **template** |

```rust
use redactable::{CreditCard, Sensitive, SensitiveDisplay};

#[derive(Clone, serde::Serialize, Sensitive)]
struct Payment { #[not_sensitive] id: u64, #[sensitive(CreditCard)] card: String }

#[derive(SensitiveDisplay)]
#[error("payment {id} on card {card}")]
struct PaymentFailed { #[not_sensitive] id: u64, #[sensitive(CreditCard)] card: String }

let card = "4111111111111234".to_owned();

// Sensitive: flat placeholder, policy output not shown.
assert_eq!(
    format!("{:?}", Payment { id: 7, card: card.clone() }),
    r#"Payment { id: 7, card: "[REDACTED]" }"#,
);

// SensitiveDisplay: the template, carrying real policy output.
assert_eq!(
    format!("{:?}", PaymentFailed { id: 7, card }),
    "payment 7 on card ************1234",
);
```

**Must-do:** Do not read "`Debug` is redacted" as "`Debug` reveals nothing". On the display derives it carries whatever each policy chose to preserve — a card's last four, an email's domain — and renders `#[not_sensitive]` fields raw. Judge it by the policies on the type, not by the derive name.

**[guarantee]** Under `Sensitive`, a `#[not_sensitive]` field and an unannotated declared field print through their own `Debug`. A `serde_json::Value` field therefore shows its **raw contents** even though `.redact()` collapses it to `"[REDACTED]"`. Do not treat generated `Debug` as a complete redaction boundary for opaque leaves.

`NotSensitive` and `NotSensitiveDisplay` generate no `Debug`. Derive it yourself when you need it.

## How Traversal Works

- **[guarantee]** Nested types that derive redaction apply their own field policies. Leave the outer field unannotated.
- **[guarantee]** `Option`, `Vec`, `VecDeque`, arrays, tuples up to four elements, `Box`, `Arc`, `Rc`, `Result`, `Cell`, `RefCell`, `Mutex`, `RwLock`, maps, and sets delegate to their contents — and forward the declaration requirement to them. A `Vec<String>` is not declared; a `Vec<User>` is.
- **[guarantee]** Map keys are never redacted. Only values are.
- **[guarantee]** `PhantomData<T>` is skipped and imposes nothing on `T`.
- **[guarantee]** `serde_json::Value` is an opaque leaf that redacts fully to `"[REDACTED]"`, annotated or not.
- **[guarantee]** Sets collapse: if two elements redact to the same value, the set shrinks. Use `Vec` when cardinality matters.
- **[guarantee]** A container implementing `Drop` is unsupported by `Sensitive` and `SensitiveDual`. It usually fails with E0509 — but a container whose fields are all `Copy` **compiles**, and then `.redact()` drops the consumed original and later drops the replacement. A `Drop` that zeroizes a buffer or decrements a handle count runs twice, with no diagnostic. Do not derive redaction on a type with a destructor.
- **[heuristic]** Assume nested `SensitiveDisplay` types are redacted when referenced from a template — verify the template actually interpolates them.

### Anti-pattern: annotating a nested declared type

<!-- harness-expect: PolicyField<Pii> -->
```rust,compile_fail
// WRONG — tries to apply one policy to a whole struct
#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Account {
    #[sensitive(redactable::Pii)]  // Do NOT do this
    user: User,
}
```

```rust
// CORRECT — let User's own annotations govern its fields
use redactable::Redactable;

#[derive(Clone, serde::Serialize, redactable::Sensitive)]
struct Account {
    user: User,  // unannotated; User's policies apply
}

let account = Account { user: User { id: 7, email: "alice@example.com".into() } };
assert_eq!(account.redact().user.email, "al***@example.com");
```

The wrong form fails with an unsatisfied `PolicyField<Pii>` bound. Remove the outer annotation; do not reach for a wrapper or escape hatch to make the error go away.

### Anti-pattern: leaking through format!/logging

<!-- harness-setup
let user = User { id: 7, email: "alice@example.com".into() };
-->
```rust
use redactable::tracing::TracingRedactedDebugExt;

// WRONG — this compiles, which is exactly the problem: nothing stops the raw
// value reaching the sink. Interpolating the field is the same leak.
let line = format!("user email: {}", user.email);
assert_eq!(line, "user email: alice@example.com"); // raw address, straight to the log

// CORRECT — redact before the value reaches the subscriber
tracing::info!(user = user.tracing_redacted_debug(), "login attempt");
```

**Must-do:** Never pass a sensitive field directly to `format!`, `println!`, `dbg!`, `to_string()`, or a logging macro. Go through `.to_redacted()`, `.redact()`, `.redacted_display()`, or a named logging adapter first.

### Errors Leak Through Ordinary Display

No derive in this crate generates ordinary `Display`. So whatever supplies it — `thiserror`, `displaydoc`, `derive_more`, `strum`, or a handwritten `impl` — renders the **raw** fields, and `format!("{value}")` compiles.

The `thiserror` pairing is the sharpest version, because both read the same `#[error("...")]` template and produce different text from it:

<!-- harness-setup
#[derive(thiserror::Error, redactable::SensitiveDisplay)]
#[error("login failed for {email}")]
struct LoginError {
    #[sensitive(redactable::Email)]
    email: String,
}
-->
```rust
use redactable::RedactableWithFormatter;  // required to call .redacted_display()

let err = LoginError { email: "alice@example.com".into() };

assert_eq!(err.redacted_display().to_string(), "login failed for al***@example.com");
assert_eq!(err.to_string(), "login failed for alice@example.com"); // ← raw
```

**Must-do:** Treat `{err}`, `err.to_string()`, and any error chain that formats through `Display` (`anyhow`, `eyre`, `log::error!("{e}")`) as raw output paths. Log errors through `.redacted_display()` or `.to_redacted()`.

### `redact(x)` is not `x.redact()`

The crate also exports a free `redact()` function for low-level traversal. It is bounded on the internal mapper trait rather than on `Redactable`, so it accepts raw leaves — and silently returns them unchanged.

```rust
use redactable::redact;

// The free function: no declaration required, and nothing happens.
assert_eq!(redact("alice@example.com".to_owned()), "alice@example.com");
assert_eq!(redact(vec!["secret".to_owned()]), vec!["secret".to_owned()]);
```

The method `value.redact()` requires `Redactable`, so an undeclared value cannot reach it. The free function has no such gate. The two differ by one character at a call site and have opposite safety properties.

**Must-do:** Never use the free `redact()` at a logging boundary. Use `.to_redacted()`, or the method form on a declared type.

## Template

```rust
use redactable::{Email, Pii, Secret, Sensitive, SensitiveDual, SensitiveValue, Token};

#[derive(Clone, serde::Serialize, Sensitive)]
struct MyRecord {
    #[not_sensitive]
    id: u64,                                   // declared public

    #[sensitive(Pii)]
    full_name: String,

    #[sensitive(Email)]
    backup_email: Option<String>,              // policy applies through the Option

    address: Address,                          // nested derive — unannotated

    api_key: SensitiveValue<String, Token>,    // leaf wrapper carries its own policy

    #[sensitive(Secret)]
    failed_attempts: u32,                      // scalars accept Secret only

    metadata: serde_json::Value,               // opaque; redacts to "[REDACTED]"
}

/// Address in {country}
#[derive(Clone, serde::Serialize, SensitiveDual)]
struct Address {
    #[sensitive(Pii)]
    street: String,
    #[not_sensitive]
    country: String,
}
```

`SensitiveDual` gives `Address` both `.redact()` and `.redacted_display()` from one set of annotations. Its template omits `street`, and `street` is still redacted structurally.

## Where Redaction Belongs

Redact at the boundary where data leaves normal program flow: logging, telemetry, error display, debug output, support dumps, ad hoc diagnostics.

**Must-do:** Do not replace raw application data with redacted data before persistence, API calls, queues, or business logic unless that is the actual product behavior. Redaction produces safe output; it does not mutate source-of-truth data. Serializing a `Sensitive` value directly still serializes the raw fields — that is deliberate, because storage and wire formats usually need the real value.

## What To Check

- Every logged type **must** carry a redactable derive for its output path, or be wrapped at the boundary.
- Every sensitive leaf **must** carry `#[sensitive(Policy)]`. The compiler accepts `#[not_sensitive]` just as readily, so this is the decision it cannot check for you.
- Every `#[not_sensitive]` **must** be justified by what the field actually holds.
- Raw `format!`, `to_string()`, `println!`, `dbg!`, and direct logging APIs **must not** carry sensitive values, including through an error's ordinary `Display`.
- Values reaching a sink **must** go through a named adapter — `.to_redacted()`, `.tracing_redacted_debug()`, `.slog_redacted_json()`, `.redacted_display()` — never the raw value.
- Redacted JSON **must** come from `.to_redacted().json()` or a redacted value, never from serializing the original.

## Migrating Old Code

Code written against 0.10 or earlier will not compile. Three changes need a decision rather than a rename:

| Old form | Replace with |
|---|---|
| `#[derive(Sensitive, SensitiveDisplay)]` + `#[sensitive(dual)]` | `#[derive(SensitiveDual)]` |
| A custom `RedactionPolicy` with no `type Kind` | add `type Kind = TextPolicyKind;` |
| Unannotated raw leaves | a policy or `#[not_sensitive]`, chosen per field |

Everything else the 0.11–0.13 line removed — `ToRedactedOutput`, `RedactedOutput` and its variants, `.redacted_output()`, `.redacted_json()`, `NotSensitiveValue`, `NotSensitiveDebug`, `NotSensitiveJson`, `slog_redacted_display()`, `RedactedValuable` — fails to compile by name, and the replacement is mechanical: the `Bypass*` family for the wrappers, and `.to_redacted()` with `.text()` / `.json()` for the outputs.

**Must-do:** That third row is the one that matters. Decide each unannotated leaf on the data it holds. Blanket-applying `#[not_sensitive]` to clear the errors converts a compile error into a silent leak, and it is the only migration failure the compiler cannot catch.

## Cross-References

- @skill:redactable-derive-selection — use when choosing among the five derives
- @skill:redactable-field-policies — use when selecting or creating a Policy type
- @skill:redactable-wrappers-and-escape-hatches — use for foreign types and deliberate bypasses
- @skill:redactable-logging-boundaries — use when wiring redaction into logging/tracing infrastructure
- @skill:redactable-review-checklist — use for a full pre-merge review pass
