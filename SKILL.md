---
name: vic3-save-analysis
description: 分析维多利亚3存档文件（.v3），提取玩家国家、列强排名、GDP/人口排行等数据并生成中文报告。当用户想分析、解读或审查某个维多利亚3存档时使用。
---

# 维多利亚 3 存档分析

用本目录的 `analyze.py` 脚本解析 Victoria 3 存档，输出中文 Markdown、CSV 与 JSON。这个工具应被当成通用存档读取框架使用，而不是只服务某一个存档。

## 用法

```bash
python analyze.py                # 自动定位并分析最新存档
python analyze.py report         # 自动定位并分析最新存档
python analyze.py report --full  # 完整扫描人口明细，较慢
python analyze.py report <存档路径> # 分析指定存档
python analyze.py --json doctor  # 检查环境，机器可读
python analyze.py --json latest  # 返回最新存档路径
python analyze.py --json community # 查看社区后端与 Rakaly 状态
python analyze.py melt <存档路径> # 用 Garibaldi/Rakaly 转换二进制存档
python analyze.py systems        # 固定模板导出主要国家体系表
python analyze.py systems --limit 30
```

用户也可以直接双击本目录的 `启动维多利亚3存档读取器.bat`，菜单里有快速分析、体系导出和 API分析。

## 存档位置（Windows）

```
C:\Users\<用户名>\Documents\Paradox Interactive\Victoria 3\save games\*.v3
```

## 输出内容

- 游戏版本、游戏日期、存档国家
- 玩家国家概况（GDP、威望、人口、识字率、生活水平）
- 列强/威望排名
- GDP 前十、人口前十
- 玩家国家州、建筑、法律
- 玩家国家人口明细与职业/文化/宗教结构（需要 `--full`）
- CSV 与 `summary.json`，方便后续预测、实验或接 API
- 主要国家固定体系导出：国家总表、州、建筑、人口、法律、利益集团、科技、关系、条约

## 社区集成策略

- 优先借用社区：Garibaldi 的指标体系与 Rakaly melter，vic3-reader 的 parser/metrics/orchestrator 分层方法。
- 保留自写层：中文报告、用户本地路径、模组兼容、API 菜单、社会学分析口径。
- API Key 配置保存在 `C:\Users\<用户名>\.vic3-save-analyzer\api_config.json`，不要在报告正文里输出密钥。

## 深入分析指南

如需更详细的报告（社会学/经济学/国际政治维度），在脚本输出基础上，进一步从存档提取：

- **经济**：`building_manager`（建筑构成，按 `state` 过滤）
- **社会**：`pops.database` 与 `country_manager.database` 的 `pop_statistics`（阶级/宗教/文化/激进与忠诚人口）
- **政治**：`interest_groups`（利益集团影响力）、`laws`（生效法律）、`character_manager`（统治者）
- **外交**：`pacts`、`relations`、`war_manager`、`power_bloc_manager`
- **科技**：`technology`（已研究科技）

## 技术要点

- Victoria 3 存档为 Clausewitz 文本格式（`key = { ... }` 花括号嵌套），必须用**花括号匹配**而非缩进解析。
- 存档可为 ZIP 压缩（二进制）或纯文本；文本格式可直接解析，二进制需先解压。
- 解析顶层管理器时优先匹配行首 `manager={`，避免误抓国家内部字段，例如国家块里的 `states={...}`。
- 国家标签（tag）→ 中文名可查游戏本地化文件 `game/localization/simp_chinese/countries_l_simp_chinese.yml`。
- 文化数字 ID → 名称：优先查存档内 `cultures.database` 的 `type` 字段；宗教通常已在 pop 字段内保存为文本键。
