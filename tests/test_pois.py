# -*- coding: utf-8 -*-
"""Integrity tests for the POI pack (pois/ds2_pois.json). Run: python -m pytest tests/ -q"""
import json, os
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
POIS = os.path.join(ROOT, "pois", "ds2_pois.json")
AREAS = os.path.join(ROOT, "maps", "areas.json")


@pytest.fixture(scope="module")
def doc():
    return json.load(open(POIS, encoding="utf-8"))


def test_top_level_shape(doc):
    assert "meta" in doc and "areas" in doc
    assert "cats" in doc["meta"]


def test_poi_fields_and_coords(doc):
    for ak, area in doc["areas"].items():
        assert "pois" in area, ak
        for p in area["pois"]:
            assert {"id", "cat", "name"} <= set(p), p
            c = p.get("coords")
            if c is not None:
                assert len(c) == 3 and all(isinstance(v, (int, float)) for v in c), p["id"]


def test_no_duplicate_ids(doc):
    ids = [p["id"] for a in doc["areas"].values() for p in a["pois"]]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    assert not dups, f"duplicate ids: {dups}"


def test_area_keys_exist_in_areas_json(doc):
    keys = {x["key"] for x in json.load(open(AREAS, encoding="utf-8"))}
    missing = [ak for ak in doc["areas"] if ak not in keys]
    assert not missing, f"areas not in maps/areas.json: {missing}"


def test_every_poi_cat_declared_in_meta(doc):
    valid = set(doc["meta"]["cats"])
    bad = sorted({p["cat"] for a in doc["areas"].values() for p in a["pois"] if p["cat"] not in valid})
    assert not bad, f"cats used but not declared in meta.cats: {bad}"


def test_forest_loot_named_with_real_items(doc):
    # regression for the object(+0xa0)->ItemLotParam2->items_db pipeline: known Forest chests
    names = {p["name"] for p in doc["areas"]["10_10_forest_of_fallen_giants"]["pois"]}
    assert "Chloranthy Ring" in names
    assert "Titanite Slab" in names


def test_bonfires_canonical_names(doc):
    # regression for the o00_0100(+0xa0)->nameId->bonfirename.fmg link + FMG-text confirmation
    bf = lambda ak: {p["name"] for p in doc["areas"][ak]["pois"] if p["cat"] == "bonfire"}
    assert {"Cardinal Tower", "Soldiers' Rest"} <= bf("10_10_forest_of_fallen_giants")
    assert "McDuff's Workshop" in bf("10_16_the_lost_bastille_sinners_rise_belfry_luna")
    assert "The Blue Cathedral" in bf("10_31_heide_s_tower_of_flame_cathedral_of_blue")


def test_no_provisional_bonfires(doc):
    # invariant: every placed bonfire has a canonical name (nothing left flagged prov)
    prov = [p["name"] for a in doc["areas"].values() for p in a["pois"]
            if p["cat"] == "bonfire" and p.get("prov")]
    assert not prov, f"provisional bonfires remain: {prov}"
