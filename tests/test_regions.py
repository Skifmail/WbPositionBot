from __future__ import annotations

from app.data.regions import DISTRICTS


def test_districts_exist():
	assert len(DISTRICTS) >= 5


def test_cities_have_dest():
	for d in DISTRICTS:
		assert d.name and d.code
		assert len(d.cities) >= 2
		for c in d.cities:
			assert isinstance(c.dest, int)
