from inspect_ai.model import get_model


def test_cells_resolve_as_moodle_models():
    assert get_model("moodle/openai-cc-gpt-6-luna").name == "openai-cc-gpt-6-luna"
