"""Tests for the HTTP webhook real-data intervention adapter."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from adapters.http_adapter import HTTPInterventionAdapter


class HTTPAdapterTest(unittest.TestCase):
    def _make(self) -> HTTPInterventionAdapter:
        return HTTPInterventionAdapter(
            n_nodes=3,
            observed_variables=["x0", "x1", "x2"],
            allowed_handles={0, 1},
            safe_value_ranges={0: (-2.0, 2.0), 1: (-1.0, 1.0)},
            observe_url="http://example.com/observe",
            intervene_url="http://example.com/intervene",
            timeout=1.0,
        )

    @patch("adapters.http_adapter.urllib.request.urlopen")
    def test_observe_parses_json_rows(self, mock_urlopen) -> None:
        mock_urlopen.return_value = io.BytesIO(
            json.dumps([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]).encode("utf-8")
        )
        adapter = self._make()
        obs = adapter.observe(2)
        self.assertEqual(obs, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        call = mock_urlopen.call_args[0][0]
        self.assertEqual(call.full_url, "http://example.com/observe?n_samples=2")
        self.assertEqual(call.method, "GET")

    @patch("adapters.http_adapter.urllib.request.urlopen")
    def test_intervene_posts_json_and_returns_sample(self, mock_urlopen) -> None:
        mock_urlopen.return_value = io.BytesIO(
            json.dumps({"sample": [0.5, 0.0, 0.0]}).encode("utf-8")
        )
        adapter = self._make()
        sample = adapter.intervene(0, 0.5)
        self.assertEqual(sample, [0.5, 0.0, 0.0])
        call = mock_urlopen.call_args[0][0]
        self.assertEqual(call.full_url, "http://example.com/intervene")
        self.assertEqual(call.method, "POST")
        self.assertEqual(
            json.loads(call.data.decode("utf-8")),
            {"node": 0, "value": 0.5},
        )

    @patch(
        "adapters.http_adapter.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="http://example.com/intervene",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b"{}"),
        ),
    )
    def test_intervene_returns_none_on_http_error(self, _mock) -> None:
        adapter = self._make()
        self.assertIsNone(adapter.intervene(0, 0.5))


if __name__ == "__main__":
    unittest.main()
