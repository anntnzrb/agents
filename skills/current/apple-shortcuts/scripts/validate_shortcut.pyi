type ValidationError = tuple[int, str, str]

def validate(
    plist: dict[str, object],
    allowed_ids: set[str],
    allowed_glyph_ids: set[int] | None = None,
    allowed_icon_colors: set[int] | None = None,
    unavailable_ids: dict[str, str] | None = None,
    unavailable_parameter_keys: dict[str, dict[str, str]] | None = None,
    toolkit_parameter_schemas: dict[str, set[str]] | None = None,
    toolkit_parameter_enum_cases: dict[str, dict[str, set[str]]] | None = None,
    toolkit_parameter_boolean_keys: dict[str, set[str]] | None = None,
    workflow_trigger_catalog: dict[str, object] | None = None,
    target_macos_major: int | None = None,
) -> tuple[list[str], ValidationError | None]: ...
