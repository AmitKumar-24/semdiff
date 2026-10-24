"""D-051: the release workflow's gates, asserted instead of reviewed.

Every gate here was added because the preflight found it missing, and a gate that nothing
asserts is one edit away from being gone again -- silently, since a workflow is only exercised
by the thing it guards. A release happens rarely enough that nobody would notice `publish`
losing its `needs:` until the day it published a red commit.

What these tests deliberately do *not* do is restate the workflow. They assert the few
properties that make a release safe: who may publish, what must pass first, that the artifacts
published are the artifacts verified, and that the one third-party action holding the OIDC
token is pinned to a commit. The file is read by `tests/workflows.py`, which refuses any YAML
it does not fully understand (D-051 explains why that is not `pyyaml`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.workflows import WORKFLOWS, YamlSubsetError, load

RELEASE = load(WORKFLOWS / "release.yml")
CI = load(WORKFLOWS / "ci.yml")

#: The publisher, pinned to a commit. v1.14.3: `release/v1`'s head is this commit, and the
#: annotated tag `v1.14.3` (tag object `aef6c9b6e301dc803e1bc9133e9ce67ae9b0906b`, which is what
#: a bare ref lookup returns and is not itself a commit) dereferences to it. Both were read
#: from GitHub's API -- changing this constant means verifying a SHA the same way (D-051).
PUBLISHER = "pypa/gh-action-pypi-publish"
PUBLISHER_SHA = "7245906fb61fa33a13554f9d5fb856fe61758086"
#: PEP 625 normalizes the sdist filename, so the artifacts are spelled with an underscore.
ARTIFACT_STEM = "semdiff_html"
#: The matrix CI covers and the release re-runs: three Pythons against both selectolax lines,
#: which spell a foreign-content attribute key differently (F-027, D-046).
MATRIX = {"python-version": ["3.11", "3.12", "3.13"], "selectolax": ["0.4.13", "1.0.0"]}
SMOKE = "scripts/smoke_install.py"


def job(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict) and name in jobs, f"no {name} job: {sorted(jobs)}"
    found = jobs[name]
    assert isinstance(found, dict)
    return found


def steps(workflow: dict[str, Any], name: str) -> list[dict[str, Any]]:
    found = job(workflow, name)["steps"]
    assert isinstance(found, list)
    return [step for step in found if isinstance(step, dict)]


def script(workflow: dict[str, Any], name: str) -> str:
    """Every `run:` in one job, so a check can be looked for wherever it lives."""
    return "\n".join(str(step.get("run", "")) for step in steps(workflow, name))


def uses(workflow: dict[str, Any], name: str) -> list[str]:
    return [str(step["uses"]) for step in steps(workflow, name) if "uses" in step]


def test_the_release_grants_no_permission_it_does_not_name() -> None:
    """Top-level `{}`, so a job that forgets to ask gets nothing. `contents: read` goes to the
    two jobs that check out -- an empty-permission token is not a working checkout token, which
    would have failed at the first real tag (D-051)."""
    assert RELEASE["permissions"] == {}
    assert job(RELEASE, "build")["permissions"] == {"contents": "read"}
    assert job(RELEASE, "test")["permissions"] == {"contents": "read"}


def test_the_oidc_token_reaches_only_the_job_that_exchanges_it() -> None:
    """`id-token: write` is the credential: it is what PyPI trusts instead of a stored token,
    so every other job must be unable to mint one."""
    assert job(RELEASE, "publish")["permissions"] == {"id-token": "write"}
    for name, spec in RELEASE["jobs"].items():
        if name == "publish":
            continue
        assert "id-token" not in (spec.get("permissions") or {}), name
    # The publish job holds no other grant -- not even `contents`, since it never checks out.
    assert set(job(RELEASE, "publish")["permissions"]) == {"id-token"}


def test_publishing_waits_for_the_build_and_for_the_tests() -> None:
    """The gate. `needs` on both jobs is what stops a tag at a red commit from publishing; CI
    being green elsewhere is not a dependency and must not be treated as one (D-051)."""
    assert job(RELEASE, "publish")["needs"] == ["build", "test"]


def test_the_release_runs_the_whole_suite_itself_on_the_matrix_ci_covers() -> None:
    """The `test` job has to be the real suite, not a subset: a gate that runs fewer tests than
    CI would make a release the least-checked thing in the repository."""
    gate = job(RELEASE, "test")
    assert gate["strategy"]["matrix"] == MATRIX
    assert gate["strategy"]["fail-fast"] is False
    commands = script(RELEASE, "test")
    assert "python -m pytest -q" in commands
    assert "python -m mypy --strict src/semdiff tests scripts" in commands
    # Unqualified: no `-k`, no path, no marker that could quietly narrow what runs.
    assert "pytest -q\n" in commands or commands.rstrip().endswith("pytest -q")


def test_a_release_can_be_rehearsed_by_hand_but_never_started_by_hand() -> None:
    """`workflow_dispatch` exists so the build and every check can be run from a branch. It
    must not be able to publish: a release is a tag, and nothing else."""
    assert RELEASE["on"] == {"push": {"tags": ["v*"]}, "workflow_dispatch": None}
    condition = str(job(RELEASE, "publish")["if"])
    assert "github.event_name == 'push'" in condition
    assert "startsWith(github.ref, 'refs/tags/')" in condition


def test_the_tag_must_match_the_version_of_the_distribution_being_published() -> None:
    """A tag that disagrees with the artifact publishes a version under the wrong number, and
    the number is the one thing a release cannot correct afterwards. Checked against the
    *installed* `semdiff-html` distribution, not an imported module that a leftover editable
    install could satisfy (D-051)."""
    tagged = [
        step
        for step in steps(RELEASE, "build")
        if "refs/tags/" in str(step.get("if", "")) and "run" in step
    ]
    assert len(tagged) == 1, [step.get("name") for step in tagged]
    step = tagged[0]
    # The ref arrives through the environment, never interpolated into the shell.
    assert step["env"] == {"TAG": "${{ github.ref_name }}"}
    commands = str(step["run"])
    assert 'version="${TAG#v}"' in commands
    assert f'test -f "dist/{ARTIFACT_STEM}-${{version}}.tar.gz"' in commands
    assert f'test -f "dist/{ARTIFACT_STEM}-${{version}}-py3-none-any.whl"' in commands
    # Both installs are re-checked against the tag, so neither artifact can carry a stale
    # version into the upload.
    assert commands.count('SEMDIFF_EXPECT_VERSION="$version"') == 2
    assert commands.count(SMOKE) == 2


def test_the_publisher_is_pinned_to_a_verified_commit() -> None:
    """A mutable ref in the one step that holds the OIDC token is the highest-value
    supply-chain target in the repository: whoever can move that ref can publish as this
    project. The SHA is verified against GitHub's API, never guessed (D-051)."""
    pinned = [reference for reference in uses(RELEASE, "publish") if PUBLISHER in reference]
    assert pinned == [f"{PUBLISHER}@{PUBLISHER_SHA}"], pinned
    raw = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for mutable in (f"{PUBLISHER}@release/", f"{PUBLISHER}@v", f"{PUBLISHER}@master"):
        assert mutable not in raw, mutable


