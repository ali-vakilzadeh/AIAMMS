"""
Dependency Graph Validator - Cycle detection and topological sorting.

Validates that all declared dependencies exist and the graph is acyclic.
Uses Kahn's algorithm for topological sort with alphabetical tie-break.
"""

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .module_base import ModuleMeta


class DependencyCycleError(Exception):
    """Raised when a dependency cycle is detected."""
    def __init__(self, cycle_path: list[str]):
        self.cycle_path = cycle_path
        cycle_str = " -> ".join(cycle_path)
        super().__init__(f"Dependency cycle detected: {cycle_str}")


class UnknownDependencyError(Exception):
    """Raised when a module depends on an unknown module."""
    def __init__(self, module: str, dependency: str):
        self.module = module
        self.dependency = dependency
        super().__init__(
            f"Module '{module}' depends on unknown module '{dependency}'"
        )


class DependencyGraphValidator:
    """
    Validate module dependency graphs.
    
    Checks:
    1. All declared dependencies exist (no unknown modules)
    2. Graph is acyclic (no circular dependencies)
    """
    
    def __init__(self):
        self._modules_by_name: dict[str, "ModuleMeta"] = {}
    
    def validate(self, modules: list["ModuleMeta"]) -> None:
        """
        Validate a list of module metadata.
        
        Args:
            modules: List of ModuleMeta from discover_modules()
        
        Raises:
            UnknownDependencyError: If a dependency references unknown module
            DependencyCycleError: If a cycle is detected
        """
        # Build index
        self._modules_by_name = {m.name: m for m in modules}
        
        # Check for unknown dependencies
        for module in modules:
            for dep in module.dependencies:
                if dep not in self._modules_by_name:
                    raise UnknownDependencyError(module.name, dep)
            
            # Optional dependencies don't need to exist
            # They're just preferences if available
        
        # Check for cycles using DFS
        self._detect_cycles(modules)
    
    def _detect_cycles(self, modules: list["ModuleMeta"]) -> None:
        """
        Detect cycles using DFS with coloring.
        
        Colors:
        - WHITE (0): Not visited
        - GRAY (1): Currently in recursion stack
        - BLACK (2): Fully processed
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {m.name: WHITE for m in modules}
        parent = {m.name: None for m in modules}
        
        def dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            
            module = self._modules_by_name[node]
            for dep in module.dependencies:
                if dep not in color:
                    # Already checked by validate(), but safety check
                    continue
                
                if color[dep] == GRAY:
                    # Found cycle - reconstruct path
                    cycle_start = path.index(dep)
                    cycle_path = path[cycle_start:] + [dep]
                    raise DependencyCycleError(cycle_path)
                
                if color[dep] == WHITE:
                    parent[dep] = node
                    dfs(dep, path + [dep])
            
            color[node] = BLACK
        
        # Process in alphabetical order for determinism
        sorted_names = sorted(self._modules_by_name.keys())
        
        for name in sorted_names:
            if color[name] == WHITE:
                dfs(name, [name])


def validate_dependency_graph(modules: list["ModuleMeta"]) -> None:
    """
    Validate a list of module metadata.
    
    Args:
        modules: List of ModuleMeta from discover_modules()
    
    Raises:
        UnknownDependencyError: If a dependency references unknown module
        DependencyCycleError: If a cycle is detected
    """
    validator = DependencyGraphValidator()
    validator.validate(modules)


def topological_sort(modules: list["ModuleMeta"]) -> list[str]:
    """
    Sort modules in dependency order using Kahn's algorithm.
    
    Uses alphabetical tie-break for deterministic ordering.
    
    Args:
        modules: List of validated ModuleMeta
    
    Returns:
        List of module names in start order (dependencies first)
    
    Example:
        If A depends on nothing, B depends on A, C depends on A,B
        Result: ['A', 'B', 'C']
    """
    # Build adjacency list and in-degree count
    # Edge: dependency -> dependent (dep must start before module)
    graph: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {m.name: 0 for m in modules}
    
    modules_by_name = {m.name: m for m in modules}
    
    for module in modules:
        for dep in module.dependencies:
            if dep in modules_by_name:
                graph[dep].append(module.name)
                in_degree[module.name] += 1
    
    # Initialize queue with nodes having no dependencies
    # Use sorted list for alphabetical tie-break
    queue = deque(sorted([n for n, d in in_degree.items() if d == 0]))
    result = []
    
    while queue:
        # Pop alphabetically first node with no remaining deps
        node = queue.popleft()
        result.append(node)
        
        # Reduce in-degree for all dependents
        dependents = sorted(graph[node])  # Alphabetical order
        for dependent in dependents:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                # Insert maintaining sorted order
                # Find insertion point
                inserted = False
                for i, item in enumerate(queue):
                    if dependent < item:
                        queue.insert(i, dependent)
                        inserted = True
                        break
                if not inserted:
                    queue.append(dependent)
    
    # If result doesn't contain all nodes, there's a cycle
    # (Should have been caught by validator already)
    if len(result) != len(modules):
        missing = set(m.name for m in modules) - set(result)
        raise DependencyCycleError(list(missing))
    
    return result
