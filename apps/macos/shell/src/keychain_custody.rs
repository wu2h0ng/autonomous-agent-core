/// Keychain custody for provider keys (ADR-0058).
///
/// The shell is the only process that reads Keychain items. The renderer can
/// only set or clear a provider key (write-only inbound); the value is never
/// read back through IPC. Environment variables take precedence when the
/// daemon is started outside the shell.

use std::env;

pub const KEYCHAIN_SERVICE: &str = "com.agent-os.runtime";
pub const PROVIDER_KEY_ACCOUNT: &str = "provider-api-key";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CustodyStatus {
    Present,
    Absent,
    EnvOverride,
}

/// Read the effective provider key for the configured provider:
/// environment wins, otherwise the Keychain item.
pub fn effective_provider_key(
    env_name: &str,
    keyring: Option<&dyn KeyValueStore>,
) -> Option<String> {
    if let Ok(value) = env::var(env_name) {
        if !value.is_empty() {
            return Some(value);
        }
    }
    keyring.and_then(|store| store.get_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT))
}

/// Status view that never exposes the key value.
pub fn custody_status(
    env_name: &str,
    keyring: Option<&dyn KeyValueStore>,
) -> CustodyStatus {
    if let Ok(value) = env::var(env_name) {
        if !value.is_empty() {
            return CustodyStatus::EnvOverride;
        }
    }
    match keyring.map(|store| store.get_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)) {
        Some(Some(_)) => CustodyStatus::Present,
        _ => CustodyStatus::Absent,
    }
}

pub trait KeyValueStore {
    fn set_secret(&self, service: &str, account: &str, value: &str) -> Result<(), String>;
    fn get_secret(&self, service: &str, account: &str) -> Option<String>;
    fn delete_secret(&self, service: &str, account: &str) -> Result<(), String>;
}

/// Real Keychain-backed store (keyring crate, Security framework).
pub struct KeychainStore;

impl KeyValueStore for KeychainStore {
    fn set_secret(&self, service: &str, account: &str, value: &str) -> Result<(), String> {
        let entry = keyring::Entry::new(service, account)
            .map_err(|e| format!("keychain entry: {e}"))?;
        entry
            .set_password(value)
            .map_err(|e| format!("keychain set: {e}"))
    }

    fn get_secret(&self, service: &str, account: &str) -> Option<String> {
        let entry = keyring::Entry::new(service, account).ok()?;
        entry.get_password().ok()
    }

    fn delete_secret(&self, service: &str, account: &str) -> Result<(), String> {
        let entry = keyring::Entry::new(service, account)
            .map_err(|e| format!("keychain entry: {e}"))?;
        entry
            .delete_credential()
            .map_err(|e| format!("keychain delete: {e}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::collections::HashMap;

    #[derive(Default)]
    struct MemoryStore {
        items: RefCell<HashMap<(String, String), String>>,
    }

    impl KeyValueStore for MemoryStore {
        fn set_secret(&self, service: &str, account: &str, value: &str) -> Result<(), String> {
            self.items
                .borrow_mut()
                .insert((service.to_string(), account.to_string()), value.to_string());
            Ok(())
        }
        fn get_secret(&self, service: &str, account: &str) -> Option<String> {
            self.items
                .borrow()
                .get(&(service.to_string(), account.to_string()))
                .cloned()
        }
        fn delete_secret(&self, service: &str, account: &str) -> Result<(), String> {
            self.items
                .borrow_mut()
                .remove(&(service.to_string(), account.to_string()));
            Ok(())
        }
    }

    #[test]
    fn environment_variable_wins_over_keychain() {
        let store = MemoryStore::default();
        store
            .set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, "keychain-value")
            .unwrap();
        unsafe {
            env::set_var("AGENT_OS_PROVIDER_TEST_KEY", "env-value");
        }
        assert_eq!(
            effective_provider_key("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            Some("env-value".to_string())
        );
        assert_eq!(
            custody_status("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            CustodyStatus::EnvOverride
        );
        unsafe {
            env::remove_var("AGENT_OS_PROVIDER_TEST_KEY");
        }
    }

    #[test]
    fn keychain_value_is_used_when_environment_absent() {
        let store = MemoryStore::default();
        store
            .set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, "keychain-value")
            .unwrap();
        unsafe {
            env::remove_var("AGENT_OS_PROVIDER_TEST_KEY");
        }
        assert_eq!(
            effective_provider_key("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            Some("keychain-value".to_string())
        );
        assert_eq!(
            custody_status("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            CustodyStatus::Present
        );
    }

    #[test]
    fn absent_keychain_and_env_report_absent_without_value() {
        let store = MemoryStore::default();
        unsafe {
            env::remove_var("AGENT_OS_PROVIDER_TEST_KEY");
        }
        assert_eq!(
            custody_status("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            CustodyStatus::Absent
        );
        assert_eq!(
            effective_provider_key("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)),
            None
        );
    }

    #[test]
    fn clear_removes_the_item() {
        let store = MemoryStore::default();
        store
            .set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, "secret")
            .unwrap();
        store
            .delete_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)
            .unwrap();
        assert_eq!(custody_status("AGENT_OS_PROVIDER_TEST_KEY", Some(&store)), CustodyStatus::Absent);
    }
}
