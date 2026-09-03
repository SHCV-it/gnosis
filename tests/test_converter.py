"""Tests for the HTML to Markdown converter quality guarantees."""

from gnosis.core.converter import HTMLToMarkdownConverter


def convert(html: str, base_url: str = "https://example.com/") -> str:
    return HTMLToMarkdownConverter().convert(html, base_url=base_url)


class TestCommentStripping:
    def test_html_comments_do_not_leak(self):
        """Confluence SSR markers (<!-- data-loadable-... -->) must not appear."""
        html = """
        <html><body><main>
        <!-- data-loadable-begin="UJdch:OP-5u" --><!-- data-loadable-end="UJdch:OP-5u" -->
        <h1>Title</h1>
        <p>Real content paragraph with enough text to matter here for the test case.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "data-loadable" not in md
        assert "<!--" not in md
        assert "Real content paragraph" in md


class TestHeadingAnchors:
    def test_headerlink_anchor_removed(self):
        """Sphinx/RTD permalink anchors must not glue '#' onto heading text."""
        html = """
        <html><body><main>
        <h1>Quickstart<a class="headerlink" href="#quickstart" title="Link to this heading">#</a></h1>
        <p>Body text body text body text body text body text body text body text.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "# Quickstart\n" in md or md.startswith("# Quickstart\n")
        assert "Quickstart#" not in md

    def test_fragment_only_anchor_removed(self):
        """Heading anchors pointing at fragments are boilerplate even without a class."""
        html = """
        <html><body><main>
        <h2>Install<a href="#install">¶</a></h2>
        <p>Body text body text body text body text body text body text body text.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "## Install" in md
        assert "¶" not in md


class TestTables:
    def test_multiline_cells_use_br_not_raw_newlines(self):
        html = """
        <html><body><main>
        <table>
          <thead><tr><th>Col A</th><th>Col B</th></tr></thead>
          <tbody>
            <tr><td><p>line one</p><p>line two</p></td><td>simple</td></tr>
            <tr><td>x</td><td>y</td></tr>
          </tbody>
        </table>
        <p>Padding content padding content padding content padding content.</p>
        </main></body></html>
        """
        md = convert(html)
        for line in md.splitlines():
            if line.startswith("|"):
                assert "\n" not in line  # sanity: rows are single lines
        assert "line one<br>line two" in md

    def test_pipes_in_cells_are_escaped(self):
        html = """
        <html><body><main>
        <table>
          <tr><th>Expression</th></tr>
          <tr><td>a | b</td></tr>
        </table>
        <p>Padding content padding content padding content padding content.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "a \\| b" in md

    def test_duplicate_header_row_removed(self):
        """Confluence repeats the header as first body row — keep it once."""
        html = """
        <html><body><main>
        <table>
          <thead><tr><th>Thema</th><th>IST</th></tr></thead>
          <tbody>
            <tr><th>Thema</th><th>IST</th></tr>
            <tr><td>real</td><td>data</td></tr>
          </tbody>
        </table>
        <p>Padding content padding content padding content padding content.</p>
        </main></body></html>
        """
        md = convert(html)
        assert md.count("| Thema | IST |") == 1
        assert "| real | data |" in md

    def test_sticky_shadow_table_removed(self):
        """Single-row sticky-header clone tables are stripped structurally."""
        html = """
        <html><body><main>
        <div class="pm-table-sticky-wrapper">
          <table><tbody><tr><th>Thema</th><th>IST</th></tr></tbody></table>
        </div>
        <div class="pm-table-wrapper">
          <table>
            <tbody>
              <tr><th>Thema</th><th>IST</th></tr>
              <tr><td>real</td><td>data</td></tr>
            </tbody>
          </table>
        </div>
        <p>Padding content padding content padding content padding content.</p>
        </main></body></html>
        """
        md = convert(html)
        assert md.count("| Thema | IST |") == 1
        assert "| real | data |" in md

    def test_legit_single_row_table_kept(self):
        """A genuine one-row table whose header matches nothing is kept."""
        html = """
        <html><body><main>
        <table><tbody><tr><td>only</td><td>row</td></tr></tbody></table>
        <p>Padding content padding content padding content padding content.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "only" in md and "row" in md


class TestBoilerplateWords:
    def test_namespaced_sidebar_stripped(self):
        """'bd-sidebar-primary' (pydata theme) is caught by word matching."""
        html = """
        <html><body>
        <div class="bd-sidebar-primary"><p>NAV NAV NAV should be gone entirely.</p></div>
        <main><p>Main content main content main content main content main content.</p></main>
        </body></html>
        """
        md = convert(html)
        assert "NAV NAV" not in md
        assert "Main content" in md

    def test_content_word_not_stripped(self):
        """'research-content' contains 'search' as substring but not as word."""
        html = """
        <html><body><main>
        <div class="research-content"><p>Important findings stay in the output text.</p></div>
        </main></body></html>
        """
        md = convert(html)
        assert "Important findings" in md

    def test_html_tag_with_toc_word_not_stripped(self):
        """Regression: <html class="vector-feature-toc-..."> must not be
        stripped — decomposing <html> destroys the entire DOM."""
        html = """
        <html class="vector-feature-toc-pinned-clientpref-1"><body>
        <main><p>Wikipedia content should survive the toc word in html tag.</p></main>
        </body></html>
        """
        md = convert(html)
        assert "Wikipedia content" in md


class TestImages:
    def test_data_uri_images_skipped(self):
        html = """
        <html><body><main>
        <p>Text with a spacer image <img src="data:image/gif;base64,R0lGODlhAQABAAAAAC" alt=""> inline.</p>
        <p>More text more text more text more text more text more text.</p>
        </main></body></html>
        """
        md = convert(html)
        assert "data:image" not in md
        assert "base64" not in md


class TestMetadata:
    def test_extract_metadata_basic(self):
        html = """
        <html lang="de"><head>
        <title>Vergleich alt/neu &mdash; Confluence</title>
        <meta name="author" content="Anna Zhuchkova">
        <meta name="description" content="A comparison page">
        <meta property="og:site_name" content="Passar Docs">
        </head><body><main><p>x</p></main></body></html>
        """
        meta = HTMLToMarkdownConverter().extract_metadata(html)
        assert meta["title"] == "Vergleich alt/neu — Confluence"  # entity unescaped
        assert meta["author"] == "Anna Zhuchkova"
        assert meta["language"] == "de"
        assert meta["description"] == "A comparison page"
        assert meta["site_name"] == "Passar Docs"

    def test_extract_metadata_og_title_preferred(self):
        html = """
        <html><head>
        <title>Page - Site Name - Extra</title>
        <meta property="og:title" content="Clean Page Title">
        </head><body></body></html>
        """
        meta = HTMLToMarkdownConverter().extract_metadata(html)
        assert meta["title"] == "Clean Page Title"


class TestContentSelectors:
    def test_first_matching_selector_wins(self):
        """A precise platform container beats a chrome-wrapping landmark."""
        html = """
        <html><body>
        <div id="content">
          <div class="breadcrumbs">Home / Somewhere / Here</div>
          <div class="ak-renderer-document">
            <p>The actual page body lives here and only here really.</p>
          </div>
        </div>
        </body></html>
        """
        md = convert(html)
        assert "actual page body" in md
        assert "breadcrumbs" not in md

    def test_fallback_to_body(self):
        html = "<html><body><p>Just a body paragraph with text and more text here.</p></body></html>"
        md = convert(html)
        assert "Just a body paragraph" in md


def test_content_class_words_not_stripped():
    """Regression: boilerplate word-matching must not eat main-content elements."""
    html = (
        "<html><body><main><h1>API</h1>"
        "<div class='cookie-api-docs'>Cookie API documentation text.</div>"
        "<table class='share-data'><tr><td>share cell</td></tr></table>"
        "<p class='badge-explainer'>Badge explainer.</p>"
        + "Real content. " * 30
        + "</main><aside class='sidebar'>sidebar noise</aside></body></html>"
    )
    converter = HTMLToMarkdownConverter()
    md = converter.convert(html)
    assert "Cookie API documentation" in md
    assert "Badge explainer" in md
    assert "sidebar noise" not in md


def test_retention_ratio_reflects_stripped_content():
    """Retention must be text-vs-text and reflect what was stripped (never > 1)."""
    main_text = "Real content. " * 30
    sidebar_text = "sidebar noise. " * 30
    html = (
        f"<html><body><main><h1>Doc</h1><p>{main_text}</p></main>"
        f"<aside class='sidebar'>{sidebar_text}</aside></body></html>"
    )
    converter = HTMLToMarkdownConverter()
    converter.convert(html)
    assert 0.2 < converter.stats.retention_ratio < 0.7, converter.stats.retention_ratio


def test_content_protected_with_class_selector():
    """Regression for the audit: class-based content selectors (`.markdown-body`)
    must protect their descendants from boilerplate word-matching (find_parent
    by tag name would NOT match a CSS class)."""
    html = (
        "<html><body>"
        "<div class='markdown-body'><div class='cookie-api-docs'>Cookie API docs.</div>"
        + "Real content. " * 30
        + "</div>"
        "<div class='sidebar'>sidebar noise</div>"
        "</body></html>"
    )
    converter = HTMLToMarkdownConverter()
    md = converter.convert(html)
    assert "Cookie API docs" in md
    assert "sidebar noise" not in md


def test_extract_license_from_meta():
    converter = HTMLToMarkdownConverter()
    html = '<html><head><meta name="license" content="CC-BY 4.0"></head><body><main>'
    html += "content " * 40 + "</main></body></html>"
    meta = converter.extract_metadata(html)
    assert meta["license"] == "CC-BY 4.0"


def test_extract_license_from_link_rel():
    converter = HTMLToMarkdownConverter()
    html = (
        '<html><head><link rel="license" '
        'href="https://creativecommons.org/licenses/by/4.0/"></head>'
        "<body><main>" + "content " * 40 + "</main></body></html>"
    )
    meta = converter.extract_metadata(html)
    assert meta["license"] == "https://creativecommons.org/licenses/by/4.0/"


def test_extract_license_not_substring_matched():
    """Regression (reviewer P2): rel values merely CONTAINING 'license' must not match."""
    converter = HTMLToMarkdownConverter()
    html = (
        '<html><head><link rel="licenses" href="https://x"></head>'
        "<body><main>" + "content " * 40 + "</main></body></html>"
    )
    meta = converter.extract_metadata(html)
    assert meta["license"] == ""


def test_heading_content_link_text_preserved():
    """Regression (#56): an in-page content link inside a heading must not be
    stripped (only permalink symbols are)."""
    converter = HTMLToMarkdownConverter()
    html = (
        "<html><body><main><h2>See <a href='#install'>Installation guide</a></h2>"
        "<h3>More<a class='headerlink' href='#more'>&para;</a></h3>"
        + "content " * 40 + "</main></body></html>"
    )
    md = converter.convert(html)
    assert "Installation guide" in md
    assert "&para;" not in md


def test_summary_table_not_dropped():
    """Regression (#57): a legitimate single-row summary table sharing a header
    with a sibling data table must not be deleted."""
    converter = HTMLToMarkdownConverter()
    html = (
        "<html><body><main>"
        "<table><tr><th>Name</th><td>Alice</td></tr></table>"  # summary (has td)
        "<table><tr><th>Name</th><th>Role</th></tr><tr><td>Bob</td><td>Admin</td></tr></table>"
        + "content " * 40 + "</main></body></html>"
    )
    md = converter.convert(html)
    assert "Alice" in md


def test_ol_non_numeric_start_no_crash():
    """Regression (#58): <ol start='abc'> must not crash conversion."""
    converter = HTMLToMarkdownConverter()
    html = "<html><body><main><ol start='abc'><li>one</li><li>two</li></ol>" + "content " * 40 + "</main></body></html>"
    md = converter.convert(html)
    assert "one" in md and "two" in md
