from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_HTML = REPO_ROOT / "apps" / "workspace" / "prototype" / "index.html"


class WorkspacePrototypeContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = WORKSPACE_HTML.read_text(encoding="utf-8")

    def test_f1_shows_dataproduct_and_knowledgeasset_candidates(self) -> None:
        """F1 must show the product loop beyond trusted Q&A."""
        required_markers = (
            'id="dataProductCandidate"',
            'id="dataProductStatus"',
            'id="dataProductSource"',
            'id="knowledgeAssetCandidate"',
            'id="knowledgeAssetState"',
            'id="knowledgeAssetReview"',
            "DataProduct candidate",
            "KnowledgeAsset candidate",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_f1_keeps_contract_shaped_mock_states_visible(self) -> None:
        for marker in (
            'data-state="loaded"',
            'data-state="blocked"',
            'data-state="insufficient"',
            "const states =",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_workspace_prototype_does_not_import_os_core(self) -> None:
        forbidden_markers = ("agent_os_core", "packages/os_core", "../packages/os_core")
        for marker in forbidden_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)


if __name__ == "__main__":
    unittest.main()
