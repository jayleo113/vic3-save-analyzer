# Rust 加速层设计

v0.3 保留 Python 作为主程序。Rust 只承担低层、可验证、容易回退的热点任务。

## 当前已放入仓库的组件

位置：`rust/vic3_parser_rs`

当前二进制：`vic3-scan`

作用：

- 读取已经展开的 Victoria 3 文本存档。
- 扫描顶层数据块，例如 `country_manager`、`states`、`pops`、`war_manager`。
- 输出每个顶层块的 byte offset：`name`、`start`、`open`、`end`。
- 扫描时跳过字符串和注释，避免把字符串里的 `{`、`}` 当作结构括号。

## 编译

```powershell
cd F:\vic3-save-analyzer\rust\vic3_parser_rs
cargo build --release
python ..\..\api_server.py status
```

如果显示 `Rust 顶层块扫描器` 路径，说明 Python 已经能发现该组件。

## 使用原则

- Rust 不直接生成最终报告。
- Rust 不替代完整的业务解析和中文输出。
- Rust 输出位置与结构线索，Python 根据这些线索继续做模块提取、缓存、筛选、报告。
- Rust 不可用时，项目必须自动回退到纯 Python 路径。

## 后续最值得迁移的热点

1. 顶层块扫描与结构索引。
2. 人口条目流式提取。
3. 战争、战斗、建筑等大表的低层条目拆分。
4. 将提取结果直接写成 SQLite 行，减少 Python 大对象中转。

## 不做的事

- 不把终端菜单、API、Markdown 报告重写成 Rust。
- 不为了“看起来高级”引入无法维护的复杂构建链。
- 不让 Rust 变成必装依赖；发布版应始终保留 Python fallback。
