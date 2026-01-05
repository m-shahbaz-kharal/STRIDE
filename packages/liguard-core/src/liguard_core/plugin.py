"""
Plugin discovery for LiGuard-Web.

Provides utilities to discover and load plugins via entry points.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    from importlib.metadata import entry_points
except ImportError:
    # Python < 3.10 fallback
    from importlib_metadata import entry_points


logger = logging.getLogger("liguard_core.plugin")

# Entry point group for LiGuard plugins
PLUGIN_ENTRY_POINT = "liguard.plugins"


@dataclass
class PluginInfo:
    """Information about a discovered plugin."""
    
    name: str
    module: str
    register_func: Optional[Callable[[], None]] = None
    metadata: Dict[str, Any] = None
    loaded: bool = False
    error: Optional[str] = None


def discover_plugins() -> List[PluginInfo]:
    """Discover all installed LiGuard plugins.
    
    Scans for packages that declare the 'liguard.plugins' entry point.
    
    Returns:
        List of PluginInfo objects for discovered plugins.
    """
    plugins = []
    
    try:
        # Python 3.12+ and 3.10-3.11 have different APIs
        eps = entry_points()
        if hasattr(eps, 'select'):
            # Python 3.10+
            liguard_eps = eps.select(group=PLUGIN_ENTRY_POINT)
        elif hasattr(eps, 'get'):
            # Older API
            liguard_eps = eps.get(PLUGIN_ENTRY_POINT, [])
        else:
            # Dict-like access (Python 3.9)
            liguard_eps = eps.get(PLUGIN_ENTRY_POINT, [])
    except Exception as e:
        logger.warning(f"Error discovering plugins: {e}")
        return plugins
    
    for ep in liguard_eps:
        plugin = PluginInfo(
            name=ep.name,
            module=ep.value if hasattr(ep, 'value') else str(ep),
        )
        plugins.append(plugin)
        logger.debug(f"Discovered plugin: {plugin.name} ({plugin.module})")
    
    return plugins


def load_plugin(plugin: PluginInfo) -> bool:
    """Load a discovered plugin.
    
    Args:
        plugin: PluginInfo from discover_plugins()
        
    Returns:
        True if plugin loaded successfully, False otherwise.
    """
    if plugin.loaded:
        return True
    
    try:
        eps = entry_points()
        if hasattr(eps, 'select'):
            liguard_eps = list(eps.select(group=PLUGIN_ENTRY_POINT))
        else:
            liguard_eps = eps.get(PLUGIN_ENTRY_POINT, [])
        
        for ep in liguard_eps:
            if ep.name == plugin.name:
                # Load the entry point
                register_func = ep.load()
                plugin.register_func = register_func
                
                # Try to get metadata
                if hasattr(register_func, '__module__'):
                    try:
                        import importlib
                        mod = importlib.import_module(register_func.__module__.rsplit('.', 1)[0])
                        if hasattr(mod, 'PLUGIN_INFO'):
                            plugin.metadata = mod.PLUGIN_INFO
                    except Exception:
                        pass
                
                # Call the register function
                if callable(register_func):
                    register_func()
                
                plugin.loaded = True
                logger.info(f"Loaded plugin: {plugin.name}")
                return True
        
        plugin.error = "Entry point not found"
        return False
        
    except Exception as e:
        plugin.error = str(e)
        logger.error(f"Error loading plugin {plugin.name}: {e}")
        return False


def load_all_plugins() -> List[PluginInfo]:
    """Discover and load all available plugins.
    
    Returns:
        List of PluginInfo objects with load status.
    """
    plugins = discover_plugins()
    
    for plugin in plugins:
        load_plugin(plugin)
    
    loaded_count = sum(1 for p in plugins if p.loaded)
    logger.info(f"Loaded {loaded_count}/{len(plugins)} plugins")
    
    return plugins
