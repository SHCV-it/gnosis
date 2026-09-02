"""
QMD integration module for knowledge base indexing.

Provides a wrapper around the QMD CLI to add collections, contexts,
and generate embeddings for documentation knowledge bases.
"""

import re
import shutil
import subprocess
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
    
    def __init__(self, qmd_binary: Optional[str] = None):
        """Initialize the QMD integrator and verify QMD is available."""
        self.qmd_binary = qmd_binary or shutil.which("qmd")
        self._verify_qmd_installed()
    
    def _verify_qmd_installed(self) -> None:
        """
        Verify that QMD is installed and available.
        
        Raises:
            QMDNotFoundError: If QMD is not found in PATH.
        """
        if self.qmd_binary is None:
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
                check=check,
                timeout=120,
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
            self.qmd_binary,
            "collection",
            "add",
            str(output_dir.resolve()),
            "--name",
            collection_name,
            "--mask",
            mask
        ]
        
        result = self._run_command(cmd, check=False)
        
        if result.returncode != 0:
            output = result.stdout + result.stderr
            
            if "already exists" in output.lower():
                # Remove the existing collection and re-add.
                # Two cases: path conflict (different name owns the path)
                # or name conflict (same name already exists).
                existing_name = self._parse_existing_collection_name(output) or collection_name
                self.remove_collection(existing_name)
                # Retry the add after removal
                retry = self._run_command(cmd, check=False)
                if retry.returncode != 0:
                    raise QMDCommandError(
                        f"Failed to add collection '{collection_name}' after "
                        f"removing '{existing_name}'\n"
                        f"Error: {retry.stdout + retry.stderr}"
                    )
                return True
            
            raise QMDCommandError(
                f"Failed to add collection '{collection_name}'\n"
                f"Error: {output}"
            )
        
        return True
    
    def remove_collection(self, collection_name: str) -> bool:
        """
        Remove a QMD collection.
        
        Args:
            collection_name: Name of the collection to remove.
        
        Returns:
            True if successful.
        
        Raises:
            QMDCommandError: If the command fails.
        """
        self._run_command([self.qmd_binary, "collection", "remove", collection_name])
        return True
    
    @staticmethod
    def _parse_existing_collection_name(output: str) -> Optional[str]:
        """
        Parse the existing collection name from QMD 'already exists' output.
        
        Args:
            output: Combined stdout+stderr from the qmd command.
        
        Returns:
            The existing collection name, or None if not found.
        """
        match = re.search(r'Name:\s+(\S+)', output)
        return match.group(1) if match else None
    
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
            self.qmd_binary,
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
        cmd = [self.qmd_binary, "embed"]
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
            result = self._run_command([self.qmd_binary, "collection", "list"], check=True)
            return collection_name in result.stdout
        except QMDCommandError:
            return False
