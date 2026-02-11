"""
QMD integration module for knowledge base indexing.

Provides a wrapper around the QMD CLI to add collections, contexts,
and generate embeddings for documentation knowledge bases.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional


class QMDNotFoundError(Exception):
    """Raised when QMD CLI is not found on the system."""
    pass


class QMDCommandError(Exception):
    """Raised when a QMD CLI command fails."""
    pass


class QMDIntegrator:
    """
    Integrates with QMD knowledge base system.
    
    Wraps QMD CLI commands to create collections, add context descriptions,
    and generate vector embeddings for semantic search.
    """
    
    def __init__(self):
        """Initialize the QMD integrator and verify QMD is available."""
        self._verify_qmd_installed()
    
    def _verify_qmd_installed(self) -> None:
        """
        Verify that QMD is installed and available.
        
        Raises:
            QMDNotFoundError: If QMD is not found in PATH.
        """
        if shutil.which("qmd") is None:
            raise QMDNotFoundError(
                "QMD is not installed or not in PATH. "
                "Install it with: bun install -g https://github.com/tobi/qmd"
            )
    
    def _run_command(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """
        Run a QMD command.
        
        Args:
            cmd: Command and arguments as a list.
            check: Whether to raise exception on non-zero exit.
        
        Returns:
            CompletedProcess instance.
        
        Raises:
            QMDCommandError: If command fails and check=True.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            raise QMDCommandError(
                f"QMD command failed: {' '.join(cmd)}\\n"
                f"Exit code: {e.returncode}\\n"
                f"Error: {e.stderr}"
            )
    
    def add_collection(
        self,
        output_dir: Path,
        collection_name: str,
        mask: str = "**/*.md"
    ) -> bool:
        """
        Add a directory as a QMD collection.
        
        Args:
            output_dir: Path to the directory containing markdown files.
            collection_name: Name for the collection.
            mask: Glob pattern for files to include (default: **/*.md).
        
        Returns:
            True if successful.
        
        Raises:
            QMDCommandError: If the command fails.
        """
        cmd = [
            "qmd",
            "collection",
            "add",
            str(output_dir.resolve()),
            "--name",
            collection_name,
            "--mask",
            mask
        ]
        
        result = self._run_command(cmd, check=False)
        
        # QMD returns non-zero if collection already exists, check stderr
        if result.returncode != 0:
            if "already exists" in result.stderr.lower():
                # Collection already exists - this is acceptable
                return True
            else:
                raise QMDCommandError(
                    f"Failed to add collection '{collection_name}'\\n"
                    f"Error: {result.stderr}"
                )
        
        return True
    
    def add_context(
        self,
        collection_name: str,
        description: str
    ) -> bool:
        """
        Add context description to a QMD collection.
        
        Args:
            collection_name: Name of the collection.
            description: Context description for semantic search.
        
        Returns:
            True if successful.
        
        Raises:
            QMDCommandError: If the command fails.
        """
        cmd = [
            "qmd",
            "context",
            "add",
            f"qmd://{collection_name}",
            description
        ]
        
        self._run_command(cmd)
        return True
    
    def embed(self, force: bool = False) -> bool:
        """
        Generate vector embeddings for all indexed documents.
        
        Args:
            force: Whether to force re-embedding of all documents.
        
        Returns:
            True if successful.
        
        Raises:
            QMDCommandError: If the command fails.
        """
        cmd = ["qmd", "embed"]
        if force:
            cmd.append("-f")
        
        self._run_command(cmd)
        return True
    
    def run_pipeline(
        self,
        output_dir: Path,
        collection_name: str,
        context_description: str
    ) -> bool:
        """
        Run the complete QMD integration pipeline.
        
        Executes: add collection → add context → generate embeddings.
        
        Args:
            output_dir: Path to the directory with markdown files.
            collection_name: Name for the collection.
            context_description: Context description for the collection.
        
        Returns:
            True if the entire pipeline succeeds.
        
        Raises:
            QMDCommandError: If any step fails.
        """
        # Step 1: Add collection
        self.add_collection(output_dir, collection_name)
        
        # Step 2: Add context
        self.add_context(collection_name, context_description)
        
        # Step 3: Generate embeddings
        self.embed()
        
        return True
    
    def collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists.
        
        Args:
            collection_name: Name of the collection to check.
        
        Returns:
            True if the collection exists, False otherwise.
        """
        try:
            result = self._run_command(["qmd", "collection", "list"], check=True)
            return collection_name in result.stdout
        except QMDCommandError:
            return False
