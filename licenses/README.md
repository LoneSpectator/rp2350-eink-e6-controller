# Third-party materials

- `firmware/epaper.py`: adapted from Waveshare PhotoPainter_B commit fc2b261e985934bf67d99aa26358e463deb0aa65. MIT notice: waveshare-MIT.txt. Changed to MicroPython SPI, chunked transfers, explicit BUSY timeout, and controlled screen power.
- `firmware/sdcard.py`: unmodified micropython-lib SPI SD driver at f652fb2dfdd231e9c9c0cc1a10e12fdc9025ce95. License: micropython-lib-LICENSE.txt (MIT and the upstream historical notices).
- `examples/tf-card/fonts/sign.e6f`: rasterized from system NotoSansCJK-Regular.ttc, Simplified Chinese face, 26 px in a 32 px cell. Font copyright/OFL notice: noto-cjk-copyright.txt. Generated bitmap font named SignBitmap; source TTF is not bundled.
