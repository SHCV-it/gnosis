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
