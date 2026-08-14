"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.graph

Purpose:
    Graph algorithms and data structures for the planning subsystem.

Planning relies on graphs for task dependencies, execution order,
critical path analysis, and cycle detection. This module is pure
algorithmic infrastructure with no planning logic.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Generic, Iterable, Iterator, TypeVar

T = TypeVar("T")

# ==============================================================================
# GRAPH STRUCTURE
# ==============================================================================


class DiGraph(Generic[T]):
    """
    Directed graph with adjacency representation.

    Nodes are stored as unique keys; edges are directed
    ``(source, target)`` pairs.
    """

    def __init__(
        self,
        *,
        weighted: bool = False,
    ) -> None:
        self._weighted = weighted
        self._nodes: set[T] = set()
        self._successors: dict[T, set[T]] = {}
        self._predecessors: dict[T, set[T]] = {}
        self._weights: dict[tuple[T, T], float] = {}

    # ------------------------------------------------------------------
    # Node Operations
    # ------------------------------------------------------------------

    def add_node(self, node: T) -> None:
        """Add a node if not already present."""
        if node not in self._nodes:
            self._nodes.add(node)
            self._successors[node] = set()
            self._predecessors[node] = set()

    def add_nodes(self, nodes: Iterable[T]) -> None:
        """Add multiple nodes."""
        for node in nodes:
            self.add_node(node)

    def remove_node(self, node: T) -> None:
        """Remove a node and all incident edges."""
        if node not in self._nodes:
            return

        for successor in self._successors[node]:
            self._predecessors[successor].discard(node)
            self._weights.pop((node, successor), None)

        for predecessor in self._predecessors[node]:
            self._successors[predecessor].discard(node)
            self._weights.pop((predecessor, node), None)

        self._nodes.remove(node)
        self._successors.pop(node, None)
        self._predecessors.pop(node, None)

    # ------------------------------------------------------------------
    # Edge Operations
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source: T,
        target: T,
        *,
        weight: float = 1.0,
    ) -> None:
        """Add a directed edge from source to target."""
        self.add_node(source)
        self.add_node(target)

        self._successors[source].add(target)
        self._predecessors[target].add(source)

        if self._weighted:
            self._weights[(source, target)] = weight

    def remove_edge(self, source: T, target: T) -> None:
        """Remove a directed edge."""
        self._successors.get(source, set()).discard(target)
        self._predecessors.get(target, set()).discard(source)
        self._weights.pop((source, target), None)

    def has_edge(self, source: T, target: T) -> bool:
        """Whether an edge exists."""
        return target in self._successors.get(source, set())

    def weight_of(self, source: T, target: T) -> float:
        """Return the weight of an edge (default 1.0)."""
        if self._weighted:
            return self._weights.get((source, target), 1.0)
        return 1.0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def nodes(self) -> list[T]:
        """List of node keys."""
        return list(self._nodes)

    @property
    def node_count(self) -> int:
        """Number of nodes."""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """Number of edges."""
        return sum(len(edges) for edges in self._successors.values())

    def successors(self, node: T) -> list[T]:
        """Direct successors of a node."""
        return sorted(self._successors.get(node, set()))

    def predecessors(self, node: T) -> list[T]:
        """Direct predecessors of a node."""
        return sorted(self._predecessors.get(node, set()))

    def edges(self) -> Iterator[tuple[T, T]]:
        """Iterate over all directed edges."""
        for source, targets in self._successors.items():
            for target in targets:
                yield source, target

    def has_node(self, node: T) -> bool:
        """Whether a node exists."""
        return node in self._nodes

    def out_degree(self, node: T) -> int:
        """Number of outgoing edges."""
        return len(self._successors.get(node, set()))

    def in_degree(self, node: T) -> int:
        """Number of incoming edges."""
        return len(self._predecessors.get(node, set()))

    # ------------------------------------------------------------------
    # Copy Operations
    # ------------------------------------------------------------------

    def clone(self) -> "DiGraph[T]":
        """Return a deep structural copy of the graph."""
        copy_graph = DiGraph[T](weighted=self._weighted)
        copy_graph.add_nodes(self.nodes)

        for source, target in self.edges():
            copy_graph.add_edge(
                source,
                target,
                weight=self.weight_of(source, target),
            )

        return copy_graph

    def __len__(self) -> int:
        return self.node_count

    def __contains__(self, node: T) -> bool:
        return self.has_node(node)


