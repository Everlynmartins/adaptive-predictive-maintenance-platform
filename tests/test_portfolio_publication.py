"""Offline checks for public documentation, reviewed assets and exclusions."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_documentation_relative_links_exist():
    files = ["README.md", "docs/portfolio_case_study.md",
             "docs/portfolio_publication.md", "docs/assets/README.md"]
    for name in files:
        source = ROOT / name
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
            if target.startswith(("https://", "http://", "#")):
                continue
            assert (source.parent / target.split("#")[0]).is_file(), (name, target)


def test_reviewed_images_match_manifest_and_originals():
    assets = ROOT / "docs/assets"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 12
    for item in manifest:
        content = (assets / item["file"]).read_bytes()
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        source = ROOT / item["source"]
        if not source.is_file():
            source = ROOT / "portfolio/prints" / item["source"]
        # Original screenshot intake is intentionally absent from public clones.
        if source.is_file():
            assert content == source.read_bytes()


def test_private_inputs_are_ignored_without_hiding_public_assets():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for folder in ("src", "configs", "data", "reports", "infra/aws"):
        assert f"{folder}/** -text" in attributes
    paths = ["portfolio/prints/comparison.csv", "portfolio/prints/print1.pdf",
             ".env", ".env.production", "credentials.json", "private.key",
             "infra/aws/terraform.tfstate", "infra/aws/terraform.tfstate.backup",
             "infra/aws/terraform.tfvars", "infra/aws/lab.tfplan",
             "data/processed/fd001/validation.parquet", "standards/SAE.pdf"]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT, input=("\0".join(paths) + "\0").encode(), capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.decode().rstrip("\0").split("\0")) == set(paths)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "docs/assets/screenshots/dashboard_main.png",
         "infra/aws/terraform.tfvars.example"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_readme_does_not_link_missing_gif_or_imported_csv():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "comparison.csv" not in readme
    assert not re.search(r"!\[[^\]]*\]\([^)]*\.gif\)", readme)
    assert readme.count("```mermaid") == 3
    assert "Neural models remain outside fusion" in readme
