# RP2350 六色墨水屏排程指示牌

在 Waveshare **PhotoPainter (B)** 的 Pico 2 主控上运行 **MicroPython**。从 TF 卡读取类似 cron 的排程，用图片或 UTF-8 TXT 替代 cron 命令。使用产品已有电池和 PCF85063 RTC 定时唤醒；完成更新后关闭主控，墨水屏保持画面。

实现已通过云端单元测试及 MicroPython v1.26.0 Unix 语言验证，**尚未在产品实机验证**。从[部署与实机验证](docs/deployment.md)开始，硬件来源见[产品分析](docs/product-analysis.md)。

## 排程格式

```cron
# 分 时 日 月 周  TF卡路径
0 9 * * 1-5 /text/open.txt
0 18 * * 1-5 /text/closed.txt
0 0 * * 6,0 /pic/weekend.e6
*/30 9-17 * * 1-5 /pic/notice.bmp
```

- 分钟 `0..59`、小时 `0..23`、日期 `1..31`、月份 `1..12`、星期 `0..7`（0 和 7 都是周日）。支持 `*`、列表 `1,3,5`、范围 `1-5`、步长 `*/15` / `9-17/2`。
- 仅数字字段，没有秒、年份、`@daily`、名称、环境变量或命令执行。路径相对 TF 根目录，支持空格和中文文件名；不支持引号转义、行尾注释及 `..`，支持全行 `#` 注释。
- 日期和星期都受限制时使用标准 cron 的 **OR**；任一字段以 `*` 开头时用 **AND**。`0 9 1 * 1` 表示每月 1 日或周一，`0 9 * * 1` 表示周一。
- “最近事件决定当前内容”：画面保持到下一条事件，重启查找最近一次匹配，不把错过的全部事件逐一重放。
- 同分钟冲突时最后一行优先。过去/未来查找上限 8 年，RTC 范围 2000..2099 年；无历史事件时使用默认内容或保留旧画面。
- 文件内容和显示配置一致就跳过刷新，即使新事件再次指定同一内容。卡片修改在下一次唤醒/分钟检查时读取，不会主动唤醒已关机的主控。

## TF 卡示例

将 `examples/tf-card/` 内容复制到 FAT32 卡根目录：

```text
schedule.cron
config.json
fonts/sign.e6f
text/default.txt
text/open.txt
text/closed.txt
text/weekend.txt
pic/weekend.e6
```

示例素材已包含。程序生成 `.display-state.json` 指纹缓存，不要复制其他设备的缓存到卡上。只有刷新成功后才记录状态，缓存损坏或写入中断最多导致下次重复刷新。

`config.json` 可调整字体、默认内容、文本缩放、边距、颜色、180° 方向补偿与中间唤醒间隔。`default: null` 表示没有历史事件时保留画面。颜色编码：黑 0、白 1、黄 2、红 3、蓝 5、绿 6。

## 图片与中文文本

- 直接图片：**800×480、未压缩、24 位 BMP**，支持正/负高度行方向和标准行填充。非六色 RGB 映射到最近六色，不在主控进行照片抖动。
- 推荐图片：`.e6`，16 字节 `E6P1` 头加 192,000 字节打包像素，两个像素一字节，比 BMP 更省读取和转换时间。
- PNG/JPEG 先在电脑转换；Pico 不运行 Pillow。素材工具不替代主控端排程、TXT 排版及屏幕驱动。
- TXT 为 UTF-8，最多 8192 字节；支持换行、横向自动换行，制表符当 4 个空格。超出一屏或字体缺字会报错并保留原画面，不静默丢字。
- 默认 32×32 点阵字体，含 ASCII、基本中日韩统一表意文字、常用标点与全角符号（21,256 字形，约 2.8 MB）。字库按需读取，不整套载入内存。生僻字/扩展区字符需用覆盖对应字符的原始字体重新生成。

开发电脑安装 `requirements-dev.txt` 后：

```sh
# 检查当前与下一事件
python tools/check_schedule.py examples/tf-card/schedule.cron --at 2026-10-11T12:00:00
# 照片可增加 --dither；标识和文字通常不用
python tools/prepare_image.py photo.jpg notice.e6
python tools/prepare_image.py photo.jpg notice.bmp --dither
# 与设备相同的文字排版预览
python tools/render_preview.py examples/tf-card /text/open.txt open-preview.png
# 从合法使用的字体生成所需字形，可缩小字库
python tools/make_font.py font.ttf sign.e6f text1.txt text2.txt
# 本仓库示例字库生成方式，TTC 第 2 号为简体中文面
python tools/make_font.py /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc sign.e6f --font-index 2 --cjk
```

`text.scale` 默认 2，长文本可改为 1。默认白底黑字、左对齐、24 px 边距。

![营业中内容的逻辑方向预览](docs/previews/open.png)

## 程序与验证

`firmware/` 全部 Python 文件上传到主控内部闪存，示例内容放 TF 卡。使用 `tools/deploy.py` 上传，`tools/set_time.py` 校准外部 RTC，再重启；完整步骤与恢复方法见[部署文档](docs/deployment.md)。

```sh
python -m unittest discover -s tests -v
```

覆盖 cron 恢复/冲突/步长、闰年和跨月、RTC 寄存器、BUSY 超时及 SPI 错误、像素打包、BMP 行方向、中文字体、TXT 溢出、刷新失败状态。独立 MicroPython 验证脚本是 `tests/micropython_smoke.py`，须提供可写的 TF 卡副本，不在带真实缓存的卡上运行。该脚本已在 **320 KiB Unix MicroPython 堆**限制下通过；这验证了缓冲复用与语言兼容，不能代替 RP2350 实测。

电池模式最多每 6 小时检查远期事件，以应对 RTC 没有月/年比较字段。实机耗电和刷新速度待测，不承诺官方相框固件的同等续航或秒级切换。

第三方驱动及字体说明见 [licenses/](licenses/README.md)。
