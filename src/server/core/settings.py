"""
Settings Loader - Environment-based configuration with Pydantic validation.

Parses env vars CMMS_<MODULE>__<KEY> into per-module Settings objects.
Fails boot on invalid config with field-level error list.
Secrets are never logged.
"""

import os
from typing import Any, Type
from pydantic import BaseModel, Field
from dataclasses import dataclass, field


class SettingsLoadError(Exception):
    """Raised when settings validation fails."""
    def __init__(self, module: str, errors: list[dict]):
        self.module = module
        self.errors = errors
        super().__init__(
            f"Settings validation failed for module '{module}': {errors}"
        )


@dataclass
class ModuleSettingsWrapper:
    """Wrapper holding a module's settings instance and its class."""
    settings_class: Type[BaseModel]
    instance: BaseModel | None = None


@dataclass
class SettingsBundle:
    """
    Container for all module settings.
    
    Access individual module settings via module_settings(name).
    """
    _modules: dict[str, ModuleSettingsWrapper] = field(default_factory=dict)
    
    def register_module(self, name: str, settings_class: Type[BaseModel]) -> None:
        """Register a module's settings class."""
        self._modules[name] = ModuleSettingsWrapper(settings_class=settings_class)
    
    def get_module(self, name: str) -> BaseModel | None:
        """Get a module's validated settings instance."""
        wrapper = self._modules.get(name)
        if wrapper is None:
            return None
        return wrapper.instance
    
    def set_module_instance(self, name: str, instance: BaseModel) -> None:
        """Set a module's validated settings instance."""
        if name not in self._modules:
            raise KeyError(f"Module '{name}' not registered")
        self._modules[name].instance = instance
    
    def list_modules(self) -> list[str]:
        """Return list of all registered module names."""
        return list(self._modules.keys())


class SettingsLoader:
    """
    Load and validate settings from environment variables.
    
    Environment variable format: CMMS_<MODULE>__<KEY>
    Example: CMMS_DB__URL, CMMS_CACHE__URL, CMMS_API__CORS_ORIGINS
    
    Double underscore separates module name from key.
    Keys are converted to uppercase for matching.
    """
    
    def __init__(self):
        self._raw_env: dict[str, str] = {}
        self._module_keys: dict[str, dict[str, str]] = {}
    
    def load_settings(self) -> SettingsBundle:
        """
        Parse env vars and validate each module's pydantic Settings.
        
        Returns:
            SettingsBundle with per-module validated settings
        
        Raises:
            SettingsLoadError: If any module's settings fail validation
        """
        # Read all CMMS_ env vars
        self._raw_env = {
            k: v for k, v in os.environ.items()
            if k.startswith('CMMS_')
        }
        
        # Group by module
        self._module_keys = {}
        for key, value in self._raw_env.items():
            # Strip CMMS_ prefix
            remainder = key[5:]  # Remove 'CMMS_'
            
            # Split on double underscore
            if '__' not in remainder:
                continue
            
            parts = remainder.split('__', 1)
            if len(parts) != 2:
                continue
            
            module_name = parts[0].upper()
            setting_key = parts[1].upper()
            
            if module_name not in self._module_keys:
                self._module_keys[module_name] = {}
            
            self._module_keys[module_name][setting_key] = value
        
        return SettingsBundle()
    
    def parse_module_settings(
        self,
        module_name: str,
        settings_class: Type[BaseModel]
    ) -> BaseModel:
        """
        Parse and validate settings for a single module.
        
        Args:
            module_name: Name of the module (e.g., 'DB', 'CACHE')
            settings_class: Pydantic BaseModel subclass for this module
        
        Returns:
            Validated settings instance
        
        Raises:
            SettingsLoadError: If validation fails
        """
        module_upper = module_name.upper()
        raw_values = self._module_keys.get(module_upper, {})
        
        # Convert keys to lowercase field names
        field_values = {}
        for key, value in raw_values.items():
            # Convert CMMS_DB__URL -> url
            field_name = key.lower()
            field_values[field_name] = value
        
        try:
            instance = settings_class(**field_values)
            return instance
        except Exception as e:
            errors = self._extract_validation_errors(e, settings_class)
            raise SettingsLoadError(module_name, errors)
    
    def _extract_validation_errors(
        self,
        exc: Exception,
        settings_class: Type[BaseModel]
    ) -> list[dict]:
        """Extract field-level errors from Pydantic validation error."""
        from pydantic import ValidationError
        
        if isinstance(exc, ValidationError):
            return [
                {
                    "field": ".".join(str(x) for x in err["loc"]),
                    "error": err["msg"],
                    "type": err["type"],
                }
                for err in exc.errors()
            ]
        
        return [{"field": "_", "error": str(exc), "type": type(exc).__name__}]


# Global settings bundle (lazy-initialized by core)
_settings_bundle: SettingsBundle | None = None


def module_settings(name: str) -> BaseModel | None:
    """
    Get a module's validated settings object.
    
    Args:
        name: Module name (e.g., 'db', 'cache', 'api')
    
    Returns:
        The module's pydantic Settings instance, or None if not registered
    
    Usage in modules:
        class DbSettings(BaseModel):
            url: str
            pool_size: int = 10
        
        # In configure():
        settings = core.module_settings('db')
        self._engine = build_engine(settings.url, settings.pool_size)
    """
    global _settings_bundle
    if _settings_bundle is None:
        return None
    return _settings_bundle.get_module(name.upper())


def register_settings(
    module_name: str,
    settings_class: Type[BaseModel]
) -> None:
    """
    Register a module's settings class during boot.
    
    Called by BootOrchestrator during module discovery.
    """
    global _settings_bundle
    if _settings_bundle is None:
        _settings_bundle = SettingsBundle()
    
    _settings_bundle.register_module(module_name.upper(), settings_class)
