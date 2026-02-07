# Gnosis

Website to Markdown converter for LLM knowledge bases.

Downloads websites and converts them to clean, LLM-friendly markdown files.

## Features

- **Single page download**: Convert any webpage to markdown
- **Full site crawling**: Download all pages under a URL path with `--all`
- **Smart content extraction**: Automatically finds main content area
- **Configurable exclusions**: Skip navigation, sidebars, scripts via YAML config
- **Clean markdown output**: Headers, code blocks, tables, lists, links, images
- **Rate limiting**: Respectful crawling with configurable delays
- **Async downloads**: Fast concurrent page fetching

## Installation

```bash
# Clone the repository
git clone https://github.com/shcv-it/gnosis.git
cd gnosis

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install
pip install -e .
```

## Usage

### Single Page

Download and convert a single webpage:

```bash
gnosis https://docs.example.com/
```

Output: `docs.example.com.md`

### Full Site Crawling

Download all pages under a URL path:

```bash
gnosis https://docs.example.com/ --all
```

Output: Multiple markdown files like:
- `docs.example.com.md`
- `docs.example.com-getting-started.md`
- `docs.example.com-api-reference.md`

### Options

```
gnosis URL [OPTIONS]

Options:
  -a, --all           Download all child pages under the URL path
  -o, --output DIR    Output directory for markdown files
  -c, --config FILE   Path to YAML configuration file
  -f, --overwrite     Overwrite existing output files
  -q, --quiet         Suppress progress output
  --version           Show version and exit
  --help              Show this message and exit
```

### Examples

```bash
# Download single page to current directory
gnosis https://docs.python.org/3/tutorial/

# Download all pages to specific directory
gnosis https://docs.python.org/3/tutorial/ --all -o ./python-docs/

# Use custom config and overwrite existing files
gnosis https://example.com/ --config myconfig.yaml --overwrite
```

## Configuration

Create a `config.yaml` file to customize behavior:

```yaml
downloader:
  timeout: 30
  retries: 3
  user_agent: "Gnosis/1.0"
  rate_limit_ms: 500

crawler:
  max_depth: 10
  max_pages: 100

converter:
  excluded_tags:
    - script
    - style
    - nav
    - footer
    - aside
  content_selectors:
    - main
    - article
    - .content
  strip_classes:
    - sidebar
    - menu
    - toc

output:
  directory: "./"
  overwrite: false
```

See `config/default.yaml` for all available options.

## Output Format

Gnosis generates clean markdown optimized for LLMs:

- **Headers**: Preserved hierarchy (`#`, `##`, `###`, etc.)
- **Code blocks**: Fenced with language detection
- **Lists**: Both ordered and unordered
- **Tables**: Converted to markdown tables
- **Links**: Preserved with absolute URLs
- **Images**: Optional markdown image references

## Requirements

- Python 3.12+
- httpx
- beautifulsoup4
- lxml
- click
- rich
- pyyaml

## License

MIT License

## Author

Steffen Hoehne, SHCV.IT
