"""
Service Registry - Typed service discovery.

This is the ONLY cross-module call mechanism.
Modules register their ports here and other modules retrieve them by name + interface type.
"""

from typing import Any, TypeVar


class ServiceNotRegisteredError(Exception):
    """Raised when a service is not found in the registry."""
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Service '{name}' is not registered")


class InterfaceMismatchError(Exception):
    """Raised when a service's actual type doesn't match the requested interface."""
    def __init__(self, name: str, expected: type, actual: type):
        self.name = name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Service '{name}' has interface {actual.__name__}, "
            f"expected {expected.__name__}"
        )


class DuplicateServiceError(Exception):
    """Raised when trying to register a service that already exists."""
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Service '{name}' is already registered")


class ServiceRegistry:
    """
    Typed service registry for cross-module communication.
    
    Services are registered with a name and interface type.
    Retrieval requires both name and expected interface type for type safety.
    
    Example:
        # In DB module:
        core.register_service("db", db_port, DatabasePort)
        
        # In AUTH module:
        db = core.get_service("db", DatabasePort)
    """
    
    def __init__(self):
        # Map of name -> (instance, interface_type)
        self._services: dict[str, tuple[Any, type]] = {}
    
    def register_service(self, name: str, port: Any, interface: type) -> None:
        """
        Register a typed service port.
        
        Args:
            name: Service name (e.g., 'db', 'cache', 'storage')
            port: The implementation instance
            interface: Protocol/type to validate against
        
        Raises:
            DuplicateServiceError: If name is already registered
        """
        if name in self._services:
            raise DuplicateServiceError(name)
        
        self._services[name] = (port, interface)
    
    def get_service(self, name: str, interface: type) -> Any:
        """
        Retrieve a service by name and verify its interface.
        
        Args:
            name: Service name
            interface: Expected Protocol/type
        
        Returns:
            The registered port instance
        
        Raises:
            ServiceNotRegisteredError: If name is not found
            InterfaceMismatchError: If actual type doesn't match expected interface
        """
        if name not in self._services:
            raise ServiceNotRegisteredError(name)
        
        instance, registered_interface = self._services[name]
        
        # Check if the registered interface matches what we expect
        # We use isinstance check against the interface (Protocol)
        if not isinstance(instance, interface):
            # Also allow if it's a subclass or implements the protocol
            if not issubclass(type(instance), interface):
                raise InterfaceMismatchError(name, interface, registered_interface)
        
        return instance
    
    def has_service(self, name: str) -> bool:
        """Check if a service is registered by name."""
        return name in self._services
    
    def list_services(self) -> list[str]:
        """Return list of all registered service names."""
        return list(self._services.keys())
    
    def clear(self) -> None:
        """Clear all registered services. Used for testing."""
        self._services.clear()


# Global registry instance (lazy-initialized by core)
_registry_instance: ServiceRegistry | None = None


def get_registry() -> ServiceRegistry:
    """Get the global registry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ServiceRegistry()
    return _registry_instance
