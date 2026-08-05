"""Setup configuration for Gnosis."""

from setuptools import setup, find_packages
from pathlib import Path


def read_requirements(filename):
    """Read requirements from file."""
    with open(filename) as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#") and not line.startswith("-r")
        ]


def read_qmd_requirements():
    """Read optional QMD integration requirements."""
    qmd_file = Path(__file__).parent / "requirements-qmd.txt"
    if not qmd_file.exists():
        return []
    return [
        line.strip()
        for line in qmd_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


setup(
    name="gnosis",
    version="1.1.2",
    author="Steffen Hoehne",
    author_email="steffen.hoehne@shcv.it",
    description="Website to Markdown converter for LLM knowledge bases",
    long_description=(Path(__file__).parent / "README.md").read_text()
    if (Path(__file__).parent / "README.md").exists()
    else "",
    long_description_content_type="text/markdown",
    url="https://github.com/shcv-it/gnosis",
    packages=find_packages(exclude=["tests"]),
    package_data={
        "gnosis": ["config/*.yaml"],
    },
    include_package_data=True,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Text Processing :: Markup",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Documentation",
    ],
    python_requires=">=3.12",
    install_requires=read_requirements("requirements.txt"),
    extras_require={
        # Heavy local-LLM dependencies for the --qmd-index pipeline
        "qmd": read_qmd_requirements(),
    },
    entry_points={
        "console_scripts": [
            "gnosis=gnosis.cli.main:main",
        ],
    },
    zip_safe=False,
)
