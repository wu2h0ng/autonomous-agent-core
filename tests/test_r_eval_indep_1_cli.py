from __future__ import annotations

import contextlib
import io
import json
import unittest

from experiments.r_eval_indep_1.cli import main


class DevelopmentOnlyCliTests(unittest.TestCase):
    def invoke(self, *args: str) -> dict[str, object]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(list(args)), 0)
        return json.loads(output.getvalue())

    def test_validate_is_explicitly_not_evidence(self) -> None:
        payload = self.invoke("validate")
        self.assertEqual(payload["evidence_status"], "NOT_EVIDENCE")
        self.assertEqual(payload["provider_fallback"], "FORBIDDEN")
        self.assertEqual(payload["scientific_verdict"], None)

    def test_qualify_dev_is_explicitly_not_evidence(self) -> None:
        payload = self.invoke("qualify-dev")
        self.assertEqual(payload["evidence_status"], "NOT_EVIDENCE")
        self.assertEqual(payload["provider_fallback"], "FORBIDDEN")
        self.assertGreaterEqual(payload["qualified_count"], 7)
        self.assertEqual(payload["qualified_count"], payload["registry_count"])

    def test_no_result_or_provider_command_exists(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["run-rfinal"])


if __name__ == "__main__":
    unittest.main()
