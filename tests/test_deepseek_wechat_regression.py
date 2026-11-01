"""Offline regressions for safe diagnostics and stock report webhook delivery."""
from unittest.mock import Mock, patch

import pytest

from src.llm.errors import is_permanent_llm_error, llm_http_status, safe_llm_endpoint


def test_endpoint_does_not_expose_credentials():
    assert safe_llm_endpoint("https://user:password@api.deepseek.com/v1/secret?key=secret") == "https://api.deepseek.com"
    assert safe_llm_endpoint(None) == "provider-default"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_transient_errors_are_not_permanent(status):
    error = RuntimeError("temporary failure")
    error.response = Mock(status_code=status)
    assert llm_http_status(error) == status
    assert not is_permanent_llm_error(error)


@pytest.mark.parametrize("status,errcode,expected", [(200, 0, True), (200, 40014, False), (500, 0, False)])
def test_stock_report_webhook_response(status, errcode, expected):
    from src.analyzer import AnalysisResult
    from src.config import Config
    from src.notification import NotificationService
    from src.notification_sender.wechat_sender import WechatSender

    config = Config(stock_list=["600519"], wechat_webhook_url="https://example.invalid/hook?key=fake-secret")
    with patch("src.notification.get_config", return_value=config):
        report = NotificationService().generate_single_stock_report(
            AnalysisResult(code="600519", name="贵州茅台", sentiment_score=60,
                           trend_prediction="震荡", operation_advice="观望", decision_type="hold")
        )
    response = Mock(status_code=status)
    response.json.return_value = {"errcode": errcode, "errmsg": "fake-secret"}
    with patch("src.notification_sender.wechat_sender.requests.post", return_value=response) as post:
        assert WechatSender(config).send_to_wechat(report) is expected
    assert "600519" in post.call_args.kwargs["json"]["markdown"]["content"]


def test_webhook_exception_does_not_log_url(caplog):
    from src.config import Config
    from src.notification_sender.wechat_sender import WechatSender

    sender = WechatSender(Config(stock_list=[], wechat_webhook_url="https://example.invalid/?key=fake-secret"))
    with patch("src.notification_sender.wechat_sender.requests.post", side_effect=RuntimeError(sender._wechat_url)):
        assert not sender.send_to_wechat("600519 report")
    assert "fake-secret" not in caplog.text
