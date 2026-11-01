# DeepSeek 官方 API + GitHub Actions + 企业微信排障

## 先区分已确认的行为与单次运行的原因

- `openai/<模型 ID>` 是 OpenAI 兼容协议的合法 LiteLLM 前缀；看到 `openai/dee...` 不能直接认定配置错误。
- `Fails, Your api key: <redacted>` 不能单独证明密钥无效。应结合完整错误类型、HTTP 状态和请求地址判断。
- 大盘 LLM 失败时可以降级为模板复盘。收到大盘不等于模型认证成功。
- 个股 `AnalysisResult.success=False` 会被流水线排除，不生成正常汇总，也不触发单股推送。不会把失败分析伪装成成功报告。
- 本次修复后，完整模式中个股全败或部分失败仍会继续发送大盘与已成功个股，但最终返回失败状态，便于 Actions 发现缺失报告。

模型错误日志包含 `type`、`status`、`model`、`endpoint`。实际请求 URL 可获得时优先使用它；否则显示配置的渠道地址，未显式配置的原生 provider 显示 `provider-default`。URL 用户信息、查询参数和片段不会进入 endpoint 字段。没有结构化状态码时显示 `unknown`，不会从消息文本猜状态码。

401/402/403/404/422 不再因流式失败而重复发同一路由的非流式请求；401/402/403/404 也不会误入生成参数恢复。明确的 422 参数错误仍允许既有的一次参数恢复。400 的流兼容/参数恢复、瞬时故障处理，以及其他已配置的 fallback 保持可用。此规则不是全局熔断；不同股票仍会单独尝试，Router 的多密钥轮换保持原有行为。

## 配置优先级（以当前代码与工作流为准）

1. 模型部署列表优先采用有效的 `LITELLM_CONFIG` YAML，其次 `LLM_CHANNELS`，最后兼容旧版 API Key 配置。渠道与 YAML 模式使用各 deployment 的 Key/Base URL。
2. `LITELLM_MODEL` 显式指定调用模型/路由别名；不会因填写 `OPENAI_MODEL` 自动被替换。在 YAML/渠道模式未显式指定时，使用第一个可用路由。
3. 旧版模式没有 `LITELLM_MODEL` 时按 Gemini → Anthropic → DeepSeek → OpenAI 的已有密钥顺序推导。`OPENAI_MODEL` 只用于 OpenAI 路径的推导。
4. 旧版 `deepseek/...` 读取 `DEEPSEEK_API_KEY(S)`；`openai/...` 读取 `OPENAI_API_KEY(S)` 并应用 `OPENAI_BASE_URL`。两组密钥不互换。多 Key 变量非空时优先于同组单 Key。
5. Actions 大部分非敏感项采用 `vars.NAME || secrets.NAME`，所以同名 Variable 非空时覆盖 Secret。密钥与企业微信 Webhook 只从 Secrets 注入。Actions 不会自动导入任意自定义渠道名的环境变量。
6. `STOCK_LIST` 优先使用 Variable/Secret，其次 runner 上已有的同名环境变量；都为空时当前工作流默认 `600519`。交易日过滤可能跳过标的，首次排障可以勾选 `force_run`。
7. `REPORT_TYPE` 支持 `simple`、`full`、`brief`；`SINGLE_STOCK_NOTIFY=true` 会逐股推送，`false` 为汇总推送，并不代表关闭个股分析。首次使用 `simple`。本地/Docker 的 `REPORT_SUMMARY_ONLY` 可影响详情展示，但当前 Actions 工作流未映射它，不能假定同名 Variable 会生效；默认值为 `false`。

## 首次只测试 600519

在 **Settings → Secrets and variables → Actions** 中先选择一种配置方式。以下为与现有 `OPENAI_*` 配置对应的 OpenAI 兼容方式：

| 类别 | 名称 | 设置 |
| --- | --- | --- |
| Secret | `OPENAI_API_KEY` | DeepSeek 官方平台密钥（只在 GitHub 安全输入） |
| Secret | `WECHAT_WEBHOOK_URL` | 企业微信群机器人完整 Webhook URL |
| Variable | `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| Variable | `OPENAI_MODEL` | 官方当前可用的模型 ID，不能是显示名称或截断名称 |
| Variable | `LITELLM_MODEL` | `openai/` 加同一个模型 ID |
| Variable | `STOCK_LIST` | `600519` |
| Variable | `REPORT_TYPE` | `simple` |
| Variable | `SINGLE_STOCK_NOTIFY` | `true` |
| Variable | `MARKET_REVIEW_ENABLED` | `true` |

首次排障时不要同时启用其他 Key 自动渠道、`LITELLM_CONFIG`、`LLM_CHANNELS` 或 `LITELLM_FALLBACK_MODELS`，否则它们可能改变实际部署或增加 fallback。检查同名旧 Secret/Variable，避免清空 Variable 后又回退到旧 Secret。应用不会自动删除或改写已有配置。

也可用原生方式：`DEEPSEEK_API_KEY` + `LITELLM_MODEL=deepseek/<官方模型 ID>`；该方式由 LiteLLM 决定官方默认地址，旧版 `OPENAI_BASE_URL` 不控制它。不要只换 provider 前缀而保留另一组 Key。

当前仓库指南推荐 `deepseek-v4-flash` / `deepseek-v4-pro`，同时旧版单 Key 推导仍使用 `deepseek-chat`。这只是仓库现状，不是当前官方可用性的在线验证。部署前请以 [DeepSeek 官方文档](https://api-docs.deepseek.com/)、[模型列表 API](https://api-docs.deepseek.com/api/list-models) 和账户权限为准；LiteLLM 接法见 [DeepSeek provider](https://docs.litellm.ai/docs/providers/deepseek)。无法读取这些来源或没有凭据时，不应声称已验证某个模型当前可用，也不应自动迁移用户模型。

在合入修复前，可从 **Actions → 每日股票分析 → Run workflow** 选择修复分支，先运行 `stocks-only`，需要时勾选 `force_run`。确认 600519 报告及企业微信接收后，再运行 `full` 验证大盘与个股组合。定时任务只运行默认分支版本；审查并合入后确认工作流已启用，当前计划为工作日北京时间 18:00，GitHub 调度可能延迟。

## 需要保留的诊断证据

记录失败运行 URL、提交 SHA、失败步骤名，以及首次模型错误前后约 30 行：完整模型、endpoint、HTTP 状态、错误类型和个股失败汇总。不要提供真实 API Key、Authorization 或带 Webhook 密钥的 URL。`exit code 1` 也可能来自安装或数据源阶段，必须结合失败步骤分析。

企业微信日志只记录异常类型、HTTP 状态或 `errcode`，不记录异常全文或响应体。HTTP 200 仍须 `errcode=0` 才算推送成功。

本地离线回归：

```bash
python -m pytest tests/test_deepseek_analysis_failures.py tests/test_market_analyzer_generate_text.py tests/test_pipeline_single_stock_notify.py tests/test_main_schedule_mode.py -q
```

测试模拟模型及企业微信响应，不会请求真实 API 或发送真实消息。回滚方式为 revert 修复提交；无数据库迁移，也不会清理已有配置。
