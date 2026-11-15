import json

from cvsearch.domain.models import ExtractedProfile
from cvsearch.llm.client import strict_schema


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_strict_schema_has_no_refs_and_closes_every_object():
    schema = strict_schema(ExtractedProfile)
    assert "$ref" not in json.dumps(schema)
    assert "$defs" not in schema
    for node in _walk(schema):
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_enum_field_keeps_its_description_without_a_ref():
    sector = strict_schema(ExtractedProfile)["properties"]["positions"]["items"]["properties"]["sector"]
    assert "enum" in sector
    assert "sector" in sector["description"].lower()


def test_field_named_like_a_schema_keyword_survives():
    position = strict_schema(ExtractedProfile)["properties"]["positions"]["items"]
    assert "title" in position["properties"]
    assert "title" in position["required"]
