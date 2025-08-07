from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="vital-chatwoot-bridge",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A bridge service connecting Vital AI to Chatwoot",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/vital-ai/vital-chatwoot-bridge",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.12",
    install_requires=[
        "fastapi==0.104.1",
        "uvicorn==0.24.0",
        "pydantic==2.10.6",
        "python-dotenv==1.0.0",
        "PyYAML==6.0.1",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "vital-chatwoot-bridge=vital_chatwoot_bridge.main:main",
        ],
    },
)
