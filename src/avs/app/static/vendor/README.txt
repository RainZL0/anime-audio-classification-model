preact-htm.js 是 htm 3.1.1 自带的 preact/standalone.module.js，里面打包了 Preact（MIT 许可）和 htm（Apache-2.0 许可，见 htm-LICENSE.txt）。
放进仓库是为了不需要 Node 和构建步骤：装好 Python 依赖就能打开界面。升级时用 npm pack htm 取同一个文件替换。
