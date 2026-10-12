# RP2350 六色墨水屏排程指示牌

在 Waveshare **PhotoPainter (B)** 的 Pico 2 主控上运行 **MicroPython**。从 TF 卡读取类似 cron 的排程，用图片或 UTF-8 TXT 替代 cron 命令。使用产品已有电池和 PCF85063 RTC 定时唤醒；完成更新后关闭主控，墨水屏保持画面。

用户已在实机确认基本显示、RTC 校时和电池定时循环刷新，USB 日志确认了文本缓存命中、NEXT 状态页及 60 秒恢复流程。程序通过云端单元测试及 MicroPython v1.26.0 Unix 验证，思源黑体、低电量画面和 NEXT 电池唤醒继续实测。从[部署与实机验证](docs/deployment.md)开始，硬件来源见[产品分析](docs/product-analysis.md)。

## 排程格式

```cron
# 分 时 日 月 周  TF卡路径
0 9 * * 1-5 /text/open.txt
0 18 * * 1-5 /text/closed.txt
0 0 * * 6,0 /pic/weekend.e6
*/30 9-17 * * 1-5 /pic/notice.bmp
0 12 * * * /text/notice.md
```

- 分钟 `0..59`、小时 `0..23`、日期 `1..31`、月份 `1..12`、星期 `0..7`（0 和 7 都是周日）。支持 `*`、列表 `1,3,5`、范围 `1-5`、步长 `*/15` / `9-17/2`。
- 仅数字字段，没有秒、年份、`@daily`、名称、环境变量或命令执行。路径相对 TF 根目录，支持空格和中文文件名；不支持引号转义、行尾注释及 `..`，支持全行 `#` 注释。
- 日期和星期都受限制时使用标准 cron 的 **OR**；任一字段以 `*` 开头时用 **AND**。`0 9 1 * 1` 表示每月 1 日或周一，`0 9 * * 1` 表示周一。
- “最近事件决定当前内容”：画面保持到下一条事件，重启查找最近一次匹配，不把错过的全部事件逐一重放。
- 同一分钟多行匹配时，**靠前的行优先**，重启恢复也遵循此规则；之后更晚的事件仍会替换画面。过去/未来查找上限 8 年，RTC 范围 2000..2099 年；无历史事件时使用默认内容或保留旧画面。
- 文件内容和显示配置一致就跳过刷新，即使新事件再次指定同一内容。卡片修改在下一次唤醒/分钟检查时读取，不会主动唤醒已关机的主控。

快速测试用 [examples/fast-switch/cron](examples/fast-switch/cron)：每分钟依次切换营业 TXT、休息 TXT、彩色 Markdown 和 E6 图片，四分钟一轮。使用 `examples/tf-card/` 中的字体和素材，把测试文件复制到 TF 根目录，命名为 `cron`，确认 `config.json` 设置 `"cron": "/cron"`，再重启即可。cron 最小时间单位为一分钟。

## TF 卡示例

将 `examples/tf-card/` 内容复制到 FAT32 卡根目录：

```text
cron
config.json
fonts/sign.e6f
fonts/status.e6f
text/default.txt
text/open.txt
text/closed.txt
text/weekend.txt
text/notice.md
pic/weekend.e6
```

示例素材已包含。程序生成 `.display-state.json` 记录成功显示的内容，不要复制其他设备的状态文件到卡上。临时状态页会先标记需要恢复，避免断电后误认为正常内容仍在屏幕上。JSON 文件统一使用 4 个空格缩进。

`config.json` 可调整字体、默认内容、文本缩放、边距、颜色、180° 方向补偿与中间唤醒间隔。`default: null` 表示没有历史事件时保留画面。颜色编码：黑 0、白 1、黄 2、红 3、蓝 5、绿 6。

## 图片与中文文本

