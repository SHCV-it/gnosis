"""
HTML to Markdown converter.

Converts HTML content to clean, LLM-friendly markdown with configurable
tag exclusions and content extraction.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from gnosis.config.settings import ConverterSettings

# Minimum character count for an element to be considered content
MIN_CONTENT_THRESHOLD = 200


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

        # Remove excluded tags
        for tag_name in self.settings.excluded_tags:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove elements with excluded classes
        for class_name in self.settings.strip_classes:
            for tag in soup.find_all(class_=lambda x: x and class_name in x):
                tag.decompose()

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
        markdown = self._clean_markdown(markdown)

        return markdown

    def _find_content(self, soup: BeautifulSoup):
        """
        Find all main content areas of the page.

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
            print(f"[Gnosis] Found {len(content_elements)} content candidate(s) before deduplication")

        # Deduplicate: remove nested elements
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
                headers = [self._convert_children(cell, base_url).strip() for cell in cells]
                rows.append(headers)

        # Find body rows
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr", recursive=False):
            cells = tr.find_all(["td", "th"])
            row = [self._convert_children(cell, base_url).strip() for cell in cells]
            if row and any(row):  # Skip empty rows
                rows.append(row)

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

    def _clean_markdown(self, markdown: str) -> str:
        """
        Clean up the generated Markdown.

        Args:
            markdown: Raw markdown string.

        Returns:
            Cleaned markdown string.
        """
        # Remove excessive blank lines (more than 2 consecutive)
        markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)

        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in markdown.split("\n")]
        markdown = "\n".join(lines)

        # Remove leading/trailing whitespace
        markdown = markdown.strip()

        # Ensure single newline at end
        if markdown:
            markdown += "\n"

        return markdown