def test_the_upload_is_the_artifact_set_the_build_verified() -> None:
    """`publish` downloads from the artifact store rather than building, so it has to prove the
    files are the ones that passed the checks: digests recorded by the build, re-checked here,
    and exactly two files, both named for the tag."""
    building = script(RELEASE, "build")
    assert "sha256sum ./*" in building
    # Outside `dist/`, because the publish step uploads everything in that directory.
    digests = [
        step
        for step in steps(RELEASE, "build")
        if "upload-artifact" in str(step.get("uses", "")) and "SHA256SUMS" in str(step["with"]["path"])
    ]
    assert len(digests) == 1
    assert str(digests[0]["with"]["path"]).startswith("${{ runner.temp }}")
    assert "dist" not in str(digests[0]["with"]["path"]).split("/")

    publishing = script(RELEASE, "publish")
    assert "sha256sum -c ../digests/SHA256SUMS" in publishing
    assert 'test "$(ls dist | wc -l)" = "2"' in publishing
    assert f'test -f "dist/{ARTIFACT_STEM}-${{version}}.tar.gz"' in publishing
    downloaded = {
        str(step["with"]["name"])
        for step in steps(RELEASE, "publish")
        if "download-artifact" in str(step.get("uses", ""))
    }
    assert downloaded == {"dist", "digests"}


