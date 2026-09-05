# anime-voice-sorter

给它一部动画，它把里面的说话声**按人分好组**，每组是一堆干净的语音片段。用来收集某个角色的音色。

```
你给它：  动画的若干集（视频或音轨），字幕可给可不给
         另外还可以给每个角色两三条样本，但不是必须的

它给你：  out/
          speaker_01/  一堆 wav      同一个人，没有背景音乐，没有两个人同时说话
          speaker_02/  一堆 wav
          _misc/                     只说了一两句的路人，不值得单独成组
          _rejected/                 质量不达标被淘汰的片段，留着让你复查
          manifest.parquet           一张表，记录每个片段的所有信息和淘汰原因
```

**它不知道有几个人，也不知道这些人是谁。** 它只负责把像的归到一起，你事后再听一听、给每组起个名字，或者干脆不起。

## 现在到哪一步了

**第 1 集从抽音轨到算指纹已经跑通，分组和导出还没写。** 声纹这条路已经用人工标注验证成立（错误率 7%），但音质筛选之后仍有 26% 的片段有多个人说话，那是当前的瓶颈。实测数字、下一步做什么、卡在哪，见 [`docs/STATUS.md`](docs/STATUS.md)。

## 怎么装

需要先装 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run avs doctor
```

`doctor` 会告诉你显卡能不能用、各个依赖装好了没有。

开发机是 Windows 加独立显卡，装的是 CUDA 版本；自动检查跑在 Linux 上，会自动改装 CPU 版本，不用手动切换。

切段认人用的模型需要先去 HuggingFace 网页上点同意、拿一个账号令牌，才能下载。

## 文档

从 [`docs/README.md`](docs/README.md) 进去，那里有导航和每份文档的分工。

- [`docs/GLOSSARY.md`](docs/GLOSSARY.md) —— 专业词的大白话解释，看不懂哪个词就查这里
- [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) —— 流程怎么走，每步在解决什么问题
- [`docs/TOOLS.md`](docs/TOOLS.md) —— 用了哪些现成工具，为什么选它
- [`docs/STATUS.md`](docs/STATUS.md) —— 进度、下一步、卡住的地方
- [`docs/DECISIONS.md`](docs/DECISIONS.md) —— 做过哪些选择，为什么
- [`docs/OLD_PROJECT.md`](docs/OLD_PROJECT.md) —— 上一版项目哪里错了

## 有一个错绝对不能犯

分析声音用的是 16 kHz 的低采样率副本，但**最终导出的音频必须从原始采样率的音轨里切**。

因为音色模型大多在 40 到 48 kHz 上训练。如果拿 16 kHz 的音频升采样回去当成品，高频信息已经永久丢了，补不回来。麻烦的是这种损坏**听着不明显、程序也不报错**，你可能训完一个音色模型才发现效果不对，还查不出原因。

## 许可

还没定。