- 直接图片：**800×480、未压缩、24 位 BMP**，支持正/负高度行方向和标准行填充。非六色 RGB 映射到最近六色，不在主控进行照片抖动。
- 推荐图片：`.e6`，16 字节 `E6P1` 头加 192,000 字节打包像素，两个像素一字节，比 BMP 更省读取和转换时间。
- PNG/JPEG 先在电脑转换；Pico 不运行 Pillow。素材工具不替代主控端排程、TXT 排版及屏幕驱动。
- TXT 为 UTF-8，最多 8192 字节；支持换行、横向自动换行，制表符当 4 个空格。超出一屏或字体缺字会报错并保留原画面，不静默丢字。
- 默认使用 Adobe 官方**思源黑体简体中文 Regular**（Source Han Sans SC），以原生 52 px 字形生成 **64×64 点阵字格**，含 ASCII、基本中日韩统一表意文字、常用标点与全角符号（21,256 字形，约 11 MB）。字库放 TF 卡，按需读取，字形缓存最多 8 KiB，不整套载入内存。生僻字/扩展区字符需用覆盖对应字符的原始字体重新生成。

TXT 和 Markdown 第一次显示时，设备在**源文件同一目录**生成最终像素缓存，例如 `text/open.txt.e6cache`、`text/notice.md.e6cache`，每份 192,076 字节，含方向补偿和校验信息。此后直接读取打包像素，不查字库、不排版、不旋转，也不再逐次扫描整个字库。修改源文件内容、文字设置、方向或字库路径/大小/修改时间会重建；缓存损坏、缺失或写入中断时重新生成。源文本始终保留，缓存写入失败仍尝试显示。

字库更新用文件大小与修改时间识别；替换字库时若保留了相同大小与时间戳，请删除对应 `.e6cache` 强制重建。缓存是本程序内部格式，cron 仍指向 `.txt` / `.md` 源文件。

## 简单 Markdown 与文字颜色

使用 UTF-8 `.md` 文件，cron 中直接写文件路径：

```markdown
# <span style="color: red">营业通知</span>
欢迎光临
## 今日安排
**营业时间：**09:00—18:00
<span style="color: blue">请从右侧入口进入</span>
```

`#` 标题居中、比正文大一级；`##` 标题居中、与正文同字号；标题和 `**粗体**` 使用点阵加粗。每个源文本行换行，空行增加段落间距，过长自动折行，标题折行后仍居中。颜色支持 `black`、`white`、`yellow`、`red`、`blue`、`green`；白字需配合深色背景。`<span>` 与 `**` 必须在同一源行闭合，反斜杠可转义 `*`、`<`、反斜杠。支持的是这些排版语法，不包含表格、图片嵌入或完整 HTML/CSS。

普通 `.txt` 保持原样显示。统一文字颜色也可通过 `config.json` 的 `text.foreground` 设置，例如 `3` 表示红字。

![居中标题与彩色文字预览](docs/previews/notice.png)

## NEXT 临时状态页

短按 NEXT（GP19 低电平，松开后识别）显示居中的“设备状态”标题，使用独立 **72×72 思源黑体字库**（60 px 字形）。标题下方共四行：当前、充电、待机，以及左侧电压和固定右对齐百分比；最后一行显示“电池：3.75 V”，右侧“50%”，不显示“电量”文字。完整日期时间保持一行，右下角仍为低电量图标留出空间。刷新完成后等待 **60 秒**，恢复当时最新排程；再次短按会重新采样并计时。

“充电”显示上一次观察到充满电的时间；“待机”是 RTC 当前时间减去该时间，包含关机期间。USB 接入、GP17 从充电低电平变为非充电且电压至少 4.1 V 时记录到 TF 的 `.charge-state.json`，跨重启保留。初次使用、仅在满电后启动或充电完成时程序未运行，不能推算完成时间；没有记录时显示“未知”。充电状态在主循环检测，显示刷新会延后检测；RTC 调整到记录之前时待机显示“未知”。

按住 NEXT 至少 **3 秒**进入素材检查模式：按 cron 中有效行顺序显示每个文件，忽略排程时间，每项从刷新完成起保持 **60 秒**。重复路径也逐行显示；无法读取或绘制的文件记录异常并跳过。遍历结束恢复当时最新排程；期间短按进入状态页，长按从第一项重新开始。启动或刷新期间的按下/松开也会记录，不中断正在执行的屏幕波形。状态页和素材检查期间保持主控供电、PWR 常亮，恢复排程后电池模式再设 RTC 闹钟并关机。

