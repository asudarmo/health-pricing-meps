import pytest

import health_pricing.data.download as download_module
from health_pricing.data.download import MANIFEST, DownloadSizeError, RawFile, download_one


def test_manifest_keys_are_unique():
    keys = [raw_file.key for raw_file in MANIFEST]
    assert len(keys) == len(set(keys))


def test_manifest_filenames_are_unique():
    filenames = [raw_file.filename for raw_file in MANIFEST]
    assert len(filenames) == len(set(filenames))


def test_manifest_has_both_years_of_fyc_and_each_event_file():
    keys = {raw_file.key for raw_file in MANIFEST}
    for stem in ["fyc", "office_based", "outpatient", "inpatient"]:
        for year in ["2022", "2023"]:
            assert f"{stem}_{year}" in keys


def test_manifest_entries_have_positive_expected_size():
    for raw_file in MANIFEST:
        assert raw_file.expected_size > 0
        assert raw_file.url.startswith("https://meps.ahrq.gov/")


def test_download_one_raises_on_existing_file_size_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(download_module, "RAW_DIR", tmp_path)
    raw_file = RawFile("fake", "HC-000", "https://example.invalid/fake.zip", expected_size=100)
    raw_file.destination.write_bytes(b"short")

    with pytest.raises(DownloadSizeError):
        download_one(raw_file)


class _FakeStreamingResponse:
    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self._content


def test_download_one_raises_and_cleans_up_on_post_download_size_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(download_module, "RAW_DIR", tmp_path)
    raw_file = RawFile("fake", "HC-000", "https://example.invalid/fake.zip", expected_size=100)
    monkeypatch.setattr(
        download_module.requests, "get", lambda *args, **kwargs: _FakeStreamingResponse(b"short")
    )

    with pytest.raises(DownloadSizeError):
        download_one(raw_file)

    assert not raw_file.destination.exists()
    assert not raw_file.destination.with_suffix(".zip.part").exists()
