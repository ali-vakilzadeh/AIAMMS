"""
Module Discovery - Scan package for ModuleBase subclasses.

Discovers all modules in a package by importing subpackages and
collecting classes that subclass ModuleBase.
"""

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .module_base import ModuleBase, ModuleMeta


class DuplicateModuleError(Exception):
    """Raised when two modules have the same name."""
    def __init__(self, name: str, path1: str, path2: str):
        self.name = name
        self.path1 = path1
        self.path2 = path2
        super().__init__(
            f"Duplicate module name '{name}' found at {path1} and {path2}"
        )


def discover_modules(package_root: str = "modules") -> list["ModuleMeta"]:
    """
    Import every subpackage, collect classes subclassing ModuleBase,
    return their metadata. Duplicate module names raise.
    
    Args:
        package_root: Python package path to scan (default 'modules')
    
    Returns:
        list[ModuleMeta]: Metadata for each discovered module
    
    Raises:
        DuplicateModuleError: If two modules declare the same name
    
    Example:
        modules = discover_modules('modules')
        # [ModuleMeta(name='db', version='1.0.0', dependencies=[]), ...]
    """
    from .module_base import ModuleBase, ModuleMeta
    
    # Convert package path to module path
    # e.g., 'modules' -> 'src.server.modules' or just 'modules'
    base_package = _resolve_package(package_root)
    
    discovered: dict[str, tuple["ModuleMeta", str]] = {}
    
    # Iterate over all subpackages
    try:
        package = importlib.import_module(base_package)
    except ImportError as e:
        # Package doesn't exist yet - return empty list
        # This is normal during early boot before modules are created
        return []
    
    # Get the package's __path__ for iteration
    if not hasattr(package, '__path__'):
        return []
    
    for importer, module_name, is_pkg in pkgutil.iter_modules(
        package.__path__,
        prefix=f"{base_package}."
    ):
        if not is_pkg:
            # Skip non-package modules
            continue
        
        try:
            # Import the module
            mod = importlib.import_module(module_name)
            
            # Find ModuleBase subclasses in this module
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                
                # Check if it's a class that subclasses ModuleBase
                if (
                    isinstance(attr, type)
                    and issubclass(attr, ModuleBase)
                    and attr is not ModuleBase
                ):
                    # Get metadata from the class
                    meta = attr.get_meta()
                    
                    # Check for duplicates
                    if meta.name in discovered:
                        _, existing_path = discovered[meta.name]
                        raise DuplicateModuleError(
                            meta.name,
                            existing_path,
                            module_name
                        )
                    
                    discovered[meta.name] = (meta, module_name)
        
        except Exception as e:
            # Log but don't fail - module may have syntax errors during development
            import logging
            logger = logging.getLogger("core.discovery")
            logger.warning(
                f"Failed to import module {module_name}: {e}",
                exc_info=True
            )
    
    return [meta for meta, _ in discovered.values()]


def _resolve_package(package_root: str) -> str:
    """
    Resolve package root to full module path.
    
    Handles both absolute and relative package paths.
    """
    # Try direct import first
    try:
        importlib.import_module(package_root)
        return package_root
    except ImportError:
        pass
    
    # Try as subpackage of src.server
    full_path = f"src.server.{package_root}"
    try:
        importlib.import_module(full_path)
        return full_path
    except ImportError:
        pass
    
    # Return as-is and let caller handle failure
    return package_root