按键设置归入 `config.json` 的 `next` 对象：`font` 默认 `/fonts/status.e6f`，`long_press_ms` 默认 `3000`（范围 `1000..10000`），`status_seconds` 和 `preview_seconds` 均默认 `60`（范围 `1..600`）。旧顶层 `status_seconds` 不再接受。电量仍按单节锂电池电压曲线粗估，受负载、充电和温度影响；当前不检测电池是否接入，USB 下移除电池仍可能显示 100%，断电后屏幕保留旧值。

![NEXT 状态页预览](docs/previews/status.png)

## PWR 电源灯

PWR（GP26）在固件运行期间常亮，包括启动初始化、读卡/排程、内容绘制与屏幕刷新，以及由主控自行计时的等待：NEXT 状态页的 60 秒、USB 下等待排程、关闭 `battery_sleep` 后等待排程、USB 启动的 5 秒中断窗口和异常重试。电池模式设置外部 RTC 闹钟并关闭主控后，等待 RTC 唤醒期间熄灭。按 Ctrl-C 停止固件、返回 USB REPL 后，正在充电时约每秒闪一次（亮 0.5 秒、灭 0.5 秒），未充电或充满时熄灭。固件运行期间，充电指示不会改变常亮状态。

充电判断使用官方信号：USB VBUS（GP24）为高且 CHARGE_STATE（GP17）为低。停止固件后的充电闪烁由后台软定时器驱动，不依赖 TF 卡配置。

## ACT 活动灯

ACT（GP25）在屏幕更新期间常亮，包含屏幕初始化、像素传输、刷新 BUSY 等待及屏幕休眠。TF 卡初始化和实际读写时约 **5 Hz** 闪烁（亮/灭各 0.1 秒），包括图片、文本、字库、像素缓存、排程、日志和状态记录；很短的读写可能只看到短闪。连续读写的闪烁相位不会因每个扇区重新开始，读写结束立即熄灭。屏幕更新期间写调试日志，仍优先保持常亮。

纯计算、RTC 操作和主控计时等待时 ACT 熄灭，等待期间若发生 TF 卡读写则短闪。状态页的 60 秒等待期间 PWR 常亮。刷新失败或按 Ctrl-C 中断刷新时，ACT 熄灭并关闭屏幕供电。无需修改 TF 卡配置。

## 低电量提示

预估电量**低于 10%**时，正常 TXT、Markdown、BMP、E6 画面及 NEXT 状态页的右下角叠加红色电池图标，带小块白底以便在照片上识别。图标不写入原素材或文本像素缓存；即使排程文件不变，跨过 10% 阈值也会刷新，充电恢复后自动去掉图标。电量在主控唤醒和运行检查时采样，关机期间不会持续监测。

电池供电时，电压低于 `low_battery_voltage`（默认 **3.1 V**），先关闭 RTC 闹钟，将整个显示内容替换为白底居中的红色空电池图标，等待屏幕刷新完成后关闭主控，留下提醒充电的画面。该画面直接绘制，不依赖 TF 卡素材或字库；成功显示后再次低压唤醒不重复刷新。接 USB 后重新恢复排程。最后一次刷新发生在低压阈值触发时，实际电池保护电路断电后已无法刷新；可按实测调高此阈值以预留刷新电量。

![图片上的低电量提示](docs/previews/low-battery.png)
![低压关机留下的画面](docs/previews/empty-battery.png)

## 调试与长期日志

`config.json` 的 `logging` 设置可修改，例如：

```json
{
    "logging": {
        "level": "INFO",
        "directory": "/logs",
        "max_bytes": 65536,
        "backup_count": 3
    }
}
```

