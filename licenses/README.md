# Third-party materials

- `firmware/epaper.py`: adapted from Waveshare PhotoPainter_B commit fc2b261e985934bf67d99aa26358e463deb0aa65. MIT notice: waveshare-MIT.txt. Changed to MicroPython SPI, chunked transfers, explicit BUSY timeout, and controlled screen power.
- `firmware/sdcard.py`: unmodified micropython-lib SPI SD driver at f652fb2dfdd231e9c9c0cc1a10e12fdc9025ce95. License: micropython-lib-LICENSE.txt (MIT and the upstream historical notices).
- `examples/tf-card/fonts/sign.e6f`: generated bitmap font **SignBitmap64**, rasterized from Adobe's official **Source Han Sans SC Regular** (思源黑体简体中文 Regular), 52 px in a 64×64 px cell. Contains 21,256 glyphs; the original OTF is not bundled. Copyright 2014–2025 Adobe; SIL Open Font License 1.1 and the reserved font name notice are preserved in [sign64-OFL.txt](sign64-OFL.txt) and TF-card [fonts/OFL.txt](../examples/tf-card/fonts/OFL.txt). The generated font uses the name SignBitmap64 rather than the reserved font name.
- `examples/tf-card/fonts/status.e6f`: generated bitmap font **SignStatus72**, from the same licensed Source Han Sans SC Regular source, 60 px in a 72×72 px cell. Contains 109 glyphs for the built-in status page, including ASCII and “未知”. The same Adobe copyright and SIL OFL notice apply.

Source OTF: [SourceHanSansSC-Regular.otf](https://github.com/adobe-fonts/source-han-sans/blob/a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2/OTF/SimplifiedChinese/SourceHanSansSC-Regular.otf), upstream release commit `a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2`.

Source SHA-256: `f1d8611151880c6c336aabeac4640ef434fa13cbfbf1ffe82d0a71b2a5637256`.

Reproduce with Pillow 11.3.0: `python tools/make_font.py SourceHanSansSC-Regular.otf examples/tf-card/fonts/sign.e6f --cell 64 --size 52 --cjk`. The earlier Noto font's notice remains in `noto-cjk-copyright.txt` for historical attribution.

Reproduce the status font: `python tools/make_font.py SourceHanSansSC-Regular.otf examples/tf-card/fonts/status.e6f --cell 72 --size 60`.
