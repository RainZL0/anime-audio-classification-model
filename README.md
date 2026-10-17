# anime-voice-sorter

按角色收集动画对白：给每一集的视频和字幕，按字幕把对白切成片段。你在界面里对照画面标几句，机器学着认出其余的；你改正它猜错的，它马上重学。最后按角色导出，可以直接拿去训练 GPT-SoVITS、Style-Bert-VITS2 或 RVC。

整套流程已经跑通，界面还在打磨。

```powershell
uv sync --locked
uv run avs doctor
uv run avs app runs
```

需要 FFmpeg 在 PATH 里。

- 现在到哪了、下一步做什么：[docs/STATUS.md](docs/STATUS.md)
- 命令怎么敲：[docs/USAGE.md](docs/USAGE.md)
- 其他全部文档：[docs/index.md](docs/index.md)

## 使用规范

本项目的代码以 [MIT 许可](LICENSE) 开源。用它从动画里提取出的音频和台词，版权属于原作的权利方，与本项目的许可无关。使用本工具即表示你同意：

- 只用于个人研究或学习。
- 不把提取出的音频、台词，或用它们训练出的模型用于商业用途。
- 不用提取出的声音冒充角色或配音演员本人，不制作会让人误以为出自本人的内容。
- 不公开分发提取出的音频。
