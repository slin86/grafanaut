from grafanaut.changes import describe_differences


def test_scalar_shows_old_and_new():
    assert describe_differences({"title": "A"}, {"title": "B"}) == "title: 'A' -> 'B'"


def test_tag_list_shows_what_was_added():
    assert describe_differences(
        {"tags": ["prod"]}, {"tags": ["prod", "synced:test"]}
    ) == "tags: +synced:test"


def test_deep_list_only_gets_a_size_hint():
    before = {"panels": [{"id": i} for i in range(12)]}
    after = {"panels": [{"id": i, "title": "x"} for i in range(12)]}
    assert describe_differences(before, after) == "panels: 12 entries, content differs"


def test_nested_dict_names_the_changed_keys():
    assert describe_differences(
        {"jsonData": {"timeout": 30, "tls": True}},
        {"jsonData": {"timeout": 60, "tls": True}},
    ) == "jsonData: timeout"


def test_key_present_on_one_side_only():
    assert describe_differences({"basicAuthUser": "svc"}, {}) == "basicAuthUser: 'svc' -> <not set>"


def test_long_values_are_truncated():
    detail = describe_differences({"q": "x" * 200}, {"q": "y" * 200})
    assert "..." in detail and len(detail) < 150


def test_identical_dicts_report_nothing():
    assert describe_differences({"a": 1}, {"a": 1}) is None


def test_field_list_is_capped():
    before = {f"f{i}": i for i in range(10)}
    after = {f"f{i}": i + 1 for i in range(10)}
    assert "more field(s)" in describe_differences(before, after)
