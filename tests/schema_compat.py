"""Small offline test validator for the schema keywords used by this package.

This module is test-only. Production code never imports it: state writes require
the real ``jsonschema`` dependency and fail closed when it is unavailable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping


class ValidationError(ValueError):
    pass


class Draft202012Validator:
    def __init__(self, schema):
        self.schema = schema

    @classmethod
    def check_schema(cls, schema):
        if not isinstance(schema, Mapping) or "$schema" not in schema:
            raise ValidationError("schema must declare $schema")

    def validate(self, instance):
        self._validate(instance, self.schema, "$")

    def _resolve(self, ref):
        if not ref.startswith("#/"):
            raise ValidationError(f"unsupported ref: {ref}")
        node = self.schema
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def _fail(self, path, message):
        raise ValidationError(f"{path}: {message}")

    def _validate(self, value, schema, path):
        if "$ref" in schema:
            return self._validate(value, self._resolve(schema["$ref"]), path)

        if "anyOf" in schema:
            errors = []
            for option in schema["anyOf"]:
                try:
                    self._validate(value, option, path)
                    break
                except ValidationError as exc:
                    errors.append(str(exc))
            else:
                self._fail(path, "did not match anyOf: " + "; ".join(errors))

        if "const" in schema and value != schema["const"]:
            self._fail(path, f"must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            self._fail(path, f"must be one of {schema['enum']!r}")

        expected = schema.get("type")
        if expected is not None:
            allowed = expected if isinstance(expected, list) else [expected]
            if not any(self._matches_type(value, item) for item in allowed):
                self._fail(path, f"expected type {allowed!r}")

        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    self._fail(path, f"missing required property {key!r}")
            if len(value) < schema.get("minProperties", 0):
                self._fail(path, "has too few properties")

            properties = schema.get("properties", {})
            additional = schema.get("additionalProperties", True)
            for key, item in value.items():
                if "propertyNames" in schema:
                    self._validate(key, schema["propertyNames"], f"{path}.<key>")
                if key in properties:
                    self._validate(item, properties[key], f"{path}.{key}")
                elif additional is False:
                    self._fail(path, f"unexpected property {key!r}")
                elif isinstance(additional, Mapping):
                    self._validate(item, additional, f"{path}.{key}")

        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                self._fail(path, "has too few items")
            if schema.get("uniqueItems"):
                seen = []
                for item in value:
                    if item in seen:
                        self._fail(path, "items must be unique")
                    seen.append(item)
            if "items" in schema:
                for index, item in enumerate(value):
                    self._validate(item, schema["items"], f"{path}[{index}]")

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                self._fail(path, "string is too short")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                self._fail(path, f"does not match {schema['pattern']!r}")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                self._fail(path, "is below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                self._fail(path, "is above maximum")
            if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
                self._fail(path, "is not above exclusiveMinimum")

    @staticmethod
    def _matches_type(value, expected):
        mapping = {
            "null": lambda item: item is None,
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "boolean": lambda item: isinstance(item, bool),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        }
        return mapping[expected](value)
