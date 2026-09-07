"""Coverage tests for the HTML→Markdown converter's element-type dispatch and edge paths.

These target the branches that the main quality-guarantee suite (test_converter.py)
doesn't exercise: inline formatting, code-block language detection, list/quote/dl
rendering, image inclusion, single-row and ragged tables, and content-area
selection edge cases.
"""

from bs4 import BeautifulSoup

from gnosis.config.settings import ConverterSettings
from gnosis.core.converter import HTMLToMarkdownConverter


def convert(html: str, base_url: str = "https://example.com/", **settings) -> str:
    return HTMLToMarkdownConverter(settings=ConverterSettings(**settings)).convert(
        html, base_url=base_url
    )


PAD = "<p>" + ("padding content " * 30) + "</p>"


class TestInlineElements:
    def test_horizontal_rule(self):
        md = convert(f"<html><body><main><hr/>{PAD}</main></body></html>")
        assert "---" in md

    def test_strong_and_emphasis(self):
        md = convert(
            "<html><body><main><p><strong>bold text</strong> and "
            "<em>italic text</em> and <b>b</b> and <i>i</i></p>"
            f"{PAD}</main></body></html>"
        )
        assert "**bold text**" in md
        assert "*italic text*" in md
        assert "**b**" in md
        assert "*i*" in md

    def test_inline_code(self):
        md = convert(
            f"<html><body><main><p>run <code>pip install x</code> now</p>{PAD}</main></body></html>"
        )
        assert "`pip install x`" in md

    def test_link_resolves_relative_to_base(self):
        md = convert(
            f'<html><body><main><p>see <a href="/docs/start">the docs</a></p>{PAD}</main></body></html>'
        )
        assert "[the docs](https://example.com/docs/start)" in md

    def test_link_without_href_preserves_text(self):
        md = convert(f"<html><body><main><p><a>plain anchor</a></p>{PAD}</main></body></html>")
        assert "plain anchor" in md

    def test_empty_heading_returns_nothing(self):
        md = convert(f"<html><body><main><h1></h1><p>body</p>{PAD}</main></body></html>")
        assert md.count("#") == 0


class TestCodeBlocks:
    def test_pre_code_language_prefix(self):
        md = convert(
            f"<html><body><main><pre><code class='language-python'>print('hi')</code></pre>{PAD}</main></body></html>"
        )
        assert "```python" in md

    def test_pre_code_lang_short_prefix(self):
        md = convert(
            f"<html><body><main><pre><code class='lang-js'>const x = 1</code></pre>{PAD}</main></body></html>"
        )
        assert "```js" in md

    def test_pre_code_bare_language_name(self):
        md = convert(
            f"<html><body><main><pre><code class='rust'>fn main() {{}}</code></pre>{PAD}</main></body></html>"
        )
        assert "```rust" in md

    def test_pre_code_unknown_language(self):
        md = convert(
            f"<html><body><main><pre><code class='totally-unknown'>x</code></pre>{PAD}</main></body></html>"
        )
        assert "```\nx\n```" in md

    def test_pre_without_code(self):
        md = convert(f"<html><body><main><pre>raw text block</pre>{PAD}</main></body></html>")
        assert "raw text block" in md

    def test_detect_language_unit(self):
        conv = HTMLToMarkdownConverter()
        soup = BeautifulSoup("<code class='language-python'>x</code>", "lxml")
        assert conv._detect_language(soup.code) == "python"
        soup = BeautifulSoup("<code class='lang-ts'>x</code>", "lxml")
        assert conv._detect_language(soup.code) == "ts"
        soup = BeautifulSoup("<code class='json'>x</code>", "lxml")
        assert conv._detect_language(soup.code) == "json"
        soup = BeautifulSoup("<code>x</code>", "lxml")
        assert conv._detect_language(soup.code) == ""


class TestListsQuotesDefinitions:
    def test_unordered_list_multiline_item(self):
        md = convert(
            f"<html><body><main><ul><li>first line<br>second line</li><li>another</li></ul>{PAD}</main></body></html>"
        )
        assert "- first line" in md
        assert "second line" in md
        assert "- another" in md

    def test_ordered_list_with_start(self):
        md = convert(
            f"<html><body><main><ol start='5'><li>five</li><li>six</li></ol>{PAD}</main></body></html>"
        )
        assert "5. five" in md
        assert "6. six" in md

    def test_blockquote(self):
        md = convert(
            f"<html><body><main><blockquote><p>quoted wisdom</p></blockquote>{PAD}</main></body></html>"
        )
        assert "> quoted wisdom" in md

    def test_definition_list(self):
        md = convert(
            f"<html><body><main><dl><dt>Term</dt><dd>Definition text</dd></dl>{PAD}</main></body></html>"
        )
        assert "**Term**" in md
        assert ": Definition text" in md


class TestImages:
    def test_real_image_rendered_with_absolute_src(self):
        md = convert(
            f'<html><body><main><img src="/logo.png" alt="Logo"/>{PAD}</main></body></html>'
        )
        assert "![Logo](https://example.com/logo.png)" in md

    def test_image_disabled_when_include_images_false(self):
        md = convert(
            f'<html><body><main><img src="/logo.png" alt="Logo"/>{PAD}</main></body></html>',
            include_images=False,
        )
        assert "Logo" not in md


class TestTableEdges:
    def test_single_row_table_rendered(self):
        md = convert(
            f"<html><body><main><table><tr><th>A</th><th>B</th></tr></table>{PAD}</main></body></html>"
        )
        assert "| A | B |" in md
        assert "| --- | --- |" in md

    def test_ragged_rows_padded(self):
        md = convert(
            "<html><body><main><table><tr><th>A</th><th>B</th><th>C</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>{PAD}</main></body></html>"
        )
        assert "| 1 | 2 |  |" in md


class TestFindContent:
    def test_nested_candidates_collapse_to_outer(self):
        # Both <main> and an inner <div> match a selector; the inner (nested) one
        # must be removed so the outer (which contains everything) is kept.
        html = (
            "<html><body><main><div class='markdown-body'>"
            + ("nested content. " * 30)
            + "</div></main></body></html>"
        )
        md = convert(html)
        assert "nested content" in md

    def test_below_threshold_candidate_skipped_then_fallback(self):
        # A selector matches a tiny element (< threshold); it's skipped and the
        # converter falls back to <body>.
        html = "<html><body><main><div id='tiny'>x</div>" + ("body text. " * 40) + "</main></body></html>"
        md = convert(html)
        assert "body text" in md


class TestBoilerplateListClass:
    def test_class_attribute_as_list(self):
        md = convert(
            "<html><body>"
            "<div class='sidebar'><p>NAVIGATION NOISE HERE</p></div>"
            "<main>" + ("main content. " * 40) + "</main>"
            "</body></html>"
        )
        assert "NAVIGATION" not in md
        assert "main content" in md


class TestVerboseMode:
    def test_verbose_no_crash(self, capsys):
        conv = HTMLToMarkdownConverter(verbose=True)
        md = conv.convert(
            "<html><body><main><div class='markdown-body'>"
            + ("verbose content. " * 30)
            + "</div></main></body></html>",
            base_url="https://example.com/",
        )
        assert "verbose content" in md
        assert "[Gnosis]" in capsys.readouterr().out


    def test_verbose_fallback_to_body(self, capsys):
        conv = HTMLToMarkdownConverter(verbose=True)
        md = conv.convert(
            "<html><body>" + ("plain body. " * 40) + "</body></html>",
            base_url="https://example.com/",
        )
        assert "plain body" in md
        assert "falling back to <body>" in capsys.readouterr().out
