from health_pricing.data.download import MANIFEST


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
