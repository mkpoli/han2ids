import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.prepare_chise import METADATA_PATH, REPOSITORY, prepare
from benchmark.score_expansion import load_specs


REVISION = "c3057f890b4d7a990628873f19274ec33b58a7aa"


def fixture_sources(tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    entries = []
    for name, data in (("IDS-UCS-A.txt", "U+6728\t木\t⿰日日\n"),
                       ("IDS-UCS-B.txt", "U+706B\t火\t⿱人人\n")):
        (source_dir / name).write_text(data, encoding="utf-8")
        entries.append({"name": name, "sha256": hashlib.sha256(data.encode()).hexdigest(),
                        "url": f"https://example.org/{REVISION}/{name}"})
    return source_dir, {"license": "GPL-2.0-or-later", "files": entries}


def test_pinned_metadata_has_complete_immutable_revision():
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["revision"] == REVISION
    assert metadata["license"] == "GPL-2.0-or-later"
    assert metadata["source_url"] == "https://github.com/chise/ids"
    files = metadata["files"]
    assert len(files) == len({entry["name"] for entry in files}) == 18
    for entry in files:
        assert entry["url"] == f"https://raw.githubusercontent.com/chise/ids/{REVISION}/{entry['name']}"
        assert len(entry["sha256"]) == 64
        assert all(c in "0123456789abcdef" for c in entry["sha256"])


def test_valid_specs_parse_and_pin_dictionary_bytes(tmp_path):
    source_dir, metadata = fixture_sources(tmp_path)
    original = copy.deepcopy(metadata)
    out = tmp_path / "specs"
    prepare(source_dir, out, metadata)
    assert metadata == original
    paths = sorted(out.iterdir())
    assert [p.name for p in paths] == [e["name"] + ".json" for e in metadata["files"]]
    for path, entry in zip(paths, metadata["files"]):
        spec = json.loads(path.read_text(encoding="utf-8"))
        assert set(spec) == {"path", "sha256", "provenance", "license"}
        assert not Path(spec["path"]).is_absolute()
        assert (out / spec["path"]).resolve() == source_dir / entry["name"]
        assert spec["sha256"] == entry["sha256"]
        assert spec["provenance"] == entry["url"]
        assert spec["license"] == metadata["license"]
    index, documents = load_specs(paths)
    assert len(documents) == len(index.metadata["sources"]) == 2
    (source_dir / metadata["files"][0]["name"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_specs(paths)


@pytest.mark.parametrize("failure", ["missing", "mismatch"])
def test_bad_source_rejected_before_output_creation(tmp_path, failure):
    source_dir, metadata = fixture_sources(tmp_path)
    source = source_dir / metadata["files"][1]["name"]
    if failure == "missing":
        source.unlink()
    else:
        source.write_text("wrong", encoding="utf-8")
    out = tmp_path / "specs"
    with pytest.raises(ValueError, match="missing|mismatch"):
        prepare(source_dir, out, metadata)
    assert not out.exists()


def test_existing_output_never_overwritten(tmp_path):
    source_dir, metadata = fixture_sources(tmp_path)
    out = tmp_path / "specs"
    out.mkdir()
    sentinel = out / "keep"
    sentinel.write_text("safe", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare(source_dir, out, metadata)
    assert sentinel.read_text(encoding="utf-8") == "safe"
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises(FileExistsError):
        prepare(source_dir, dangling, metadata)


@pytest.mark.parametrize("name", ["../outside.txt", "/tmp/IDS-UCS-A.txt", "IDS-UCS-../escape.txt",
                                   "IDS-UCS-A.txt.json", "IDS-UCS-\\evil.txt", ""])
def test_unsafe_metadata_filename_rejected(tmp_path, name):
    source_dir, metadata = fixture_sources(tmp_path)
    metadata["files"][0]["name"] = name
    with pytest.raises(ValueError, match="filename"):
        prepare(source_dir, tmp_path / "specs", metadata)
    assert not (tmp_path / "specs").exists()


def test_duplicates_and_symlink_sources_rejected(tmp_path):
    source_dir, metadata = fixture_sources(tmp_path)
    duplicate = copy.deepcopy(metadata)
    duplicate["files"].append(copy.deepcopy(duplicate["files"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        prepare(source_dir, tmp_path / "specs", duplicate)
    source = source_dir / metadata["files"][0]["name"]
    source.unlink()
    source.symlink_to(source_dir / metadata["files"][1]["name"])
    with pytest.raises(ValueError, match="regular"):
        prepare(source_dir, tmp_path / "specs", metadata)


def test_home_source_does_not_leak_home_path(tmp_path, monkeypatch):
    home = tmp_path / "home" / "private-user"
    home.mkdir(parents=True)
    source_dir, metadata = fixture_sources(home)
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(ValueError, match="output must be under home"):
        prepare(source_dir, tmp_path / "specs", metadata)
    output = home / "specs"
    prepare(source_dir, output, metadata)
    for path in output.iterdir():
        assert "private-user" not in json.loads(path.read_text(encoding="utf-8"))["path"]


def test_repo_output_must_be_ignored(tmp_path):
    source_dir, metadata = fixture_sources(tmp_path)
    with pytest.raises(ValueError, match="gitignored"):
        prepare(source_dir, REPOSITORY / "not-ignored-chise-specs", metadata)


def test_cli_does_not_allow_unpinned_metadata():
    process = subprocess.run([sys.executable, "-m", "benchmark.prepare_chise", "--metadata", "fake",
                              "--source-dir", "unused", "--output", "unused"],
                             text=True, capture_output=True)
    assert process.returncode != 0
    assert "unrecognized arguments" in process.stderr
