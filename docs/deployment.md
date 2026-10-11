# PhotoPainter (B) 部署与实机验证

目标为官方示例的 `PICO_BOARD=pico2` 引脚布局。云端没有连接产品，尚未刷机或验证实物；先核对主控为 RP2350/Pico 2 版本。程序包含电池关机与外部 PCF85063 唤醒逻辑，实际续航、引脚方向和唤醒效果以实机结果为准。

## 准备与恢复

1. 保留原 TF 卡内容，准备匹配产品的官方恢复 UF2。上传 ZIP 中 `extra_uf2` 是候选恢复文件，本项目未在你的设备上验证这些二进制；优先使用你已确认能运行的官方版本。
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

## TF 卡与程序上传

1. 使用 **FAT32** TF 卡；先备份，格式化不是程序自动执行的操作。本项目不假定 MicroPython 支持官方 C 示例的 exFAT 配置。
2. 将 `examples/tf-card/` 的**内容**复制到 TF 卡根目录，保留 `fonts/`、`text/`、`pic/` 目录及 `schedule.cron`、`config.json`。
3. 用电脑调整排程并检查：

```sh
python tools/check_schedule.py examples/tf-card/schedule.cron --at 2026-10-11T12:00:00
python -m mpremote connect list
python tools/deploy.py --port auto
python tools/set_time.py --port auto --timezone Asia/Shanghai
python -m mpremote connect auto reset
```

多设备连接时把 `auto` 换成实际串口，例如 `/dev/ttyACM0` 或 `COM3`。`set_time.py` 设置的是产品内的**外部 PCF85063**；`mpremote rtc` 通常设置主控内部时钟，不能替代它。程序启动不会将有效 RTC 重置为固定日期。

RTC 保存当地民用时间，cron 与它使用相同时间。默认校时为北京时间；换时区时调整 `--timezone`，夏令时地区需重新校时，设备没有网络校时服务。USB 握手可能带来几秒校时误差，需精确到秒时可在连接后的 REPL 直接校准。

## 电池运行

`boot.py` 尽早拉高 GP18 保持主控供电。程序完成以下流程：

1. 检查电池、TF 卡、RTC 和排程，寻找最近一次应显示的文件。
2. 校验内容，复用启动早期分配的一个 192 KB 帧缓冲，避免大块内存碎片。只有内容或排版变化才刷新。
3. 等待刷新结束、屏幕休眠，持久化成功显示内容的指纹。
4. 根据刷新**后的** RTC 时间计算下一事件，写入并核对闹钟；检查 INT 已释放且闹钟尚未到期。
5. 无 USB 时释放 GP18 电源保持。RTC 下次唤醒后重新启动，不让 Python 在内存里 sleep 到下一次。

PCF85063 闹钟只比较日/时/分/秒，不能比较月/年。远期排程默认最多每 **6 小时**中间唤醒检查，保持跨月无歧义；内容不变不刷新。配置可缩短间隔。修改卡片后可按产品原有唤醒键让主控重新读取；没有另行定义按键切页功能。

电池低于配置阈值（默认 3.1 V）时停止更新、关闭闹钟，等待 USB 充电。算法沿用官方分压比例，需实机校准。文件/卡片错误时保留旧画面，默认 5 分钟后 RTC 重试；RTC 无效或无法可靠设置闹钟时不假装已安排唤醒，需要接 USB 检查及校时。

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

关机后没有到时唤醒：接 USB 读取 RTC 时间和 `0x0B..0x0F` 闹钟寄存器，检查 GP6 INT、GP18 保持及 RTC 电源电路。云端模拟不能证明硬件行为。

USB 常供电时主控保持运行，每秒观察时间、每个新分钟读取配置和内容；显示可能因素材处理和全屏刷新延迟。不要设置秒级切换或多个独立队列画面的排程。刷新跨过新排程时，程序再次检查并更新至最新内容。
