# PhotoPainter (B) 部署与实机验证

目标为官方示例的 `PICO_BOARD=pico2` 引脚布局。已在 PhotoPainter (B) 上投入日常使用，显示与排版、RTC 校时与电池定时唤醒、缓存、NEXT 状态页与长按素材检查、日志及运行状态指示目前正常。低电量提醒、低压关机和再次充满电后的时间记录尚待完整电池循环验证。自动化及实机验证状态见 [README](../README.md#程序与验证)。

## 准备与恢复

1. 备份 TF 卡内容及当前可用的官方 UF2，准备恢复固件。官方示例包 `PhotoPainter_B.zip` 的 `extra_uf2` 包含不同刷新间隔版本，选择时核对产品型号与刷新间隔。
2. 下载官方 [MicroPython Pico 2 固件](https://micropython.org/download/RPI_PICO2/)，本项目语言验证版本为 **v1.26.0**。不要刷入 RP2040 Pico 或 Pico 2 W 固件。官方板型固件不包含 PhotoPainter 驱动，由本仓库 Python 模块适配。
3. 按产品说明进入 BOOTSEL，连接 USB 后将对应 UF2 拖入启动盘。该操作替换原应用固件；恢复时重新进入 BOOTSEL 并刷回已准备的官方 UF2。
4. 首次上传、校时和检查使用 USB 供电；成功后再拔掉 USB 验证电池模式。

## 开发电脑

在仓库目录使用 Python 3.10+：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Windows 使用 `.venv\Scripts\activate`。设备端只运行 MicroPython，不需要安装 Pillow、mpremote 或这些电脑工具。

Windows 的 `zoneinfo` 需要 `tzdata` 提供 IANA 时区数据库，已包含在依赖清单中。若已有虚拟环境出现 `No module named 'tzdata'` 或 `No time zone found with key Asia/Shanghai`，重新运行 `python -m pip install -r requirements-dev.txt` 后再校时。

## TF 卡与程序上传

1. 使用 **FAT32** TF 卡；先备份，格式化不是程序自动执行的操作。本项目不假定 MicroPython 支持官方 C 示例的 exFAT 配置。
2. 将 `examples/tf-card/` 的**内容**复制到 TF 卡根目录，保留 `fonts/`、`text/`、`pic/` 目录及 `cron`、`config.json`。
3. 用电脑调整排程并检查：

```sh
python tools/check_schedule.py examples/tf-card/cron --at 2026-10-11T12:00:00
python -m mpremote connect list
python tools/deploy.py --port auto
python tools/set_time.py --port auto --timezone Asia/Shanghai
python -m mpremote connect auto reset
```

多设备连接时把 `auto` 换成实际串口，例如 `/dev/ttyACM0` 或 `COM3`。`set_time.py` 设置的是产品内的**外部 PCF85063**；`mpremote rtc` 通常设置主控内部时钟，不能替代它。程序启动不会将有效 RTC 重置为固定日期。

已有设备升级时保留 TF 卡现有排程和素材，先 `git pull`，将 `examples/tf-card/fonts/status.e6f` 复制到 TF 的 `fonts/`。参照新的 `examples/tf-card/config.json` 修改卡上配置：删除顶层 `status_seconds`，添加 `next` 对象；删除 `logging.debug` / `logging.warnings`，使用 `logging.level`。其余个人设置保留。随后执行 `python tools/deploy.py --port COM8`、`python -m mpremote connect COM8 reset`。有效 RTC 无需重新校时；新配置不兼容旧字段。

从旧字库升级至思源黑体时，将 `examples/tf-card/fonts/sign.e6f`（约 11 MB）及同目录 `OFL.txt` 复制到 TF 卡的 `fonts/`，并将 `text.scale` 设为 **1**。字体保存在 TF 卡；`deploy.py` 上传 Python 模块至 Pico 内部闪存。字库大小改变会自动重建 TXT/Markdown 像素缓存。示例 `notice.md` 和 `pic/weekend.e6` 使用当前思源黑体排版。

排程文件统一命名为 **`cron`**，没有扩展名。已有 TF 卡需将旧排程文件重命名为 `cron`，并把 `config.json` 中的 `cron` 设置改为 `"/cron"`，保留原排程内容，再上传新版程序并重启。

RTC 保存当地民用时间，cron 与它使用相同时间。默认校时为北京时间；换时区时调整 `--timezone`，夏令时地区需重新校时，设备没有网络校时服务。USB 握手可能带来几秒校时误差，需精确到秒时可在连接后的 REPL 直接校准。

## 电池运行

`boot.py` 尽早拉高 GP18 保持主控供电。程序完成以下流程：

1. 检查电池、TF 卡、RTC 和排程，寻找最近一次应显示的文件。
2. 校验内容，复用启动早期分配的一个 192 KB 帧缓冲。TXT/Markdown 首次生成同目录 `.e6cache`，此后直接读取最终像素；缓存有内容/参数标识及像素 SHA-256，损坏会重建。只有显示内容变化才刷新。
3. 等待刷新结束、屏幕休眠，持久化成功显示内容的指纹。
4. 根据刷新**后的** RTC 时间计算下一事件，写入并核对闹钟；检查 INT 已释放且闹钟尚未到期。
5. 无 USB 时释放 GP18 电源保持。RTC 下次唤醒后重新启动，不让 Python 在内存里 sleep 到下一次。

PCF85063 闹钟只比较日/时/分/秒，不能比较月/年。远期排程默认最多每 **6 小时**中间唤醒检查，保持跨月无歧义；内容不变不刷新。配置可缩短间隔。按 NEXT 可手动唤醒并查看状态页，显示完成后等待 60 秒，恢复最新排程后再关机。

预估电量低于 10% 时，在内容右下角叠加红色电池图标，图片也适用，充电恢复后去掉；显示状态记录包含图标状态，原文本缓存不受影响。电池电压低于配置阈值（默认 3.1 V）时关闭闹钟，将原画面替换为白底红色空电池，等待刷新完成后关闭主控，等待 USB 充电。最后一屏不需要字体或素材；刷新或写卡失败会记录异常，仍尝试关闭主控。阈值可在 2.8–3.5 V 范围内调整，需按实测预留最后一次全屏刷新的电量；硬件保护断电后不能再更新屏幕。

电压算法沿用官方分压比例，需实机校准。文件/卡片错误时保留旧画面，默认 5 分钟后 RTC 重试；RTC 无效或无法可靠设置闹钟时不假装已安排唤醒，需要接 USB 检查及校时。

## 首次实机检查

使用 `python -m mpremote connect auto repl` 观察串口；Ctrl-C 可停止应用。USB 启动时预留 5 秒中断窗口。

- 检查 `import sys; print(sys.implementation)` 确认为 Pico 2/RP2350 对应固件。
- 读取 RTC，确认真实年月日、时分秒，以及断电后仍能走时。
- 列出 `/sd`，确认 FAT32 卡能挂载，字体及内容路径存在。
- 显示文本或六色图，确认方向。默认 `rotation=180` 对齐官方 BMP 方向；安装方向相反时改为 `0`。
- 测量刷新时长和可用堆；出现 `MemoryError` 时记录 `gc.mem_free()`，不要另加一个 RGB 整帧缓冲。
- 设置两条间隔至少几分钟、内容不同的排程。拔 USB，确认主控关机、画面保留、到时重新启动并切换。
- 以相同内容重复排程，确认输出 `Content unchanged`，屏幕不重复刷新。
- 测试跨午夜，以及错过前一时间后手动重启，确认恢复最近内容。

关机后没有到时唤醒：接 USB 读取 RTC 时间和 `0x0B..0x0F` 闹钟寄存器，检查 GP6 INT、GP18 保持及 RTC 电源电路。

USB 常供电时主控保持运行，约每 100 ms 观察按键和时间、每个新分钟读取配置和内容。显示仍需完成屏幕全屏刷新；刷新跨过新排程时，程序再次检查并更新至最新内容。

## 缓存、Markdown 和耗时

需要快速验证时，把 [examples/fast-switch/cron](../examples/fast-switch/cron) 复制到 TF 根目录替换 `cron`，保留原排程副本，并确认配置为 `"cron": "/cron"`。该样本每分钟切换一次营业 TXT、休息 TXT、彩色 Markdown、E6 图片，四分钟一轮；使用仓库自带的 `fonts/`、`text/`、`pic/` 素材。重启后立即显示当前分钟对应内容，之后按整分钟切换。

以 `text/open.txt`、`text/closed.txt` 两项 TXT 排程检查缓存：分别显示一遍后，TF 卡上应出现同目录 `.e6cache` 文件，每份 192,076 字节。设置 `logging.level=DEBUG` 后，缓存命中输出 `Text cache hit`，不再出现 `text_render`；源文件、排版、方向或字库大小/修改时间变化时输出 `Text cache rebuild`。删除缓存可以强制重建；更新字库时若保留了原大小及时间戳，也需要删除缓存。

Markdown 语法与六色文字见 [README](../README.md)，可先预览：

```sh
python tools/render_preview.py examples/tf-card /text/notice.md notice-preview.png
```

ACT 在屏幕初始化、像素传输、BUSY 刷新等待和休眠期间常亮；TF 卡初始化及实际读写时约 5 Hz 闪烁；其余时间熄灭。屏幕更新常亮优先于 TF 卡闪烁，因而刷新期间写日志不会打断常亮。TF 指示接在 VFS 底层块设备，图片、文本、字体、缓存、配置、排程、日志、状态保存及同步都自动覆盖；纯计算与 RTC 操作不会点亮 ACT。短暂读写可能只看到短闪，结束立即熄灭。刷新异常或中断也会熄灯并关闭屏幕供电。

日志中 `fingerprint` 是输入检查，`text_cache` 是缓存读取或重建，`text_render` 只在重建时出现；`panel_init`、`frame_upload`、`panel_power_on`、`panel_refresh`、`panel_sleep` 分别对应屏幕阶段，`display` 是整个驱动过程，不能与内部阶段相加。屏幕驱动维持官方正常全屏波形，像素缓存缩短准备时间。

既有 USB 实机日志记录：旧 32×32 字库的 TXT 首次排版约 4.47–5.17 秒、缓存读取约 1.76 秒、屏幕 `panel_refresh` 约 19.09 秒，缓存命中后完整切换约 21.76 秒。这组数据对应旧字库和当时的运行条件；当前思源黑体的准备耗时可能不同，缓存命中仍会绕过字库读取与绘制。

## 日志设置与读取

所有级别统一写入 TF 的 `/logs/YYYY-MM-DD.log`，按 RTC 当地日期跨日切换、同日重启追加。`logging.level` 同时过滤串口与文件，默认 `INFO`；`DEBUG` 包含调试与耗时，`WARNING` 只保留警告/异常，`ERROR` 只保留异常，`OFF` 关闭记录。`directory` 默认 `/logs`，`max_bytes` 默认 65,536，`backup_count` 默认 3；同日超限轮转为 `.log.1` 等，每日最多 256 KiB，旧日期不自动删除。格式为 `[当地 RTC 时间] [级别] 内容`；RTC 无效时使用 `uptime_ms` 并暂存 `undated.log`。设置在下一次唤醒/分钟检查或开始状态/预览时读取。

USB 连接、退出其他占用串口的 REPL/Thonny 后，可从仍已挂卡的设备读取日志（`resume` 避免软重启丢失 `/sd` 挂载）：

```sh
python -m mpremote connect COM8 resume fs cp :/sd/logs/2026-10-12.log ./2026-10-12.log
python -m mpremote connect COM8 reset
```

示例命令中的日期改成实际需读取的日期。没有达到配置级别的记录时文件不会创建；也可把 TF 卡插入电脑读取 `/logs`。排查时使用 `DEBUG`，长期电池运行可设 `WARNING`。文件写入异常在串口报告、应用继续运行；挂卡前消息只有串口输出。旧的 `debug` / `warnings` 配置不再接受。

## NEXT 状态页检查

1. 正常画面短按 NEXT，松开后显示状态页；确认居中标题下方有“当前、充电、待机”和电池行，共四行。独立 `fonts/status.e6f` 使用 72×72 字格、60 px 思源黑体字形，完整日期时间一行。电池行左侧为电压、右侧固定右对齐百分比，没有“电量”标签，右下角保留低电量图标空间。
2. 从刷新完成起计 60 秒，确认恢复**当时最新**排程。再次短按重新采样/计时。配置 `next.status_seconds` 默认 `60`，范围 `1..600`。
3. 刷新期间按键会先记录，处理后再展示状态页；不会中断正在执行的屏幕波形。
4. 电池状态页等待期间主控保持运行，恢复画面后重新设置 RTC 并关机。无 RTC 闹钟标志的电池上电视为手动唤醒。
5. “充电”为上一次观察到充满电的时间；USB 下先看到 GP17 低电平充电，之后非充电且电压至少 4.1 V 才记录。`.charge-state.json` 在 TF 上持久保存，临时文件支持断电恢复；待机由 RTC 当前时间减去充满时间，跨关机/重启累计。初次使用或程序未观察到充满时显示“未知”，不会把满电启动当成充满时间。检测在主循环进行，刷新会延后采样；调时早于记录时待机显示“未知”。
6. 时间、电压及百分比在生成页面时采样，不每秒刷新；电量仍是电压曲线估计。USB 供电下拔掉电池仍可能显示 100%，程序没有独立电池接入检测；切断全部供电后墨水屏保留原值。

只有同时没有默认内容、历史排程和之前已知正常文件时，程序会保留原画面并记录警告，避免显示状态页后无法恢复。

## NEXT 长按素材检查

按住 NEXT 至少 3 秒（`next.long_press_ms=3000`）按 cron 文件行顺序显示全部有效行的素材，忽略排程日期时间，包含重复路径。每项从刷新完成起停留 60 秒（`next.preview_seconds=60`）；失败素材记录异常并跳过，空 cron 保留日常画面。遍历结束恢复当时最新排程，电池模式之后才设 RTC 并关机。检查期间保持主控供电，PWR 常亮，ACT 按刷新/读卡指示。短按进入状态页，长按从头重新检查。

测试时把只在未来时间或不可能日期匹配的文件也加入 cron，确认仍会预览；在预览期间跨过日常排程的时间，确认结束后恢复最新内容。启动 5 秒窗口和屏幕刷新期间的按键边沿会记录，长按不会同时触发短按状态页；刷新完成后再执行对应操作。重启/断电后直接恢复日常排程，不续播临时检查。

## PWR 指示检查

升级指示灯功能只需上传新版 Python 模块并重启，无需修改 TF 卡配置。PWR（GP26）采用以下逻辑：

| 状态 | PWR |
| --- | --- |
| 启动初始化、读卡/排程、绘制、屏幕刷新、异常处理、设置 RTC 唤醒 | 常亮，充电时也常亮 |
| 主控计时等待：状态页 60 秒、USB 排程等待、禁用电池休眠、启动 5 秒窗口、异常重试 | 常亮，充电时也常亮 |
| 已停止固件，USB REPL 下 GP17 充电状态为低 | 约 1 Hz 闪烁，亮/灭各 0.5 秒 |
| 已停止固件且未充电或充满 | 熄灭 |
| 释放电池供电保持之前 | 熄灭 |

状态页的 60 秒由主控单调计时器计算，从刷新完成开始，不通过外部 RTC 唤醒；期间主控保持供电，PWR 常亮，ACT 熄灭，发生 TF 卡读写时短闪。恢复日常画面后，电池模式重新安排外部 RTC 闹钟并关闭主控，此时 PWR 熄灭。USB 排程轮询及禁用电池休眠时的等待也保持 PWR 常亮。

充电闪烁只在停止固件后使用后台软定时器。实机检查时，固件运行及软件计时等待应一直常亮；按 Ctrl-C 返回 REPL 后，充电中闪烁，充满后熄灭。信号来自 GP24/GP17；它不用于判断电池是否接入。
