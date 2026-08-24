"""
Feature Flags - Environment-based feature toggles.

Reads CMMS_FEATURE_<FLAG> environment variables.
Default is False if not set.

Usage:
    if core.feature_enabled("MCP_SERVER"):
        # Enable MCP server functionality
"""

import os


def feature_enabled(flag: str) -> bool:
    """
    Check if a feature flag is enabled.
    
    Reads from environment variable CMMS_FEATURE_<FLAG>.
    Returns False if not set or set to any falsy value.
    
    Truthy values (case-insensitive):
    - "1", "true", "yes", "on", "enabled"
    
    Args:
        flag: Flag name (e.g., "MCP_SERVER", "AI_CHECKLISTS")
    
    Returns:
        bool: True if feature is enabled
    
    Example:
        # Set env: CMMS_FEATURE_MCP_SERVER=1
        if core.feature_enabled("MCP_SERVER"):
            enable_mcp()
        
        # Default false if not set
        if core.feature_enabled("EXPERIMENTAL_FEATURE"):
            # Won't run unless explicitly enabled
    """
    env_key = f"CMMS_FEATURE_{flag.upper()}"
    value = os.environ.get(env_key, "").lower().strip()
    
    truthy_values = {"1", "true", "yes", "on", "enabled"}
    return value in truthy_values


def get_all_flags() -> dict[str, bool]:
    """
    Get all feature flags and their current state.
    
    Returns:
        dict mapping flag names to boolean values
    
    Example:
        flags = get_all_flags()
        # {"MCP_SERVER": True, "AI_CHECKLISTS": False, ...}
    """
    prefix = "CMMS_FEATURE_"
    flags = {}
    
    for key, value in os.environ.items():
        if key.startswith(prefix):
            flag_name = key[len(prefix):].upper()
            flags[flag_name] = value.lower().strip() in {"1", "true", "yes", "on", "enabled"}
    
    return flags