# ==============================================================================
# CYCLE DETECTION
# ==============================================================================


def has_cycle(graph: DiGraph[Any]) -> bool:
    """
    Detect whether a directed graph contains a cycle.

    Uses an iterative DFS with three-color marking.
    """

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[Any, int] = {node: WHITE for node in graph.nodes}

    for start in graph.nodes:
        if color[start] != WHITE:
            continue

        stack: list[tuple[Any, Iterator[Any]]] = [
            (start, iter(graph.successors(start)))
        ]
        color[start] = GRAY

        while stack:
            node, successors = stack[-1]

            try:
                successor = next(successors)
            except StopIteration:
                color[node] = BLACK
                stack.pop()
                continue

            if color[successor] == GRAY:
                return True

            if color[successor] == WHITE:
                color[successor] = GRAY
                stack.append(
                    (successor, iter(graph.successors(successor)))
                )

    return False


def find_cycles(graph: DiGraph[Any]) -> list[list[Any]]:
    """
    Return a list of simple cycles found in the graph.
    """

    result: list[list[Any]] = []
    visited: set[Any] = set()

    def dfs(node: Any, path: list[Any]) -> None:
        if node in path:
            index = path.index(node)
            cycle = path[index:] + [node]
            if len(cycle) > 2:
                result.append(cycle)
            return

        if node in visited:
            return

        visited.add(node)

        for successor in graph.successors(node):
            dfs(successor, path + [node])

    for node in graph.nodes:
        dfs(node, [])

    return result


def is_dag(graph: DiGraph[Any]) -> bool:
    """Whether the graph is a valid directed acyclic graph."""
    return not has_cycle(graph)


# ==============================================================================
# TOPOLOGICAL SORT
# ==============================================================================


def topological_sort(
    graph: DiGraph[Any],
    *,
    reverse: bool = False,
) -> list[Any]:
    """
    Return nodes in topological order (Kahn's algorithm).

    Raises
    ------
    ValueError
        When the graph contains a cycle.
    """

    work = graph.clone()
    in_degree = {
        node: work.in_degree(node)
        for node in work.nodes
    }

    queue = deque(
        node
        for node, degree in in_degree.items()
        if degree == 0
    )

    order: list[Any] = []

    while queue:
        node = queue.popleft()
        order.append(node)

        for successor in work.successors(node):
            in_degree[successor] -= 1

            if in_degree[successor] == 0:
                queue.append(successor)

    if len(order) != work.node_count:
        raise ValueError(
            "graph contains a cycle; topological sort is impossible"
        )

    if reverse:
        return list(reversed(order))

    return order


# ==============================================================================
# TRAVERSALS
# ==============================================================================


def bfs(
    graph: DiGraph[Any],
    start: Any,
) -> list[Any]:
    """Return nodes reachable from start in breadth-first order."""
    visited: set[Any] = set()
    queue = deque([start])
    visited.add(start)

    order: list[Any] = []

    while queue:
        node = queue.popleft()
        order.append(node)

        for successor in graph.successors(node):
            if successor not in visited:
                visited.add(successor)
                queue.append(successor)

    return order


def dfs(
    graph: DiGraph[Any],
    start: Any,
) -> list[Any]:
    """Return nodes reachable from start in depth-first order."""
    visited: set[Any] = set()
    stack = [start]
    order: list[Any] = []

    while stack:
        node = stack.pop()

        if node in visited:
            continue

        visited.add(node)
        order.append(node)

        stack.extend(
            reversed(graph.successors(node))
        )

    return order


# ==============================================================================
# PATH ALGORITHMS
# ==============================================================================


def shortest_path(
    graph: DiGraph[Any],
    start: Any,
    end: Any,
) -> list[Any] | None:
    """
    Return the shortest unweighted path from start to end.

    Returns None when no path exists. Uses BFS.
    """

    if start == end:
        return [start]

    visited: set[Any] = {start}
    predecessors: dict[Any, Any] = {}
    queue = deque([start])

    while queue:
        node = queue.popleft()

        for successor in graph.successors(node):
            if successor in visited:
                continue

            visited.add(successor)
            predecessors[successor] = node

            if successor == end:
                return _reconstruct_path(predecessors, start, end)

            queue.append(successor)

    return None


