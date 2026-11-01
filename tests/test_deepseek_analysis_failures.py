"""Offline regressions for permanent LLM failures and the stock-to-WeChat path."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests

from src.analyzer import GeminiAnalyzer, _AllModelsFailedError
from src.config import Config, extra_litellm_params, get_api_keys_for_model
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.llm.errors import call_litellm_with_param_recovery, llm_error_status
from src.notification import NotificationService
from src.notification_sender.wechat_sender import WechatSender


@pytest.fixture
def analyzer():
    config = Config(
        litellm_model="openai/test-deepseek-model",
        openai_api_keys=["test-private-api-key"],
        openai_base_url="https://api.deepseek.com/v1",
        report_integrity_enabled=False,
        wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-webhook-secret",
    )
    return GeminiAnalyzer(config=config, skill_instructions="", default_skill_policy="")


def api_error(status):
    error = RuntimeError("Fails, Your api key: test-private-api-key")
    error.status_code = status
    error.request = httpx.Request(
        "POST", "https://api.deepseek.com/v1/chat/completions?key=test-private-api-key"
    )
    return error


@pytest.mark.parametrize("status", [401, 402, 403, 404, 422])
@pytest.mark.parametrize("during_stream", [False, True])
def test_permanent_errors_do_not_repeat_as_non_stream(analyzer, status, during_stream, caplog):
    error = api_error(status)

    def broken_stream():
        raise error
        yield  # pragma: no cover

    def dispatch(model, kwargs, **ignored):
        if during_stream:
            return broken_stream()
        raise error

    with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch) as completion:
        with pytest.raises(_AllModelsFailedError) as failure:
            analyzer._call_litellm_impl("analyze 600519", {}, stream=True)
    assert completion.call_count == 1
    assert f"status={status}" in caplog.text
    assert "model=openai/test-deepseek-model" in caplog.text
    assert "endpoint=https://api.deepseek.com/v1" in caplog.text
    assert "test-private-api-key" not in caplog.text + str(failure.value)
    assert "?key=" not in caplog.text


def test_permanent_error_still_allows_configured_fallback(analyzer):
    analyzer._config_override.litellm_fallback_models = ["openai/backup-model"]

    def dispatch(model, kwargs, **ignored):
        if model == "openai/test-deepseek-model":
            raise api_error(401)
        return iter([{"choices": [{"delta": {"content": "backup report"}}]}])

    with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=dispatch) as completion:
        text, model, _ = analyzer._call_litellm_impl("prompt", {}, stream=True)
    assert text == "backup report"
    assert model == "openai/backup-model"
    assert completion.call_count == 2


def test_auth_error_is_not_parameter_recovery():
    error = api_error(401)
    error.args = ("authentication failed: temperature not supported",)
    call = MagicMock(side_effect=error)
    with pytest.raises(RuntimeError):
        call_litellm_with_param_recovery(
            call, model="openai/test-model", call_kwargs={"temperature": 0.7}
        )
    assert call.call_count == 1
    assert llm_error_status(error) == 401


def test_explicit_422_parameter_error_keeps_one_shot_recovery():
    error = api_error(422)
    error.args = ("temperature is not supported",)
    call = MagicMock(side_effect=[error, "recovered"])
    assert call_litellm_with_param_recovery(
        call, model="openai/test-422-model", call_kwargs={"temperature": 0.7},
        cache_recovery=False,
    ) == "recovered"
    assert call.call_count == 2
    assert "temperature" not in call.call_args.args[0]


def test_status_reads_response_and_handles_cyclic_causes():
    error = RuntimeError("HTTP error")
    error.response = SimpleNamespace(status_code=402)
    assert llm_error_status(error) == 402
    error.response = None
    error.__cause__ = error
    assert llm_error_status(error) is None


def test_endpoint_omits_userinfo_and_query(analyzer):
    error = RuntimeError("failed")
    error.request = httpx.Request("POST", "https://user:password@api.deepseek.com/v1?secret=opaque#hidden")
    endpoint = analyzer._litellm_error_endpoint(analyzer._config_override, "openai/test-model", error)
    assert endpoint == "https://api.deepseek.com/v1"


def test_stock_analysis_error_is_safe_and_failed(analyzer, caplog):
    with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=api_error(401)) as completion:
        result = analyzer.analyze({"code": "600519", "name": "贵州茅台"})
    assert not result.success
    assert "status=401" in result.error_message
    assert "test-private-api-key" not in result.error_message + caplog.text
    assert completion.call_count == 1


def test_stock_analysis_renders_and_posts_wechat(analyzer, tmp_path):
    payload = json.dumps({
        "stock_name": "贵州茅台", "sentiment_score": 65,
        "trend_prediction": "震荡", "operation_advice": "持有",
        "confidence_level": "中", "analysis_summary": "模拟个股报告",
    }, ensure_ascii=False)
    response = iter([{"choices": [{"delta": {"content": payload}}]}])
    with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
        result = analyzer.analyze({"code": "600519", "name": "贵州茅台"})
    assert result.success
    config = analyzer._config_override
    with patch("src.notification.get_config", return_value=config):
        notifier = NotificationService()
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = config
    pipeline.notifier = notifier
    pipeline._refresh_saved_diagnostic_snapshot = MagicMock()
    http_response = SimpleNamespace(status_code=200, json=lambda: {"errcode": 0, "errmsg": "ok"})
    with (
        patch.object(notifier, "save_report_to_file", return_value=str(tmp_path / "report.md")),
        patch("src.notification_sender.wechat_sender.requests.post", return_value=http_response) as post,
        patch("src.notification_sender.wechat_sender.time.sleep"),
    ):
        pipeline._send_single_stock_notification(result, ReportType.SIMPLE)
    assert post.called
    sent = "".join(call.kwargs["json"]["markdown"]["content"] for call in post.call_args_list)
    assert "600519" in sent
    assert "模拟个股报告" in sent
    assert all(call.kwargs["verify"] is True for call in post.call_args_list)


@pytest.mark.parametrize("chunked", [False, True])
def test_wechat_network_error_hides_webhook(analyzer, caplog, chunked):
    sender = WechatSender(analyzer._config_override)
    error = requests.ConnectionError(f"failed URL {sender._wechat_url}")
    with patch("src.notification_sender.wechat_sender.requests.post", side_effect=error):
        assert not sender.send_to_wechat("个股报告" * (1000 if chunked else 1))
    assert "ConnectionError" in caplog.text
    assert "test-webhook-secret" not in caplog.text


def test_wechat_rejection_logs_code_without_response_body(analyzer, caplog):
    response = SimpleNamespace(status_code=200, json=lambda: {
        "errcode": 93000, "errmsg": "invalid webhook test-webhook-secret"
    })
    with patch("src.notification_sender.wechat_sender.requests.post", return_value=response):
        assert not WechatSender(analyzer._config_override).send_to_wechat("个股报告")
    assert "93000" in caplog.text
    assert "test-webhook-secret" not in caplog.text


def test_legacy_deepseek_and_openai_credentials_are_not_interchangeable():
    config = Config(openai_api_keys=["test-openai-key"], deepseek_api_keys=["test-deepseek-key"],
                    openai_base_url="https://api.deepseek.com/v1")
    assert get_api_keys_for_model("openai/test-model", config) == ["test-openai-key"]
    assert get_api_keys_for_model("deepseek/test-model", config) == ["test-deepseek-key"]
    assert extra_litellm_params("openai/test-model", config)["api_base"] == config.openai_base_url
    assert "api_base" not in extra_litellm_params("deepseek/test-model", config)
