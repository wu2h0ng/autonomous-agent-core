from __future__ import annotations

import contextlib
import io
import json
import unittest
from typing import Any

from experiments.r_eval_indep_1.cli import main


class DevelopmentOnlyCliTests(unittest.TestCase):
    def invoke(self, *args: str) -> dict[str, Any]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(list(args)), 0)
        return json.loads(output.getvalue())

    def test_compile_corpus_dev_is_explicitly_not_evidence(self) -> None:
        payload = self.invoke("compile-corpus-dev")
        self.assertEqual(payload["mode"], "compile-corpus-dev")
        self.assertEqual(payload["evidence_status"], "NOT_EVIDENCE")
        self.assertEqual(payload["provider_fallback"], "FORBIDDEN")
        self.assertEqual(payload["scientific_verdict"], None)
        self.assertEqual(payload["provider_calls"], 0)
        self.assertEqual(payload["result_run"], False)
        self.assertEqual(payload["freeze_status"], "NOT_FROZEN")
        self.assertEqual(payload["run_status"], "NOT_RUN")
        self.assertEqual(payload["case_count"], 74)
        self.assertEqual(payload["harmful_count"], 60)
        self.assertEqual(payload["clean_count"], 14)
        self.assertNotEqual(
            payload["public_cases_sha256"], payload["referee_cases_sha256"]
        )

    def test_verify_corpus_dev_is_explicitly_not_evidence(self) -> None:
        payload = self.invoke("verify-corpus-dev")
        self.assertEqual(payload["mode"], "verify-corpus-dev")
        self.assertEqual(payload["evidence_status"], "NOT_EVIDENCE")
        self.assertEqual(payload["provider_fallback"], "FORBIDDEN")
        self.assertEqual(payload["provider_calls"], 0)
        self.assertEqual(payload["result_run"], False)
        self.assertEqual(payload["qualified_count"], 74)
        self.assertEqual(payload["qualified_count"], payload["case_count"])
        self.assertEqual(len(payload["records"]), 74)

    def test_only_corpus_development_commands_exist(self) -> None:
        for command in ("validate", "qualify-dev", "run-rfinal"):
            with self.subTest(command=command):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        main([command])


if __name__ == "__main__":
    unittest.main()
