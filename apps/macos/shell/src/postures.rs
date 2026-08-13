// Wave 2c posture/notification helpers shared by the shell.
//
// Notifications carry ONLY closed, enum-like payloads: a known kind, an
// optional capability id from the closed capability vocabulary, and an
// optional hex digest prefix. Arbitrary detail text is never included, so
// provider keys, tokens, or raw message content cannot leak.

pub const CAPABILITY_VOCABULARY: &[&str] = &[
    "workspace.read",
    "workspace.write",
    "workspace.search",
    "workspace.edit",
    "workspace.apply_patch",
    "workspace.run_tests",
    "workspace.shell",
    "artifact.write",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotificationKind {
    DaemonRestarted,
    ApprovalPending,
    CorrectionHalted,
}

impl NotificationKind {
    pub fn label(self) -> &'static str {
        match self {
            NotificationKind::DaemonRestarted => "daemon restarted",
            NotificationKind::ApprovalPending => "approval pending",
            NotificationKind::CorrectionHalted => "correction halted",
        }
    }
}

/// A bounded notification payload. Only known kinds, a closed-vocabulary
/// capability id, and a hex digest prefix are permitted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundedNotification {
    pub kind: NotificationKind,
    pub capability_id: Option<String>,
    pub digest_prefix: Option<String>,
}

pub fn bounded_capability_id(value: &str) -> Option<String> {
    CAPABILITY_VOCABULARY
        .iter()
        .find(|candidate| **candidate == value)
        .map(|candidate| (*candidate).to_string())
}

pub fn bounded_digest_prefix(value: &str) -> Option<String> {
    let value = value.trim();
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    Some(value[..8].to_string())
}

impl BoundedNotification {
    pub fn approval(capability_id: &str, digest: &str) -> Self {
        Self {
            kind: NotificationKind::ApprovalPending,
            capability_id: bounded_capability_id(capability_id),
            digest_prefix: bounded_digest_prefix(digest),
        }
    }

    pub fn daemon_restarted() -> Self {
        Self {
            kind: NotificationKind::DaemonRestarted,
            capability_id: None,
            digest_prefix: None,
        }
    }

    /// Render the bounded summary for display; safe for any input because it
    /// never echoes arbitrary detail text.
    pub fn summary(&self) -> String {
        let mut summary = self.kind.label().to_string();
        if let Some(capability_id) = &self.capability_id {
            summary.push_str(&format!(" ({capability_id})"));
        }
        if let Some(prefix) = &self.digest_prefix {
            summary.push_str(&format!(" digest:{prefix}"));
        }
        summary
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn approval_payload_bounds_capability_and_digest() {
        let notification =
            BoundedNotification::approval("workspace.edit", &"a".repeat(64));
        assert_eq!(
            notification.capability_id.as_deref(),
            Some("workspace.edit")
        );
        assert_eq!(notification.digest_prefix.as_deref(), Some("aaaaaaaa"));
    }

    #[test]
    fn unknown_capability_and_malformed_digest_are_bounded_away() {
        let notification = BoundedNotification::approval(
            "not-a-capability",
            "not-a-hex-digest",
        );
        assert_eq!(notification.capability_id, None);
        assert_eq!(notification.digest_prefix, None);
    }

    #[test]
    fn summary_never_contains_secret_shaped_text() {
        let notification =
            BoundedNotification::approval("workspace.edit", &"b".repeat(64));
        let summary = notification.summary();
        assert!(!summary.contains("sk-"));
        assert!(!summary.contains("Bearer"));
        assert!(!summary.contains(&"b".repeat(64)));
    }

    #[test]
    fn daemon_restart_payload_has_no_arbitrary_detail() {
        let notification = BoundedNotification::daemon_restarted();
        assert_eq!(notification.summary(), "daemon restarted");
    }
}
