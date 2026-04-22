from pathlib import Path

from src.discovery.classifiers import classify_all
from src.generation import TerraformWriter
from src.settings import GenerationCfg, NamingCfg


def _cfg(out: Path) -> GenerationCfg:
    return GenerationCfg(
        output_dir=str(out),
        provider_version="~> 6.0",
        terraform_version=">= 1.9.0",
        naming=NamingCfg(prefix="{env}-"),
        labels={"managed_by": "tf-out", "environment": "dev"},
    )


def test_writer_emits_provider_and_domain_files(sample_report, tmp_outdir):
    classified = classify_all(sample_report.resources)
    writer = TerraformWriter(_cfg(tmp_outdir), environment="dev")
    out = writer.write(classified)

    assert (out / "provider.tf").exists()
    assert (out / "networking.tf").exists()
    assert (out / "iam.tf").exists()
    # no compute resources in fixture -> no compute.tf
    assert not (out / "compute.tf").exists()


def test_import_script_has_one_line_per_importable(sample_report, tmp_outdir):
    classified = classify_all(sample_report.resources)
    writer = TerraformWriter(_cfg(tmp_outdir), environment="dev")
    out = writer.write(classified)

    script = (out / "import.sh").read_text()
    # 3 fixture resources, all importable
    lines = [line for line in script.splitlines() if line.startswith("terraform import")]
    assert len(lines) == 3


def test_imports_tf_emits_hcl_blocks(sample_report, tmp_outdir):
    classified = classify_all(sample_report.resources)
    writer = TerraformWriter(_cfg(tmp_outdir), environment="dev")
    out = writer.write(classified)

    imports = (out / "imports.tf").read_text()
    assert imports.count("import {") == 3
    # Canonical IDs, not shorthand
    assert 'id = "projects/proj-a/global/networks/vpc-app"' in imports
    assert 'id = "projects/proj-a/regions/us-west1/subnetworks/subnet-west"' in imports
    assert "to = google_compute_network." in imports


def test_hcl_contains_expected_resource_block(sample_report, tmp_outdir):
    classified = classify_all(sample_report.resources)
    writer = TerraformWriter(_cfg(tmp_outdir), environment="dev")
    out = writer.write(classified)

    network_hcl = (out / "networking.tf").read_text()
    assert 'resource "google_compute_network"' in network_hcl
    assert 'name                    = "vpc-app"' in network_hcl
    assert 'resource "google_compute_subnetwork"' in network_hcl
