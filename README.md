# anime-voice-sorter

按角色收集动画对白：按字幕把对白切成片段，再把同一角色的声音归到一组，不同角色尽量分开。先解决「谁在说话」，偶发的语气词和噪声以后再处理。

流程已经跑通，分组还在改进。

```powershell
uv sync --locked
uv run avs doctor
```

需要 FFmpeg 在 PATH 里。

- 现在到哪了、下一步做什么：[docs/STATUS.md](docs/STATUS.md)
- 命令怎么敲：[docs/USAGE.md](docs/USAGE.md)
- 其他全部文档：[docs/index.md](docs/index.md)
