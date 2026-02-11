"""
LLM integration for generating contextual descriptions.

Uses HuggingFace transformers to generate concise descriptions of
documentation collections for QMD knowledge base indexing.
"""

from pathlib import Path
from typing import Optional

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

from gnosis.config.settings import QMDSettings


class LLMContextGenerator:
    """
    Generates contextual descriptions using local LLMs.
    
    Uses HuggingFace transformers with models like Qwen3-0.6B to analyze
    markdown content and generate search-friendly descriptions.
    """
    
    def __init__(self, settings: QMDSettings):
        """
        Initialize the LLM context generator.
        
        Args:
            settings: QMD configuration settings including model name and parameters.
        """
        self.settings = settings
        self.model: Optional[AutoModelForCausalLM] = None
        self.tokenizer: Optional[AutoTokenizer] = None
        self._model_loaded = False
    
    def _load_model(self) -> None:
        """Load the model and tokenizer if not already loaded."""
        if self._model_loaded:
            return
        
        # Map dtype string to torch dtype
        dtype_map = {
            'float32': torch.float32,
            'float16': torch.float16,
            'bfloat16': torch.bfloat16
        }
        dtype = dtype_map.get(self.settings.llm_dtype, torch.float32)
        
        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.settings.llm_model)
        
        # Load model
        self.model = AutoModelForCausalLM.from_pretrained(
            self.settings.llm_model,
            dtype=dtype,
            device_map=self.settings.llm_device
        )
        self.model.eval()
        
        self._model_loaded = True
    
    def generate_context(
        self,
        markdown_files: list[Path],
        collection_name: str,
        url: str
    ) -> str:
        """
        Generate a contextual description for a collection of markdown files.
        
        Args:
            markdown_files: List of markdown file paths to analyze.
            collection_name: Name of the QMD collection.
            url: Original URL of the documentation source.
        
        Returns:
            A concise description suitable for QMD context.
        
        Raises:
            RuntimeError: If model loading or generation fails.
        """
        try:
            self._load_model()
        except Exception as e:
            raise RuntimeError(f"Failed to load LLM model: {e}")
        
        # Aggregate content from markdown files
        aggregated_content = self._aggregate_content(markdown_files)
        
        # Prepare the prompt - just use the content directly
        user_prompt = self.settings.context_prompt_template.format(content=aggregated_content)
        
        # Add /no_think tag for Qwen models to disable thinking mode
        if "qwen" in self.settings.llm_model.lower():
            user_prompt = user_prompt + " /no_think"
        
        # Create messages for chat format
        messages = self._create_messages(user_prompt)
        
        # Generate description
        try:
            description = self._generate(messages)
            return description.strip()
        except Exception as e:
            raise RuntimeError(f"Failed to generate context description: {e}")
    
    def _aggregate_content(self, markdown_files: list[Path]) -> str:
        """
        Aggregate content from multiple markdown files.
        
        Samples the first N files up to a maximum character limit to avoid
        overwhelming the LLM context window.
        
        Args:
            markdown_files: List of markdown file paths.
        
        Returns:
            Aggregated markdown content string.
        """
        aggregated = []
        total_chars = 0
        max_chars = self.settings.sample_content_max_chars
        max_files = self.settings.sample_files_limit
        
        for i, file_path in enumerate(markdown_files[:max_files]):
            if total_chars >= max_chars:
                break
            
            try:
                content = file_path.read_text(encoding='utf-8')
                remaining_chars = max_chars - total_chars
                
                if len(content) > remaining_chars:
                    content = content[:remaining_chars] + "\n[... truncated ...]"
                
                aggregated.append(f"## File: {file_path.name}\n{content}")
                total_chars += len(content)
            except Exception:
                # Skip files that can't be read
                continue
        
        if not aggregated:
            return "No content available."
        
        # If only one file, return its content without the file header
        if len(aggregated) == 1 and len(markdown_files) == 1:
            # Extract content after the "## File: ..." header
            content = aggregated[0]
            if content.startswith("## File:"):
                # Skip the first line (file header)
                content = "\n".join(content.split("\n")[1:])
            return content.strip()
        
        result = "\n\n".join(aggregated)
        
        # Add metadata if we sampled
        if len(markdown_files) > max_files:
            result += f"\n\n[Note: Showing {max_files} of {len(markdown_files)} files]"
        
        return result
    
    def _create_messages(self, user_prompt: str) -> list[dict]:
        """
        Create chat messages in the appropriate format for the model.
        
        Args:
            user_prompt: The user's prompt text.
        
        Returns:
            List of message dictionaries.
        """
        return [{"role": "user", "content": user_prompt}]
    
    def _generate(self, messages: list[dict]) -> str:
        """
        Generate text using the loaded model.
        
        Args:
            messages: Chat messages to process.
        
        Returns:
            Generated text string.
        """
        # Apply chat template and tokenize
        inputs = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt"
        ).to(self.model.device)
        
        # Generate
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.settings.max_tokens,
                temperature=self.settings.temperature,
                top_k=self.settings.top_k,
                top_p=self.settings.top_p,
                do_sample=True
            )
        
        # Decode output (exclude input tokens)
        generated_tokens = outputs[0][inputs['input_ids'].shape[-1]:]
        description = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
        
        # Clean up thinking tags (for models like Qwen3)
        description = self._clean_thinking_tags(description)
        
        return description
    
    def _clean_thinking_tags(self, text: str) -> str:
        """
        Remove thinking process tags and extract final answer.
        
        Some models (like Qwen3) output thinking process wrapped in <think> tags.
        This method removes those tags and extracts the actual response.
        
        Args:
            text: Generated text that may contain thinking tags.
        
        Returns:
            Cleaned text without thinking process.
        """
        import re
        
        # Remove <think>...</think> blocks (including multiline)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = text.strip()
        
        return text
    
    def cleanup(self) -> None:
        """Clean up model resources."""
        if self.model is not None:
            del self.model
            self.model = None
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        self._model_loaded = False
        
        # Clear CUDA cache if available
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
