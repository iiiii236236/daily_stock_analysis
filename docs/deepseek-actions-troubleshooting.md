# DeepSeek 官方 API 与企业微信：Actions 排障

## 已确认的故障

运行 41353811731（2026-11-02 北京时间）使用 `openai/deepseek-flash`、
`OPENAI_BASE_URL=https://api.deepseek.com`，服务返回 `Authentication Fails`。
这证明请求鉴权失败，不能证明密钥失效的具体原因（错误凭据、账户状态等需由部署者核实）。
日志没有提供可靠 HTTP 状态码，不能据此声称一定是 401。
4 只股票全部失败，pipeline 不将 `success=False` 结果计入报告，main 因无报告返回 1。
行情接口也出现错误，但该次已通过备用源成功获取，不是最终退出的直接原因。

大盘与个股为独立流程；大盘 AI 失败时可使用模板（`fallback_template`），
因此收到大盘推送不能证明个股 AI 鉴权正常。最新这次运行没有生成大盘报告。

代码现在避免对鉴权/余额/权限/模型路由错误再做一次非流式请求；
仍保留其他模型 fallback、临时错误和流式不支持时的兼容降级。
安全日志包含类型、结构化 HTTP 状态（无则 None）、模型及接口 origin。
Router 有多个部署时显示配置的候选 origin，并不冒充实际失败部署。
Webhook 错误仅记录类型、HTTP 状态或 errcode，不记录异常 URL 或完整响应体。

## 配置与优先级

工作流同名配置通常是 Variables 优先于 Secrets。Environment `STOCK_LIST`
若存在同名 Secret/Variable，也应检查，避免旧值覆盖 Repository 配置。

- 部署配置：有效 `LITELLM_CONFIG` > `LLM_CHANNELS` > 旧环境变量。
- 显式 `LITELLM_MODEL` 优先；否则根据部署列表或旧 provider 推断。
- `OPENAI_MODEL` 用于旧 OpenAI 兼容配置，不能覆盖显式 `LITELLM_MODEL`。
- 旧兼容层密钥：`OPENAI_API_KEYS` > `AIHUBMIX_KEY` > `OPENAI_API_KEY`。
- 原生 `deepseek/` provider 使用独立 `DEEPSEEK_API_KEYS` / `DEEPSEEK_API_KEY`。
- `STOCK_LIST` 逗号分隔。手动输入 `stocks` > Variables/Secrets 的 STOCK_LIST > runner STOCK_LIST > 默认 600519。
- `REPORT_TYPE` 支持 `simple/full/brief`，改变报告内容格式，不控制是否进行个股分析。
- `SINGLE_STOCK_NOTIFY=true` 每只成功后立即推送；false 汇总成功结果再推送。不会让失败分析变成有效报告。
- 企业微信群机器人使用 `WECHAT_WEBHOOK_URL`；发送成功需 HTTP 200 且 JSON `errcode=0`。

## 推荐首次配置（只选一套）

在 Settings → Secrets and variables → Actions 设置：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | OPENAI_API_KEY | 从 DeepSeek 官方平台取得的真实密钥 |
| Secret | WECHAT_WEBHOOK_URL | 企业微信群机器人完整 Webhook |
| Variable | OPENAI_BASE_URL | https://api.deepseek.com/v1 |
| Variable | OPENAI_MODEL | deepseek-flash |
| Variable | LITELLM_MODEL | openai/deepseek-flash |
| Variable | STOCK_LIST | 600519 |
| Variable | REPORT_TYPE | full |
| Variable | SINGLE_STOCK_NOTIFY | true |

此套配置使用 OpenAI 兼容路由。停用其他旧路由配置，尤其 `LLM_CHANNELS`、
`LITELLM_CONFIG`、`OPENAI_API_KEYS`、`AIHUBMIX_KEY` 以及其他主模型密钥，
以免推断出不同 provider。不要在 Variables 中保存密钥，也不要粘贴到日志或 PR。
若选择原生路由，则配置 Secret `DEEPSEEK_API_KEY` 和 Variable
`LITELLM_MODEL=deepseek/deepseek-flash`，无需 OpenAI 兼容层密钥。

截至 2026-11-02，官方文档列出的模型是 `deepseek-flash`、`deepseek-v4-pro`；
不要照搬旧教程的 `deepseek-chat`。LiteLLM 原生前缀为 `deepseek/`；
指定 `api_base` 的 OpenAI 兼容路由 `openai/` 也是合法配置，前缀本身不是本次鉴权失败的证据。
来源：[DeepSeek 模型](https://api-docs.deepseek.com/quick_start/pricing/)、
[首次调用](https://api-docs.deepseek.com/quick_start/agent_integrations/)、
[LiteLLM DeepSeek](https://docs.litellm.ai/docs/providers/deepseek)。

## 首次运行和验收

1. 审查并手动合并修复 PR，或在 Actions 中选择修复分支测试；不要重跑旧运行（仍会使用旧提交）。
2. Actions → 每日股票分析 → Run workflow，`stocks=600519`、`mode=full`；非交易日测试可勾选 force_run。
3. 检查 600519 分析成功、报告 artifact，以及群内个股与大盘消息。
4. 若仍失败，提供新运行链接及安全的 error_type/http_status/model/endpoints 日志，不提供密钥。
5. 验收后扩充 STOCK_LIST；确认 Actions 已启用。默认计划为周一至周五北京时间 18:00，
   GitHub 调度可能延迟，fork 需要启用工作流，定时运行使用默认分支代码。

真实 API、真实群投递及定时调度需部署者配置后验收；模拟测试不代表这些项目已通过。
回滚：revert 此 PR 的提交。未改动行情数据源或报告模块。

此排障文档针对本仓库中文部署场景，未新增英文镜像；既有双语文档保持不变。
