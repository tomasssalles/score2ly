from pathlib import Path

import pytest

from score2ly.pdf import is_vector

SAMPLE_SCORES = Path(__file__).parent.parent / "sample_scores"


@pytest.mark.parametrize("filename", [
    "clair_de_lune-mutopia.pdf",
    "gymnopedie_1-mutopia.pdf",
])
def test_is_vector(filename):
    assert is_vector(SAMPLE_SCORES / filename)


@pytest.mark.parametrize("filename", [
    "consolations-first_edition.pdf",
    "fuer_elise-first_edition.pdf",
    "fuer_elise-leipzig.pdf",
    "kinderscenen-first_edition.pdf",
])
def test_is_scan(filename):
    assert not is_vector(SAMPLE_SCORES / filename)