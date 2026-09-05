# anime-voice-sorter

把一部动画拆成按人分好组的纯净人声片段，用来收集角色音色。

## 接手先读这三样

1. [`docs/STATUS.md`](docs/STATUS.md) —— 现在到哪了、卡在哪、下一步做什么。**先读「一句话」
   和「下一步」两节**，其余是留档。
2. [`docs/README.md`](docs/README.md) —— 文档导航，以及**每份文档管什么**。改文档前先看这个，
   一件事只写在一个地方。
3. [`docs/DECISIONS.md`](docs/DECISIONS.md) —— 做过哪些选择。**已经写下的条目不修改**，
   推翻了就往后加一条，再把旧那条标成「已被第 N 条取代」。

不认识的词查 [`docs/GLOSSARY.md`](docs/GLOSSARY.md)。

人工标注在 [`annotations/`](annotations/)，那是目前唯一的真答案，会进 git；`runs/`、`data/`、`models/`、`out/` 都被忽略，里面的东西删了能重跑。

## 改完代码要过的四项检查

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
```

## 表达风格（对所有输出生效）

聊天回复、文档、代码注释、提交信息，全部适用。

- **用大白话，不用行话。** 判断标准是：一个没做过语音和机器学习的人能不能读懂。
- **专业词第一次出现时，先用一句话解释它是什么**，或者直接指向 [`docs/GLOSSARY.md`](docs/GLOSSARY.md)。
  已经在术语表里的词可以直接用。
- **不用英文缩写当主语**。要写就写全称加中文解释，比如「说话人分段（diarization，判断每一段是谁在说）」，
  不要只甩一个 `VAD`、`SDR`、`RTF` 就往下走。
- **不堆形容词，不写空话。** 「效果好」要说好在哪、好多少；「很快」要给秒数或者倍率。
  拿不出数字就直说「还没测」。
- **别把简单的事说复杂。** 能一句话讲完就一句话，不要为了显得严谨而套一层术语。

这条规则和 [`docs/README.md`](docs/README.md) 里对文档的要求是同一条，只是扩大到所有输出。
