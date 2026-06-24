# 传统 Alpha 因子挖掘说明

这份说明记录 `examples/alpha_factor_mining` 的研究逻辑、指标含义和最近一次
本地数据评估结果。当前示例只使用公式因子，不依赖深度模型，目标是保留较强的
可解释性。

## 数据和时间切分

当前默认数据源是本机 Qlib 数据：

```yaml
provider_uri: "~/.qlib/qlib_data/cn_data"
market: "csi300"
freq: "day"
```

本地 `day` 日历到 2026-04-03，但 `csi300` 实际可取到的行情样本到
2026-03-30。因此默认切分设为：

| segment | date range |
| --- | --- |
| train | 2021-01-01 to 2023-12-31 |
| valid | 2024-01-01 to 2024-12-31 |
| test | 2025-01-01 to 2026-03-30 |

使用原则是：训练期只用来确定因子方向，验证期用来筛因子，测试期只做最后观察。
这样可以避免用测试期结果反向调因子。

## Label 含义

默认 label 是：

```text
Ref($close, -2) / Ref($close, -1) - 1
```

它表示从 T+1 收盘到 T+2 收盘的收益，而不是当天收盘到下一天收盘的收益。
这是 Qlib `Alpha158` 的默认习惯，背后的考虑是：T 日收盘后才知道 T 日因子，
真实交易中更合理的是从后续可交易价格开始计算收益。

因此，一个因子在某天给出高分，评价的是它对后续可交易收益的排序能力。

## 因子方向

很多传统因子天然有方向，但方向在不同市场阶段可能会变化。例如：

- 低波动可能更好，也可能在强趋势市场中落后。
- 短期涨幅高可能是动量，也可能是反转。
- 价量相关性高可能代表资金推动，也可能代表拥挤。

脚本默认使用 `direction_policy: train_ic`：

1. 先在 train 期计算原始因子的 IC。
2. 如果 train IC 为正，保持方向为 `1`。
3. 如果 train IC 为负，把因子乘以 `-1`，方向记为 `-1`。

这样报告里的正向分数统一表示：分数越高，预期未来收益越高。

如果你对某个因子有明确经济假设，可以在 `factor_pool.yaml` 里手动设置：

```yaml
direction: 1
```

或：

```yaml
direction: -1
```

## 指标怎么看

`factor_metrics.csv` 是主结果表，一行一个因子。核心字段如下：

| metric | meaning |
| --- | --- |
| `ic_mean` | 每日横截面 Pearson IC 的均值 |
| `rank_ic_mean` | 每日横截面 Spearman Rank IC 的均值 |
| `icir` | `ic_mean / ic_std`，衡量 IC 稳定性 |
| `rank_icir` | `rank_ic_mean / rank_ic_std`，衡量排序能力稳定性 |
| `positive_ic_rate` | IC 大于 0 的交易日占比 |
| `long_short_ann` | top/bottom 分组多空收益的年化均值 |
| `long_short_ir` | 多空收益的信息比率 |
| `coverage` | 因子和 label 同时非空的样本比例 |
| `autocorr_1` | 因子相邻交易日自相关，衡量信号稳定性和换手压力 |

对传统 alpha 来说，优先看 `rank_ic_mean` 和 `rank_icir`。因为很多选股策略本质上
用的是横截面排序，而不是预测具体收益数值。

## 最近一次结果解读

使用本地 `~/.qlib/qlib_data/cn_data`，在 2024 验证期排名前 10 的因子是：

| rank | factor | category | direction | valid_rank_ic_mean | valid_rank_icir | note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | STD20 | risk | -1 | 0.052312 | 0.205712 | 低 20 日波动更优 |
| 2 | KLEN | kbar | -1 | 0.044023 | 0.194065 | 小日内振幅更优 |
| 3 | CORD20 | price_volume | -1 | 0.027714 | 0.169735 | 价量变化相关性偏低更优 |
| 4 | CORR20 | price_volume | -1 | 0.026156 | 0.160881 | 价格和成交量相关性偏低更优 |
| 5 | VSTD20 | volume | -1 | 0.017414 | 0.121267 | 成交量波动偏低更优 |
| 6 | KLOW | kbar | -1 | 0.013895 | 0.080657 | 下影线弱一些更优 |
| 7 | KUP | kbar | -1 | 0.011368 | 0.063957 | 上影线弱一些更优 |
| 8 | RSV20 | position | 1 | 0.007612 | 0.030371 | 收盘位置偏高略优 |
| 9 | RSQR20 | trend | 1 | 0.003637 | 0.024510 | 趋势线性更强略优 |
| 10 | ROC5 | momentum | 1 | 0.004221 | 0.016312 | 近 5 日相对位置信号较弱 |

这次结果和旧的 2010-2020 切分不同，主要原因是市场状态变了。最近样本中，
低波动、低振幅、低价量拥挤特征更靠前，这更像是偏防御和反拥挤的排序信号。

也要注意：验证期表现好不代表测试期一定好。例如 `STD20` 在 2024 验证期排名第一，
但 2025 到 2026-03-30 的测试期多空年化为负。这说明单因子稳定性还不够，不能
只凭一个验证期直接上线。

## 如何继续用这些结果

推荐下一步按下面顺序推进：

1. 扩展因子池，但每个因子必须有清楚假设。
2. 对同一类因子做相关性去重，例如波动类只保留最稳的几个。
3. 不直接用单因子上线，先做分组组合：
   - 低波动组：`STD20`, `KLEN`, `VSTD20`
   - 价量反拥挤组：`CORD20`, `CORR20`
   - K 线结构组：`KLOW`, `KUP`
4. 用 validation 期确定权重，用 test 期只做验收。
5. 再接入 `TopkDropoutStrategy` 或线性模型做组合回测。

一个保守的组合方式是：对入选因子横截面标准化，然后等权相加。这样比 LightGBM
更容易解释，也更容易定位收益来源。

## 运行命令

```bash
PYTHONPATH=. UV_LINK_MODE=copy uv run python examples/alpha_factor_mining/evaluate_factors.py \
  --output-dir /tmp/qlib_alpha_factor_mining_recent
```

主要输出：

| file | content |
| --- | --- |
| `factor_metrics.csv` | 每个因子的 train/valid/test 汇总指标 |
| `factor_daily_metrics.csv` | 每个因子的日度 IC、Rank IC 和多空收益 |
| `report.md` | 按验证期筛出的因子摘要 |

