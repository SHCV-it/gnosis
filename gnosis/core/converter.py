"""
HTML to Markdown converter.

Converts HTML content to clean, LLM-friendly markdown with configurable
tag exclusions, boilerplate stripping, and content extraction.
"""

import html as html_lib
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from gnosis.config.settings import ConverterSettings

# Minimum character count for an element to be considered content
MIN_CONTENT_THRESHOLD = 200


@dataclass
class ConversionStats:
    """How the converter transformed the source HTML."""

    source_chars: int = 0
    markdown_chars: int = 0
    stripped_elements: int = 0
    retention_ratio: float = 1.0

# Class tokens that mark permalink anchors inside headings
# (e.g. Sphinx/ReadTheDocs 'headerlink' anchors rendered as '#').
_HEADING_ANCHOR_CLASSES = {"headerlink", "anchor", "heading-anchor", "permalink"}


# Structural root elements that must never be stripped — decomposing
# <html> or <body> would destroy the entire document tree.
_PROTECTED_TAGS = {"html", "head", "body"}


def _markdown_text(markdown: str) -> str:
    """Strip markdown markup to approximate visible text (for retention ratio)."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`>~]", "", text)
    return " ".join(text.replace("|", " ").split())


class HTMLToMarkdownConverter:
    """
    Converts HTML to clean Markdown.

    Handles headers, code blocks, lists, tables, links, images, and emphasis
    while excluding configured tags and extracting main content.
    """

    def __init__(self, settings: Optional[ConverterSettings] = None, verbose: bool = False):
        """
        Initialize the converter.

        Args:
            settings: Converter settings. Uses defaults if None.
            verbose: Enable verbose logging of conversion process.
        """
        self.settings = settings or ConverterSettings()
        self.verbose = verbose
        self.stats = ConversionStats()

    def convert(self, html: str, base_url: Optional[str] = None) -> str:
        """
        Convert HTML to Markdown.

        Args:
            html: The HTML content to convert.
            base_url: Base URL for resolving relative links.

        Returns:
            Clean Markdown string.
        """
        soup = BeautifulSoup(html, "lxml")
        self.stats = ConversionStats()

        # Remove HTML comments. Comment nodes subclass NavigableString, so
        # without this they leak into output as raw text (e.g. Confluence's
        # '<!-- data-loadable-begin="..." -->' SSR markers).
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()

        self.stats.source_chars = len(" ".join(soup.get_text().split()))

        # Remove excluded tags
        for tag_name in self.settings.excluded_tags:
            for tag in soup.find_all(tag_name):
                self.stats.stripped_elements += 1
                tag.decompose()

        # Remove elements with excluded classes (exact token match)
        for class_name in self.settings.strip_classes:
            for tag in soup.find_all(class_=class_name):
                if tag.find_parent(self.settings.content_selectors):
                    continue
                self.stats.stripped_elements += 1
                tag.decompose()

        # Remove elements whose class tokens contain configured boilerplate
        # words (catches namespaced classes like 'bd-sidebar-primary')
        self._strip_by_class_words(soup)

        # Remove permalink anchors inside headings ('# Quickstart#' artifact)
        self._strip_heading_anchors(soup)

        # Remove sticky-header clone tables (single-row tables duplicating
        # the header of a following real table — Confluence/DataTables pattern)
        self._dedupe_shadow_tables(soup)

        # Find main content area(s)
        content = self._find_content(soup)

        # Convert to markdown
        if isinstance(content, list):
            # Multiple content areas - convert and concatenate
            if self.verbose:
                print(f"[Gnosis] Converting {len(content)} content area(s) to markdown...")
            
            markdown_parts = []
            for i, element in enumerate(content, 1):
                part_markdown = self._convert_element(element, base_url)
                if self.verbose:
                    chars_in = len(element.get_text().strip())
                    chars_out = len(part_markdown.strip())
                    print(f"[Gnosis]   Area {i}: {chars_in} chars -> {chars_out} chars markdown")
                markdown_parts.append(part_markdown)
            
            markdown = "\n\n".join(markdown_parts)
        else:
            # Single content area
            markdown = self._convert_element(content, base_url)

        # Clean up the output
        self.stats.markdown_chars = len(markdown)
        self.stats.retention_ratio = round(len(_markdown_text(markdown)) / max(1, self.stats.source_chars), 4)
        markdown = self._clean_markdown(markdown)

        return markdown

    def _strip_by_class_words(self, soup: BeautifulSoup) -> None:
        """
        Strip elements whose class tokens contain configured boilerplate words.

        Each class token is split on '-' and '_' into words; the element is
        stripped if any word matches the strip_class_words set. This catches
        framework-namespaced boilerplate ('bd-sidebar-primary', 'site-toc')
        while leaving content like 'research-content' untouched (the word
        'research' != 'search').

        Args:
            soup: Parsed HTML document (modified in place).
        """
        words_config = {w.lower() for w in self.settings.strip_class_words}
        if not words_config:
            return

        def has_boilerplate_word(class_attr) -> bool:
            if not class_attr:
                return False
            tokens = class_attr if isinstance(class_attr, list) else [class_attr]
            for token in tokens:
                token_words = re.split(r"[-_]", str(token).lower())
                if any(w in words_config for w in token_words):
                    return True
            return False

        for tag in soup.find_all(class_=has_boilerplate_word):
            if tag.name and tag.name.lower() in _PROTECTED_TAGS:
                continue
            if tag.find_parent(self.settings.content_selectors):
                continue
            self.stats.stripped_elements += 1
            tag.decompose()

    def _strip_heading_anchors(self, soup: BeautifulSoup) -> None:
        """
        Remove permalink anchors inside headings.

        Docs generators (Sphinx, mkdocs, etc.) embed '<a class="headerlink"
        href="#...">#</a>' inside headings; without removal the '#' leaks
        into the markdown heading text.

        Args:
            soup: Parsed HTML document (modified in place).
        """
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            for anchor in heading.find_all("a"):
                classes = {str(c).lower() for c in (anchor.get("class") or [])}
                href = str(anchor.get("href", ""))
                if classes & _HEADING_ANCHOR_CLASSES or href.startswith("#"):
                    self.stats.stripped_elements += 1
                    anchor.decompose()

    def extract_metadata(self, html: str) -> dict:
        """
        Extract page metadata from HTML head and open-graph tags.

        Args:
            html: Raw HTML document.

        Returns:
            Dict with title, author, language, description, site_name,
            published_time, modified_time (missing values are empty strings).
        """
        soup = BeautifulSoup(html, "lxml")

        def meta(**attrs) -> str:
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return html_lib.unescape(str(tag["content"]).strip())
            return ""

        title = meta(property="og:title")
        if not title:
            title_tag = soup.find("title")
            if title_tag and title_tag.get_text():
                title = html_lib.unescape(title_tag.get_text().strip())

        language = ""
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            language = str(html_tag["lang"]).strip()
        if not language:
            language = meta(property="og:locale")

        return {
            "title": title,
            "author": meta(name="author")
            or meta(property="article:author")
            or meta(name="dc.creator"),
            "language": language,
            "description": meta(name="description") or meta(property="og:description"),
            "site_name": meta(property="og:site_name"),
            "published_time": meta(property="article:published_time"),
            "modified_time": meta(property="article:modified_time"),
        }

    def _dedupe_shadow_tables(self, soup: BeautifulSoup) -> None:
        """
        Remove single-row tables that duplicate the header row of a real table.

        Sticky-header implementations (Confluence 'pm-table-sticky-wrapper',
        DataTables fixed headers, etc.) clone the header row into a separate
        single-row table. Structurally: a table with exactly one row whose
        cells equal the first row of another, larger table is a shadow copy.

        Args:
            soup: Parsed HTML document (modified in place).
        """
        tables = soup.find_all("table")
        if len(tables) < 2:
            return

        def first_row_signature(table: Tag) -> tuple:
            row = table.find("tr")
            if not row:
                return ()
            return tuple(
                cell.get_text(strip=True) for cell in row.find_all(["th", "td"])
            )

        real_signatures = set()
        for table in tables:
            if len(table.find_all("tr")) > 1:
                sig = first_row_signature(table)
                if sig:
                    real_signatures.add(sig)

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) == 1:
                sig = first_row_signature(table)
                if sig and sig in real_signatures:
                    table.decompose()

    def _find_content(self, soup: BeautifulSoup):
        """
        Find the main content area(s) of the page.

        Content selectors are tried in order; the first selector that yields
        at least one element above the minimum content threshold wins. This
        lets precise, platform-specific selectors (e.g. '.markdown-body',
        '.ak-renderer-document') take precedence over generic landmarks
        ('main', '#content') that often wrap navigation chrome.

        Args:
            soup: Parsed HTML document.

        Returns:
            List of content elements, single element, or body as fallback.
        """
        if self.verbose:
            print("[Gnosis] Searching for content areas...")

        # Collect all potential content elements
        content_elements = []
        seen_elements = set()

        for selector in self.settings.content_selectors:
            matches = soup.select(selector)
            if self.verbose and matches:
                print(f"[Gnosis] Selector '{selector}' found {len(matches)} match(es)")

            if content_elements:
                # A previous selector already won — selectors are ordered by
                # precedence, so stop looking.
                if self.verbose and matches:
                    print("[Gnosis]   (ignored — content already found)")
                continue

            for element in matches:
                # Skip if already seen
                if id(element) in seen_elements:
                    continue

                text_content = element.get_text()
                text_length = len(text_content.strip())

                # Get element description for logging
                elem_id = element.get('id', '')
                elem_classes = ' '.join(element.get('class', [])[:3])  # First 3 classes
                elem_desc = f"{element.name}"
                if elem_id:
                    elem_desc += f"#{elem_id}"
                if elem_classes:
                    elem_desc += f".{elem_classes.replace(' ', '.')}"

                if text_length < MIN_CONTENT_THRESHOLD:
                    if self.verbose:
                        print(f"[Gnosis]   - Skipped {elem_desc}: {text_length} chars (below threshold)")
                    continue

                if self.verbose:
                    print(f"[Gnosis]   - Found {elem_desc}: {text_length} chars")

                content_elements.append(element)
                seen_elements.add(id(element))

        if self.verbose:
            print(f"[Gnosis] Found {len(content_elements)} content candidate(s) before deduplication")  # noqa: E501

        # Deduplicate: remove nested elements (same-selector matches can
        # nest, e.g. multiple 'article' elements inside each other)
        if len(content_elements) > 1:
            filtered_elements = []
            for element in content_elements:
                # Check if this element is contained in any other element
                is_nested = False
                for other in content_elements:
                    if other != element and element in other.descendants:
                        is_nested = True
                        break
                if not is_nested:
                    filtered_elements.append(element)

            removed_count = len(content_elements) - len(filtered_elements)
            if self.verbose and removed_count > 0:
                print(f"[Gnosis] Removed {removed_count} nested element(s)")

            content_elements = filtered_elements

        # Calculate total characters
        if content_elements and self.verbose:
            total_chars = sum(len(e.get_text().strip()) for e in content_elements)
            print(f"[Gnosis] Final content areas: {len(content_elements)} element(s), {total_chars} total chars")

        # Return results
        if not content_elements:
            if self.verbose:
                print("[Gnosis] No content areas found, falling back to <body>")
            # Fallback to body
            body = soup.find("body")
            if body:
                return body
            # Last resort: return the whole soup
            return soup

        # Return list if multiple, single element if one
        if len(content_elements) == 1:
            return content_elements[0]
        return content_elements

    def _convert_element(self, element, base_url: Optional[str] = None) -> str:
        """
        Recursively convert an HTML element to Markdown.

        Args:
            element: BeautifulSoup element to convert.
            base_url: Base URL for resolving relative links.

        Returns:
            Markdown string.
        """
        # HTML comments carry no content (SSR markers, template hints)
        if isinstance(element, Comment):
            return ""

        if isinstance(element, NavigableString):
            text = str(element)
            # Collapse whitespace but preserve single spaces
            text = re.sub(r"[ \t]+", " ", text)
            return text

        if not isinstance(element, Tag):
            return ""

        tag_name = element.name.lower()

        # Headers
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            text = self._get_text_content(element).strip()
            if text:
                return f"\n\n{'#' * level} {text}\n\n"
            return ""

        # Paragraphs
        if tag_name == "p":
            text = self._convert_children(element, base_url).strip()
            if text:
                return f"\n\n{text}\n\n"
            return ""

        # Line breaks
        if tag_name == "br":
            return "\n"

        # Horizontal rules
        if tag_name == "hr":
            return "\n\n---\n\n"

        # Bold/Strong
        if tag_name in ("strong", "b"):
            text = self._convert_children(element, base_url).strip()
            if text:
                return f"**{text}**"
            return ""

        # Italic/Emphasis
        if tag_name in ("em", "i"):
            text = self._convert_children(element, base_url).strip()
            if text:
                return f"*{text}*"
            return ""

        # Inline code
        if tag_name == "code" and element.parent and element.parent.name != "pre":
            text = self._get_text_content(element)
            if text:
                return f"`{text}`"
            return ""

        # Code blocks
        if tag_name == "pre":
            code_elem = element.find("code")
            if code_elem:
                code = self._get_text_content(code_elem)
                lang = self._detect_language(code_elem)
            else:
                code = self._get_text_content(element)
                lang = ""
            if code:
                return f"\n\n```{lang}\n{code.strip()}\n```\n\n"
            return ""

        # Links
        if tag_name == "a":
            href = element.get("href", "")
            if href and not href.startswith(("#", "javascript:")):
                if self.settings.absolute_urls and base_url:
                    href = urljoin(base_url, href)
                text = self._convert_children(element, base_url).strip()
                if text:
                    return f"[{text}]({href})"
            return self._convert_children(element, base_url)

        # Images
        if tag_name == "img" and self.settings.include_images:
            src = element.get("src", "")
            alt = element.get("alt", "")
            # Skip data-URI images: almost always 1x1 spacers/tracking pixels,
            # and they bloat output with base64 noise.
            if src.startswith("data:"):
                return ""
            if src:
                if self.settings.absolute_urls and base_url:
                    src = urljoin(base_url, src)
                return f"![{alt}]({src})"
            return ""

        # Unordered lists
        if tag_name == "ul":
            items = []
            for li in element.find_all("li", recursive=False):
                text = self._convert_children(li, base_url).strip()
                if text:
                    # Handle multi-line items
                    lines = text.split("\n")
                    item = f"- {lines[0]}"
                    for line in lines[1:]:
                        if line.strip():
                            item += f"\n  {line}"
                    items.append(item)
            if items:
                return "\n\n" + "\n".join(items) + "\n\n"
            return ""

        # Ordered lists
        if tag_name == "ol":
            items = []
            start = int(element.get("start", 1))
            for i, li in enumerate(element.find_all("li", recursive=False)):
                text = self._convert_children(li, base_url).strip()
                if text:
                    lines = text.split("\n")
                    item = f"{start + i}. {lines[0]}"
                    for line in lines[1:]:
                        if line.strip():
                            item += f"\n   {line}"
                    items.append(item)
            if items:
                return "\n\n" + "\n".join(items) + "\n\n"
            return ""

        # Tables
        if tag_name == "table":
            return self._convert_table(element, base_url)

        # Blockquotes
        if tag_name == "blockquote":
            text = self._convert_children(element, base_url).strip()
            if text:
                lines = text.split("\n")
                quoted = "\n".join(f"> {line}" for line in lines)
                return f"\n\n{quoted}\n\n"
            return ""

        # Definition lists
        if tag_name == "dl":
            result = []
            for child in element.children:
                if isinstance(child, Tag):
                    if child.name == "dt":
                        text = self._convert_children(child, base_url).strip()
                        if text:
                            result.append(f"**{text}**")
                    elif child.name == "dd":
                        text = self._convert_children(child, base_url).strip()
                        if text:
                            result.append(f": {text}")
            if result:
                return "\n\n" + "\n".join(result) + "\n\n"
            return ""

        # Divs and spans - just process children
        if tag_name in ("div", "span", "section", "article", "main", "header", "footer"):
            return self._convert_children(element, base_url)

        # Default: process children
        return self._convert_children(element, base_url)

    def _convert_children(self, element: Tag, base_url: Optional[str] = None) -> str:
        """Convert all children of an element to Markdown."""
        result = []
        for child in element.children:
            result.append(self._convert_element(child, base_url))
        return "".join(result)

    def _get_text_content(self, element) -> str:
        """Get the text content of an element, preserving whitespace in code."""
        if isinstance(element, NavigableString):
            return str(element)
        if isinstance(element, Tag):
            return element.get_text()
        return ""

    def _detect_language(self, code_elem: Tag) -> str:
        """
        Detect the programming language from code element classes.

        Args:
            code_elem: The code element to check.

        Returns:
            Language identifier or empty string.
        """
        classes = code_elem.get("class", [])
        for cls in classes:
            if cls.startswith("language-"):
                return cls[9:]
            if cls.startswith("lang-"):
                return cls[5:]
            # Common language class names
            if cls in (
                "python",
                "javascript",
                "typescript",
                "java",
                "c",
                "cpp",
                "csharp",
                "go",
                "rust",
                "ruby",
                "php",
                "swift",
                "kotlin",
                "scala",
                "bash",
                "shell",
                "sql",
                "html",
                "css",
                "json",
                "yaml",
                "xml",
                "markdown",
            ):
                return cls
        return ""

    def _convert_table(self, table: Tag, base_url: Optional[str] = None) -> str:
        """
        Convert an HTML table to Markdown.

        Args:
            table: The table element.
            base_url: Base URL for resolving relative links.

        Returns:
            Markdown table string.
        """
        rows = []

        # Find header row
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                cells = header_row.find_all(["th", "td"])
                headers = [self._convert_table_cell(cell, base_url) for cell in cells]
                rows.append(headers)

        # Find body rows
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr", recursive=False):
            cells = tr.find_all(["td", "th"])
            row = [self._convert_table_cell(cell, base_url) for cell in cells]
            if row and any(row):  # Skip empty rows
                rows.append(row)

        # Some generators (e.g. Confluence) repeat the header row as the
        # first body row — drop the duplicate.
        if len(rows) >= 2 and rows[0] == rows[1]:
            rows.pop(1)

        if not rows:
            return ""

        # Determine column widths
        if len(rows) == 1:
            # Single row - treat as header
            headers = rows[0]
            separator = ["-" * max(3, len(h)) for h in headers]
            return (
                "\n\n| "
                + " | ".join(headers)
                + " |\n| "
                + " | ".join(separator)
                + " |\n\n"
            )

        # Multiple rows - first row is header
        headers = rows[0]
        separator = ["-" * max(3, len(h)) for h in headers]
        result = ["| " + " | ".join(headers) + " |"]
        result.append("| " + " | ".join(separator) + " |")

        for row in rows[1:]:
            # Pad row to match header length
            while len(row) < len(headers):
                row.append("")
            result.append("| " + " | ".join(row[: len(headers)]) + " |")

        return "\n\n" + "\n".join(result) + "\n\n"

    def _convert_table_cell(self, cell: Tag, base_url: Optional[str] = None) -> str:
        """
        Convert a table cell to single-line markdown.

        Raw newlines break markdown table rows, so multi-paragraph cells are
        joined with <br> (GFM-compatible). Pipe characters are escaped.

        Args:
            cell: The td/th element.
            base_url: Base URL for resolving relative links.

        Returns:
            Single-line cell markdown.
        """
        text = self._convert_children(cell, base_url).strip()
        # Collapse runs of whitespace/newlines into <br> separators
        text = re.sub(r"(\s*\n\s*)+", "<br>", text)
        # Escape pipes so they don't split the cell
        text = text.replace("|", "\\|")
        return text.strip()

    def _clean_markdown(self, markdown: str) -> str:
        """
        Clean up the generated Markdown.

        Args:
            markdown: Raw markdown string.

        Returns:
            Cleaned markdown string.
        """
        # Remove excessive blank lines (keep at most one blank line)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in markdown.split("\n")]
        markdown = "\n".join(lines)

        # Remove leading/trailing whitespace
        markdown = markdown.strip()

        # Ensure single newline at end
        if markdown:
            markdown += "\n"

        return markdown