def test_both_artifacts_are_installed_and_exercised_before_they_can_be_published() -> None:
    """`twine check` reads metadata and `check_sdist.py` reads a file list; neither runs the
    code. The sdist in particular is what a platform without a matching wheel builds from, and
    nothing installed it before D-051."""
    building = script(RELEASE, "build")
    assert "python -m twine check --strict dist/*" in building
    assert "python scripts/check_sdist.py dist/*.tar.gz" in building
    for source in ("dist/*.whl", "dist/*.tar.gz"):
        assert f"-m pip install {source}" in building, source
    for environment in ("from-wheel", "from-sdist"):
        assert f'python -m venv "$RUNNER_TEMP/{environment}"' in building, environment
        assert f'"$RUNNER_TEMP/{environment}/bin/python" {SMOKE}' in building, environment


def test_one_smoke_test_serves_both_workflows_so_they_cannot_drift() -> None:
    """The packaging job and the release build check the same thing about an installed
    distribution. Two copies of that check would agree only until one was edited."""
    assert SMOKE in script(CI, "package")
    assert SMOKE in script(RELEASE, "build")
    assert (WORKFLOWS.parents[1] / SMOKE).is_file()


def test_the_ci_matrix_is_what_it_was() -> None:
    """D-050 and D-051 both promised to leave it alone: it is the evidence behind the
    cross-version determinism claim (D-046), and narrowing it would quietly retire that."""
    assert set(CI["jobs"]) == {"test", "package", "latest-parser"}
    assert job(CI, "test")["strategy"]["matrix"] == MATRIX
    assert job(CI, "test")["strategy"]["fail-fast"] is False
    assert job(CI, "latest-parser")["if"] == (
        "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    )


def test_two_releases_of_one_tag_cannot_race_and_neither_is_cancelled() -> None:
    """An upload cancelled halfway leaves a version PyPI will not accept a second time."""
    assert RELEASE["concurrency"] == {
        "group": "release-${{ github.ref }}",
        "cancel-in-progress": False,
    }


@pytest.mark.parametrize(
    "unsupported",
    [
        "jobs:\n  build:\n    run: >\n      folded\n",  # a folded scalar
        "jobs:\n  build: &anchor\n    name: x\n",  # an anchor
        "permissions: {contents: read}\n",  # a non-empty flow mapping
        "jobs:\n\tbuild:\n    name: x\n",  # a tab
        "--- \njobs: {}\n",  # a document marker
    ],
)
def test_the_reader_refuses_yaml_it_does_not_understand(unsupported: str, tmp_path: Path) -> None:
    """The reason these tests can be trusted. A reader that guessed at YAML it did not support
    would report a `permissions:` block that is not the one the file declares, which is worse
    than having no assertion at all (D-051)."""
    path = tmp_path / "workflow.yml"
    path.write_text(unsupported, encoding="utf-8")
    with pytest.raises(YamlSubsetError):
        load(path)


def test_the_reader_reads_the_constructs_the_workflows_actually_use(tmp_path: Path) -> None:
    """The other half: refusing everything would also pass the test above."""
    path = tmp_path / "workflow.yml"
    path.write_text(
        'name: Demo\n'
        "# a whole-line comment\n"
        "on:\n"
        '  push:\n    tags: ["v*"]\n'
        "  workflow_dispatch:\n"
        "permissions: {}\n"
        "jobs:\n"
        "  build:\n"
        "    needs: [a, b]\n"
        "    permissions:\n      contents: read\n"
        "    strategy:\n      fail-fast: false\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4  # trailing comment\n"
        "        with:\n          persist-credentials: false\n"
        "      - name: Two lines\n"
        "        run: |\n          echo one\n          echo two  # kept verbatim\n",
        encoding="utf-8",
    )
    document = load(path)
    assert document["on"] == {"push": {"tags": ["v*"]}, "workflow_dispatch": None}
    assert document["permissions"] == {}
    build = document["jobs"]["build"]
    assert build["needs"] == ["a", "b"]
    assert build["permissions"] == {"contents": "read"}
    assert build["strategy"] == {"fail-fast": False}
    assert build["steps"][0] == {
        "uses": "actions/checkout@v4",
        "with": {"persist-credentials": False},
    }
    assert build["steps"][1]["run"] == "echo one\necho two  # kept verbatim\n"