def shortest_path_weighted(
    graph: DiGraph[Any],
    start: Any,
    end: Any,
) -> tuple[list[Any] | None, float]:
    """
    Return the shortest weighted path (Dijkstra) and its total weight.

    Returns (None, inf) when no path exists.
    """

    import heapq

    distances: dict[Any, float] = {node: float("inf") for node in graph.nodes}
    distances[start] = 0.0
    predecessors: dict[Any, Any] = {}
    heap: list[tuple[float, Any]] = [(0.0, start)]

    while heap:
        distance, node = heapq.heappop(heap)

        if distance > distances[node]:
            continue

        if node == end:
            return _reconstruct_path(predecessors, start, end), distance

        for successor in graph.successors(node):
            candidate = distance + graph.weight_of(node, successor)

            if candidate < distances[successor]:
                distances[successor] = candidate
                predecessors[successor] = node
                heapq.heappush(heap, (candidate, successor))

    return None, float("inf")


def _reconstruct_path(
    predecessors: dict[Any, Any],
    start: Any,
    end: Any,
) -> list[Any]:
    path = [end]
    current = end

    while current != start:
        current = predecessors[current]
        path.append(current)

    return list(reversed(path))


# ==============================================================================
# CRITICAL PATH
# ==============================================================================


def critical_path(
    graph: DiGraph[Any],
) -> tuple[list[Any], float]:
    """
    Return the critical path and its total weight.

    The critical path is the longest weighted path through the DAG.

    Raises
    ------
    ValueError
        When the graph contains a cycle.
    """

    if not is_dag(graph):
        raise ValueError("critical path requires a DAG")

    order = topological_sort(graph, reverse=False)

    earliest: dict[Any, float] = {node: 0.0 for node in graph.nodes}

    for node in order:
        for successor in graph.successors(node):
            candidate = earliest[node] + graph.weight_of(node, successor)

            if candidate > earliest[successor]:
                earliest[successor] = candidate

    end_node = max(
        graph.nodes,
        key=lambda node: earliest[node],
        default=None,
    )

    if end_node is None:
        return [], 0.0

    # Reconstruct the critical path backwards.
    path = [end_node]
    current = end_node

    while earliest[current] > 0.0:
        candidates = [
            predecessor
            for predecessor in graph.predecessors(current)
            if earliest[current]
            == earliest[predecessor] + graph.weight_of(predecessor, current)
        ]

        if not candidates:
            break

        current = candidates[0]
        path.append(current)

    return list(reversed(path)), earliest[end_node]


# ==============================================================================
# GRAPH MERGE / SPLIT
# ==============================================================================


def merge_graphs(
    *graphs: DiGraph[Any],
    weighted: bool = False,
) -> DiGraph[Any]:
    """Merge multiple graphs into one."""
    merged = DiGraph[Any](weighted=weighted)

    for graph in graphs:
        merged.add_nodes(graph.nodes)

        for source, target in graph.edges():
            merged.add_edge(
                source,
                target,
                weight=graph.weight_of(source, target),
            )

    return merged


def split_subgraph(
    graph: DiGraph[Any],
    node_subset: Iterable[Any],
) -> DiGraph[Any]:
    """Extract the subgraph induced by a subset of nodes."""
    subset = set(node_subset)
    subgraph = DiGraph[Any](weighted=graph._weighted)

    subgraph.add_nodes(
        node for node in graph.nodes if node in subset
    )

    for source, target in graph.edges():
        if source in subset and target in subset:
            subgraph.add_edge(
                source,
                target,
                weight=graph.weight_of(source, target),
            )

    return subgraph


def connected_components(
    graph: DiGraph[Any],
) -> list[list[Any]]:
    """
    Return weakly connected components as lists of nodes.

    Ignores edge direction.
    """

    undirected: dict[Any, set[Any]] = {node: set() for node in graph.nodes}

    for source, target in graph.edges():
        undirected[source].add(target)
        undirected[target].add(source)

    visited: set[Any] = set()
    components: list[list[Any]] = []

    for start in graph.nodes:
        if start in visited:
            continue

        component: list[Any] = []
        stack = [start]
        visited.add(start)

        while stack:
            node = stack.pop()
            component.append(node)

            for neighbor in undirected[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)

        components.append(component)

    return components


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "DiGraph",
    "has_cycle",
    "find_cycles",
    "is_dag",
    "topological_sort",
    "bfs",
    "dfs",
    "shortest_path",
    "shortest_path_weighted",
    "critical_path",
    "merge_graphs",
    "split_subgraph",
    "connected_components",
]
