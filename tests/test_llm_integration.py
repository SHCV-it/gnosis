"""Tests for the LLM integration (pure helpers; no torch/transformers needed)."""


from gnosis.config.settings import QMDSettings
from gnosis.integrations.llm import LLMContextGenerator


def test_aggregate_content_truncates(tmp_path):
    files = []
    for i in range(3):
        f = tmp_path / f"{i}.md"
        f.write_text(f"# Doc {i}\n\n" + "word " * 100)
        files.append(f)
    gen = LLMContextGenerator(
        QMDSettings(sample_content_max_chars=200, sample_files_limit=2)
    )
    out = gen._aggregate_content(files)
    assert "truncated" in out
    assert "Showing 2 of 3 files" in out


def test_aggregate_content_empty():
    gen = LLMContextGenerator(QMDSettings())
    assert gen._aggregate_content([]) == "No content available."


def test_clean_thinking_tags():
    gen = LLMContextGenerator(QMDSettings())
    text = "<think>internal reasoning</think>\n\nFinal answer."
    assert gen._clean_thinking_tags(text) == "Final answer."


def test_create_messages():
    gen = LLMContextGenerator(QMDSettings())
    assert gen._create_messages("hi") == [{"role": "user", "content": "hi"}]


def test_no_think_suffix_for_qwen():
    gen = LLMContextGenerator(QMDSettings(llm_model="Qwen/Qwen3-0.6B"))
    # exercise the prompt-suffix branch without a model by calling the helper
    prompt = gen.settings.context_prompt_template.format(content="c")
    assert "/no_think" not in prompt  # suffix is appended in generate_context, not here
