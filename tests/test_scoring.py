"""Eval scoring deterministic checks."""

from __future__ import annotations

from eval.scoring.language import contains_english
from eval.scoring.recast import error_repeated, recast_explicit, recast_present
from eval.scoring.register import check_register_heuristic
from eval.scoring.turn import _count_questions, _count_sentences, parse_tool_calls

# ---------------------------------------------------------------------------
# parse_tool_calls — both surface formats
# ---------------------------------------------------------------------------


class TestParseToolCalls:
    def test_legacy_bracket_format(self):
        text = '¡Hola! [TOOL_CALL: log_turn]{"learner_utterance": "x", "errors": []}'
        calls = parse_tool_calls(text, None)
        assert len(calls) == 1
        assert calls[0]["name"] == "log_turn"
        assert calls[0]["arguments"]["learner_utterance"] == "x"

    def test_function_call_format_json(self):
        text = '¡Hola!\n\nlog_turn({"learner_utterance": "x", "errors": []})'
        calls = parse_tool_calls(text, None)
        assert len(calls) == 1
        assert calls[0]["name"] == "log_turn"
        assert calls[0]["arguments"]["errors"] == []

    def test_function_call_format_python_dict(self):
        # Single quotes — the natural Gemma post-fine-tune output.
        text = (
            "¡Qué bien!\n\nlog_turn({\n"
            "    'learner_utterance': 'Yo fui al tienda y compré mucho frutas.',\n"
            "    'errors': ['al tienda', 'mucho frutas'],\n"
            "    'fluency_indicators': {'words_per_minute': 120}\n"
            "})"
        )
        calls = parse_tool_calls(text, None)
        assert len(calls) == 1
        assert calls[0]["name"] == "log_turn"
        assert calls[0]["arguments"]["learner_utterance"].startswith("Yo fui")
        assert calls[0]["arguments"]["errors"] == ["al tienda", "mucho frutas"]

    def test_python_keyword_not_picked_up(self):
        # `print(...)` should not be misparsed as a tool call.
        text = "Some text. print({'foo': 'bar'})"
        calls = parse_tool_calls(text, None)
        assert calls == []

    def test_no_tool_call(self):
        text = "Just a plain Spanish response with no tool call. ¿Cómo estás?"
        assert parse_tool_calls(text, None) == []

    def test_both_formats_in_same_text_dedupes(self):
        # If the model emits both formats we shouldn't double-count.
        text = (
            'log_turn({"learner_utterance": "x", "errors": []})\n'
            '[TOOL_CALL: log_turn]{"learner_utterance": "x", "errors": []}'
        )
        calls = parse_tool_calls(text, None)
        # The bracket form runs first, then dedup skips the function-call one.
        names = [c["name"] for c in calls]
        assert names.count("log_turn") == 1

    def test_api_tool_calls_preferred(self):
        api_calls = [{"name": "log_turn", "arguments": '{"learner_utterance": "api"}'}]
        text = '[TOOL_CALL: log_turn]{"learner_utterance": "inline"}'
        calls = parse_tool_calls(text, api_calls)
        assert len(calls) == 1
        assert calls[0]["arguments"]["learner_utterance"] == "api"

    def test_api_tool_calls_dict_args(self):
        api_calls = [{"name": "log_turn", "arguments": {"learner_utterance": "direct"}}]
        calls = parse_tool_calls("text", api_calls)
        assert calls[0]["arguments"]["learner_utterance"] == "direct"


# ---------------------------------------------------------------------------
# recast_present
# ---------------------------------------------------------------------------


class TestRecastPresent:
    def test_found(self):
        assert recast_present("El parque está cerca de tu casa.", "está cerca") is True

    def test_missing(self):
        assert recast_present("Muy bien, continúa.", "está cerca") is False

    def test_none_recast_auto_pass(self):
        assert recast_present("Anything goes here.", None) is True

    def test_case_insensitive(self):
        assert recast_present("ESTÁ CERCA de aquí.", "está cerca") is True


# ---------------------------------------------------------------------------
# recast_explicit
# ---------------------------------------------------------------------------


class TestRecastExplicit:
    def test_clean_response(self):
        assert recast_explicit("El parque está cerca. ¿Vas mucho?") is False

    def test_no_se_dice(self):
        assert recast_explicit("No se dice 'es cerca', sino 'está cerca'.") is True

    def test_la_forma_correcta(self):
        assert recast_explicit("La forma correcta es 'está'.") is True

    def test_debes_decir(self):
        assert recast_explicit("Debes decir 'está cerca'.") is True

    def test_error_word(self):
        assert recast_explicit("Hay un error en tu frase.") is True


# ---------------------------------------------------------------------------
# error_repeated
# ---------------------------------------------------------------------------


class TestErrorRepeated:
    def test_repeated(self):
        assert error_repeated("El parque es cerca, qué bonito.", ["es cerca"]) is True

    def test_not_repeated(self):
        assert error_repeated("El parque está cerca.", ["es cerca"]) is False

    def test_empty_forms(self):
        assert error_repeated("Cualquier cosa.", []) is False

    def test_multiple_forms_one_match(self):
        assert error_repeated("Yo soy cerca.", ["es cerca", "soy cerca"]) is True


# ---------------------------------------------------------------------------
# contains_english
# ---------------------------------------------------------------------------


class TestContainsEnglish:
    def test_spanish_only(self):
        assert contains_english("¿Qué haces en tu tiempo libre?") is False

    def test_english_detected(self):
        assert contains_english("That's great! You are doing well.") is True

    def test_short_text_skipped(self):
        assert contains_english("Sí.") is False

    def test_empty_string(self):
        assert contains_english("") is False


# ---------------------------------------------------------------------------
# check_register_heuristic
# ---------------------------------------------------------------------------


class TestRegisterHeuristic:
    def test_a1_simple_passes(self):
        assert (
            check_register_heuristic("El parque está cerca. ¿Vas mucho?", "A1") is True
        )

    def test_a1_too_complex(self):
        text = (
            "La infraestructura metropolitana contemporánea exhibe "
            "características extraordinarias e incomprensibles."
        )
        assert check_register_heuristic(text, "A1") is False

    def test_c1_allows_complexity(self):
        text = (
            "Me parece que la situación económica ha mejorado "
            "considerablemente en los últimos años."
        )
        assert check_register_heuristic(text, "C1") is True

    def test_empty_text(self):
        assert check_register_heuristic("", "B1") is True


# ---------------------------------------------------------------------------
# sentence / question counting
# ---------------------------------------------------------------------------


class TestCounting:
    def test_two_sentences(self):
        assert _count_sentences("Hola. ¿Cómo estás?") == 2

    def test_one_sentence(self):
        assert _count_sentences("El parque está cerca") == 1

    def test_three_sentences(self):
        assert _count_sentences("Hola. Bien. ¿Y tú?") == 3

    def test_one_question(self):
        assert _count_questions("Está bien. ¿Y tú?") == 1

    def test_no_questions(self):
        assert _count_questions("Está bien.") == 0

    def test_two_questions(self):
        assert _count_questions("¿Sí? ¿Y tú?") == 2


# (TestParseToolCalls is defined at the top of this module; see above.)
