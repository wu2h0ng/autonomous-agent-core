//! Opt-in real Keychain integration test (ADR-0058).
//!
//! Touches the user's login Keychain, so it is skipped unless
//! `AGENT_OS_WAVE2_KEYCHAIN_TEST=1` is set. The Task 7 exit gate performs the
//! authoritative real-Keychain verification during the `.app` launch.

use agent_os_shell_lib::keychain_custody::{
    KeyValueStore, KeychainStore, PROVIDER_KEY_ACCOUNT, KEYCHAIN_SERVICE,
};

#[test]
#[ignore = "opt-in real keychain test: run with AGENT_OS_WAVE2_KEYCHAIN_TEST=1 and --ignored"]
fn real_keychain_set_status_clear_roundtrip() {
    if std::env::var("AGENT_OS_WAVE2_KEYCHAIN_TEST").as_deref() != Ok("1") {
        return;
    }
    let store = KeychainStore;
    let probe = format!("wave2a-integration-probe-{}", std::process::id());
    store
        .set_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT, &probe)
        .expect("keychain set must succeed");
    let value = store
        .get_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)
        .expect("keychain read must succeed");
    assert_eq!(value, probe);
    store
        .delete_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT)
        .expect("keychain clear must succeed");
    assert_eq!(
        store.get_secret(KEYCHAIN_SERVICE, PROVIDER_KEY_ACCOUNT),
        None
    );
}
