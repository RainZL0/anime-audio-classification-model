# anime-voice-sorter

按角色收集动画对白。项目简介见 `README.md`。

## 动手前

1. `docs/STATUS.md`：现在到哪、正在检验什么、下一步。
2. `docs/DECISIONS.md`：已经定下和已经排除的做法。**不要重开已排除的路**，要推翻先拿出新数据。
3. `docs/HISTORY.md`：做事的规矩，尤其是打分和标注那两节。

其余文档从 `docs/README.md` 找，那里也写了每份文档管什么、不管什么。**一件事只写在一处，别处只放链接。**

## 语言

用朴素易懂的话，**不要自造简称，不要用行话**。文档、代码注释、命令行输出、聊天回复一视同仁。名词以 `docs/HOW_IT_WORKS.md` 的名词表为准，新借来的指标名第一次出现时用一句话说清它衡量什么。

## 检查

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```
