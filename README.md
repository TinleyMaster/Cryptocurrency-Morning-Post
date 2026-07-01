# Cloud Automation Scaffold

这是当前 `加密市场早报 + KOL 24h 监控` 的云上执行脚手架 V1。

## 目标

- 使用 `Python + GitHub Actions` 定时生成市场早报和 KOL 报告
- 输出 Markdown 到本地仓库 `reports/` 目录
- 后续可接入 Feishu OpenAPI、CMC、xpoz、Dune 等真实数据源

## 目录说明

- `app/`: 应用代码
- `config/`: 配置文件
- `.github/workflows/`: GitHub Actions 定时任务
- `reports/`: 输出目录
- `tests/`: 最少必要测试

## 本地运行

```bash
pip install -r requirements.txt
python -m app.main_market
python -m app.main_kol
```

- 本地可直接在项目根目录填写 `.env`，程序启动时会自动加载其中的 API key 与 token。

## 环境变量

- `CMC_API_KEY`
- `XPOZ_API_KEY`
- `DUNE_API_KEY`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_FOLDER_TOKEN`
- `FEISHU_CHAT_ID`
- `FEISHU_BASE_TOKEN`
- `FEISHU_TABLE_ID`
- `FEISHU_WEBHOOK_URL`

说明：

- 本地未配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 时，脚本会跳过真实飞书发布，但仍会正常生成本地报告文件。
- 配置 `FEISHU_WEBHOOK_URL` 后，群消息会优先走 webhook 发送；程序仍会先尝试导入飞书云文档，成功时自动把文档链接带进 webhook 摘要，失败时再降级为纯文本推送。
- 上云时请在 GitHub Secrets 中配置上述飞书变量，届时会真实调用 Feishu OpenAPI。
- Dune 当前走官方 REST 接口 `GET /v1/query/{query_id}/results`，需要在 `config/market.yaml` 配置 `dune.whale_query_id`。
- 建议你的 Dune 保存查询直接输出这 4 列：`chain`、`symbol`、`amount_usd`、`interpretation`；如果列名不同，可在 `dune.row_mapping` 中改映射。

## 当前状态

- 已完成项目骨架、配置、模板、入口和工作流初稿
- CMC / xpoz / Dune 已接入真实接口，其中 Dune 需要额外提供可用 query id
- 如未配置 Dune key 或 query id，市场报告会明确写出缺失原因，不会编造巨鲸数据