示例完整配置见 [config.json](examples/tf-card/config.json)。所有符合最低级别的记录统一写入 `/logs/YYYY-MM-DD.log`，使用 RTC 当地日期，跨日自动换文件，同日重启追加。`level` 同时过滤串口和文件：`DEBUG` 保存全部，`INFO`（默认）过滤调试，`WARNING` 只保留警告与异常，`ERROR` 只保留异常，`OFF` 关闭记录。旧 `debug` / `warnings` 字段不再接受。异常附带堆栈，记录带时间和级别，例如 `[2026-10-12 21:30:00] [DEBUG] [timing] text_cache: 123 ms`。RTC 无效时用 `uptime_ms` 并保存到 `undated.log`；挂卡前只输出串口。

每日日志达到 `max_bytes` 后轮转为同日 `.log.1` 等，默认最多当前文件加 3 份备份，每日最多 256 KiB。旧日期文件保留，可按需要从 TF 卡归档或清理；旧 `debug.log` / `warnings.log` 不再写入。单条过大记录截断，写入后关闭并同步；文件 I/O 失败在串口报告并继续运行。`DEBUG` 增加写卡、耗电和 ACT 闪烁，长期电池运行可用 `WARNING`。ACT 常亮表示屏幕更新，闪烁表示 TF 读写。

开发电脑安装 `requirements-dev.txt` 后：

```sh
# 检查当前与下一事件
python tools/check_schedule.py examples/tf-card/cron --at 2026-10-11T12:00:00
# 照片可增加 --dither；标识和文字通常不用
python tools/prepare_image.py photo.jpg notice.e6
python tools/prepare_image.py photo.jpg notice.bmp --dither
# 与设备相同的文字排版预览
python tools/render_preview.py examples/tf-card /text/open.txt open-preview.png
python tools/render_preview.py examples/tf-card /text/notice.md notice-preview.png
python tools/render_preview.py examples/tf-card /pic/weekend.e6 low-battery.png --battery-voltage 3.4
# 从合法使用的字体生成所需字形，可缩小字库
python tools/make_font.py font.ttf sign.e6f text1.txt text2.txt
# 从 Adobe 官方仓库下载 SourceHanSansSC-Regular.otf 后，生成本仓库字库
python tools/make_font.py SourceHanSansSC-Regular.otf sign.e6f --cell 64 --size 52 --cjk
```

`text.scale` 默认 **1**，直接绘制原生点阵。默认白底黑字、左对齐、24 px 边距；需要较小正文时可生成 `--cell 32 --size 26` 的字库，保持 `scale: 1`。状态页单独使用 `next.font`，不受正文字库大小影响。
`make_font.py` 默认 `--cell 64 --size 52`，自动加入 NEXT 状态页文字；支持最大 72 px 字格。状态字库用 `--cell 72 --size 60` 生成。字体来源与 SIL OFL 许可见 [licenses](licenses/README.md)。升级需复制 `fonts/status.e6f`（约 70 KiB）到 TF 卡，并按新配置修改 `next` / `logging`；其余排程和素材保留。

![营业中内容的逻辑方向预览](docs/previews/open.png)

## 程序与验证

`firmware/` 全部 Python 文件上传到主控内部闪存，示例内容放 TF 卡。使用 `tools/deploy.py` 上传，`tools/set_time.py` 校准外部 RTC，再重启；完整步骤与恢复方法见[部署文档](docs/deployment.md)。

```sh
python -m unittest discover -s tests -v
```

覆盖 cron、RTC、BUSY/SPI、图片与字体、像素缓存复用/损坏/失效、Markdown 六色排版、日志轮转/堆栈、NEXT 防抖、60 秒恢复最新排程、低电量叠加及低压关机。独立 MicroPython 验证脚本是 `tests/micropython_smoke.py`，须提供可写的 TF 卡副本，不在真实卡上运行。该脚本已在 **320 KiB Unix MicroPython 堆**限制下通过，包含原生 64×64 思源黑体、Markdown、状态页、低电量图标和日志；这验证了缓冲复用与语言兼容，不能代替 RP2350 实测。

电池模式最多每 6 小时检查远期事件，以应对 RTC 没有月/年比较字段。实机耗电和刷新速度待测，不承诺官方相框固件的同等续航或秒级切换。

第三方驱动及字体说明见 [licenses/](licenses/README.md)。
