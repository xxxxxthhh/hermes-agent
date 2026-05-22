"""Regression tests for Discord empty-response loop-fuel suppression."""

from gateway.run import _prepare_gateway_status_message, _sanitize_gateway_final_response


def test_discord_empty_response_retry_status_is_suppressed():
    assert (
        _prepare_gateway_status_message(
            "discord",
            "status",
            "⚠️ Empty response from model — retrying (1/3)",
        )
        is None
    )


def test_discord_empty_final_response_warning_is_suppressed():
    assert (
        _sanitize_gateway_final_response(
            "discord",
            "⚠️ The model returned no response after processing tool results. "
            "This can happen with some models — try again or rephrase your question.",
        )
        == ""
    )


def test_discord_normal_status_still_passes_through():
    assert (
        _prepare_gateway_status_message("discord", "status", "Running tests…")
        == "Running tests…"
    )


def test_discord_explanation_about_empty_response_is_not_suppressed():
    text = "结论：`⚠️ Empty response from model — retrying (1/3)` 这种状态消息应该不发到 Discord thread。"
    assert _sanitize_gateway_final_response("discord", text) == text


def test_telegram_empty_response_status_behavior_unchanged():
    message = "⚠️ Empty response from model — retrying (1/3)"
    assert _prepare_gateway_status_message("telegram", "status", message) == message
