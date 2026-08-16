"""SP-404 MK2 Simple Converter - pip installation.

Installs the app and its dependencies so it can be launched from anywhere
with the `sp404-converter` command.

    pip install .          # or:  pip install -r requirements.txt  (deps only)

Note: styles.qss and icon.ico are placed next to the installed modules so the
app can find them. FFmpeg is expected on the system PATH (see README).
"""
import sysconfig

from setuptools import setup

DATA_FILES = [
    (sysconfig.get_paths()["purelib"], ["styles.qss", "icon.ico"]),
]

setup(
    name="sp404-converter",
    version="1.0.0",
    description=(
        "Convert audio samples to the Roland SP-404 MK2 format "
        "(44.1 kHz, 16-bit, stereo WAV)."
    ),
    long_description=None,
    long_description_content_type="text/markdown",
    author="SP-404 MK2 Simple Converter",
    license="MIT",
    py_modules=["gui", "converter"],
    data_files=DATA_FILES,
    entry_points={
        "console_scripts": [
            "sp404-converter=gui:main",
        ],
    },
    python_requires=">=3.10",
    install_requires=[
        "PySide6>=6.6.0",
        "ffmpeg-python>=0.2.0",
    ],
    classifiers=[
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3",
        "Topic :: Multimedia :: Sound/Audio :: Conversion",
    ],
)