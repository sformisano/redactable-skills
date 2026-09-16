//! Shared support types injected into every checked example.
//!
//! This exists so a skill example can say `settings: Settings` without spending
//! four lines defining a type the example is not about. Everything here is
//! glob-imported, so an example that declares its own `User` shadows the one
//! below rather than colliding with it.
//!
//! Keep this small. A large prelude hides the fact that examples are not
//! self-contained, and an agent copying an example out of a skill does not get
//! this file. Types only: values belong in the example or in a
//! `<!-- harness-setup -->` directive.

#![allow(dead_code, unused_imports)]

use redactable::{Email, NotSensitive, NotSensitiveDisplay, Pii, Secret, Sensitive, Token};

/// The canonical user record across these skills: one public field, one
/// policy-annotated leaf. An example that declares its own `User` shadows this.
#[derive(Clone, serde::Serialize, Sensitive)]
pub struct User {
    #[not_sensitive]
    pub id: u64,
    #[sensitive(Email)]
    pub email: String,
}

/// A nested type that declares its own redaction. Use for "leave it unannotated".
#[derive(Clone, serde::Serialize, Sensitive)]
pub struct Settings {
    #[not_sensitive]
    pub theme: String,
}

/// A declared-public config type. Use for `NotSensitive` composition examples.
#[derive(Clone, Debug, serde::Serialize, NotSensitive)]
pub struct RetryConfig {
    pub max_attempts: u32,
}

/// A type from "another crate": no redactable derives, no Serialize.
#[derive(Clone, Debug, Default)]
pub struct ForeignConfig {
    pub timeout_ms: u64,
}

/// A foreign type carrying a sensitive identifier. Use for `SensitiveWithPolicy`.
#[derive(Clone, Debug, Default)]
pub struct MerchantAccount {
    pub id: String,
    pub region: String,
}

/// A minimal custom sink, for `ToRedacted` pipeline examples.
pub trait LogSink {
    fn wants_structure(&self) -> bool;
    fn write_json(&mut self, key: &str, value: serde_json::Value);
    fn write_text(&mut self, key: &str, value: &str);
}

/// A capturing `LogSink` so pipeline examples can assert what was written.
#[derive(Default)]
pub struct CapturingSink {
    pub structured: bool,
    pub written: Vec<String>,
}

impl LogSink for CapturingSink {
    fn wants_structure(&self) -> bool {
        self.structured
    }
    fn write_json(&mut self, key: &str, value: serde_json::Value) {
        self.written.push(format!("{key}={value}"));
    }
    fn write_text(&mut self, key: &str, value: &str) {
        self.written.push(format!("{key}={value}"));
    }
}

/// A discarding slog logger, so slog examples need no drain setup.
pub fn discard_logger() -> slog::Logger {
    slog::Logger::root(slog::Discard, slog::o!())
}

/// Captures what one value emits through slog, so an example can assert on it
/// instead of describing it. Returns the emitted JSON, or emitted text as a
/// JSON string. Adapted from the crate's own `tests/support/slog_capture.rs`.
pub fn capture_slog<V: slog::Value>(value: &V) -> serde_json::Value {
    use std::{cell::RefCell, fmt::Arguments};

    #[derive(Default)]
    struct Capture(RefCell<serde_json::Value>);

    impl slog::Serializer for Capture {
        fn emit_arguments(&mut self, _key: slog::Key, val: &Arguments<'_>) -> slog::Result {
            *self.0.borrow_mut() = serde_json::Value::String(val.to_string());
            Ok(())
        }
        fn emit_str(&mut self, _key: slog::Key, val: &str) -> slog::Result {
            *self.0.borrow_mut() = serde_json::Value::String(val.to_owned());
            Ok(())
        }
        fn emit_serde(&mut self, _key: slog::Key, val: &dyn slog::SerdeValue) -> slog::Result {
            *self.0.borrow_mut() =
                serde_json::to_value(val.as_serde()).unwrap_or(serde_json::Value::Null);
            Ok(())
        }
    }

    static RS: slog::RecordStatic<'static> = slog::record_static!(slog::Level::Info, "");
    let args = format_args!("");
    let record = slog::Record::new(&RS, &args, slog::b!());
    let mut capture = Capture::default();
    value
        .serialize(&record, "value", &mut capture)
        .expect("slog serialization should succeed");
    capture.0.into_inner()
}
