"""Docs stay navigable: every relative Markdown link points at a file that exists."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
SKIP = ("tests/fixtures/",)  # planted content for the review skill, not docs


def markdown_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.md")
            if ".git" not in p.parts and not p.relative_to(ROOT).as_posix().startswith(SKIP)]


class DocsLinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        broken = []
        for md in markdown_files():
            for target in LINK.findall(md.read_text(encoding="utf-8")):
                if target.startswith(("http:", "https:", "mailto:", "#")):
                    continue
                if not (md.parent / target.split("#")[0]).exists():
                    broken.append(f"{md.relative_to(ROOT).as_posix()} -> {target}")
        self.assertEqual(broken, [])

    def test_every_doc_is_in_the_index(self):
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        for md in (ROOT / "docs").rglob("*.md"):
            rel = md.relative_to(ROOT / "docs").as_posix()
            if rel != "README.md":
                self.assertIn(f"]({rel})", index, f"add docs/{rel} to docs/README.md")


if __name__ == "__main__":
    unittest.main()
