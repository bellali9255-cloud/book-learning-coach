import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = [
    "modes-and-routing.md",
    "teaching-loop.md",
    "state-and-recovery.md",
    "source-ingestion.md",
    "identity-and-migration.md",
    "traceability-and-audit.md",
    "knowledge-invocation.md",
]
TEMPLATES = [
    "toc-guide.template.md",
    "lesson.template.md",
    "reading-notes.template.md",
    "review-cards.template.md",
    "method-card.template.md",
    "scene-index.template.md",
    "work-mapping.template.md",
    "invocation-report.template.md",
]
CHAPTER_ASSETS = [
    "method-card.template.md",
    "scene-index.template.md",
    "work-mapping.template.md",
]


class PackageReferenceTests(unittest.TestCase):
    def test_all_operational_references_exist(self):
        for name in REFERENCES:
            with self.subTest(name=name):
                path = ROOT / "references" / name
                self.assertTrue(path.is_file(), name)
                self.assertGreater(len(path.read_text(encoding="utf-8").strip()), 100)

    def test_markdown_templates_have_stable_id_source_ref_and_untrusted_boundary(self):
        for name in TEMPLATES:
            with self.subTest(name=name):
                text = (ROOT / "assets" / name).read_text(encoding="utf-8")
                self.assertIn("<!-- blc:start {{stable_id}} -->", text)
                self.assertIn("source_block_id:", text)
                self.assertIn("不可信数据", text)

    def test_knowledge_assets_support_chapter_and_book_scopes(self):
        for name in CHAPTER_ASSETS:
            with self.subTest(name=name):
                text = (ROOT / "assets" / name).read_text(encoding="utf-8")
                self.assertIn("scope: {{scope}}", text)
                self.assertIn("chapter_id: {{chapter_id_or_omit}}", text)
                self.assertIn("audit_ref: {{audit_ref}}", text)
                self.assertNotIn("book_audit_status: incomplete", text)

    def test_reading_notes_template_persists_lens_and_display_metadata(self):
        text = (ROOT / "assets" / "reading-notes.template.md").read_text(encoding="utf-8")
        self.assertIn("reading_lens_primary:", text)
        self.assertIn("reading_lens_supporting:", text)
        self.assertIn("display_position:", text)
        self.assertIn("lines:", text)

    def test_references_name_deterministic_helpers(self):
        combined = "\n".join(
            (ROOT / "references" / name).read_text(encoding="utf-8") for name in REFERENCES
        )
        self.assertIn("scripts/progress.py", combined)
        self.assertIn("scripts/asset_store.py", combined)
        self.assertIn("scripts/audit_workspace.py", combined)


class SkillDistributionTests(unittest.TestCase):
    def test_skill_frontmatter_and_entry_mode_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---\n", 2)[1]
        self.assertIn("name: book-learning-coach", frontmatter)
        description = next(
            line.removeprefix("description:").strip()
            for line in frontmatter.splitlines()
            if line.startswith("description:")
        )
        self.assertTrue(description.startswith("Use when"))
        self.assertLess(len(frontmatter), 1024)
        for entry in ("拆这本书", "教我这本书", "调用这本书"):
            self.assertIn(f"| {entry} |", text)
        for mode in ("browse", "intensive", "breakdown"):
            self.assertRegex(text, rf"`{mode}`")

    def test_every_local_resource_referenced_by_skill_exists(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        paths = set(
            re.findall(r"(?<![A-Za-z0-9_.-])((?:references|assets|scripts)/[A-Za-z0-9_.-]+)", text)
        )
        self.assertGreaterEqual(len(paths), 10)
        for relative in paths:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_readme_documents_install_dependency_examples_formats_and_ocr_limit(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("python -m pip install -r requirements.txt", text)
        self.assertIn("jsonschema", text)
        for entry in ("拆这本书", "教我这本书", "调用这本书"):
            self.assertIn(entry, text)
        for extension in ("MD", "TXT", "PDF", "DOCX", "EPUB"):
            self.assertIn(extension, text)
        self.assertIn("OCR", text)
        self.assertIn("python -m unittest discover -s tests -v", text)
        self.assertIn("raw-show", text)

    def test_metadata_license_attribution_and_ignore_rules(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "拆书教练"', metadata)
        self.assertIn("$book-learning-coach", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)

        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        attribution = (ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
        self.assertIn("fangyuan-3149/book-learning-tutor", attribution)
        self.assertIn("mollycall-zmy/book-learning-skill", attribution)
        self.assertIn("MIT", attribution)

        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".cache/", ignore)
        self.assertIn("!tests/fixtures/**", ignore)
        for pattern in ("*.tmp", "*.bak", "*.recovery.*", ".pytest_cache/", ".coverage", "htmlcov/"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main()
