// Wave 2c posture helpers shared by the shell (currently a placeholder for
// native-side posture logic; the Ask/Observe projections live in the renderer
// as typed Surface consumers).

/// Bounded notification payload: a short summary string that must never
/// contain provider keys, tokens, or raw message content.
pub fn bounded_summary(capability_or_kind: &str, detail: Option<&str>) -> String {
    let mut summary = capability_or_kind.to_string();
    if let Some(detail) = detail {
        if detail.len() > 80 {
            summary.push_str(": ");
            summary.push_str(&detail[..80]);
        } else {
            summary.push_str(": ");
            summary.push_str(detail);
        }
    }
    summary
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_summary_truncates_long_details() {
        let long = "x".repeat(500);
        let summary = bounded_summary("approval_required", Some(&long));
        assert_eq!(summary.len(), "approval_required: ".len() + 80);
        assert!(!summary.contains(&long[..120]));
    }

    #[test]
    fn bounded_summary_never_includes_secrets() {
        let summary = bounded_summary("daemon_restarted", None);
        assert!(!summary.contains("sk-"));
        assert!(!summary.contains("Bearer"));
    }
}
