import ast

_BLOCKED_NAMES = {"eval", "exec", "compile", "open", "globals", "locals", "vars", "getattr", "setattr", "delattr", "input", "breakpoint"}


def validate_user_code(code: str) -> ast.AST:
    """Parse user code and reject imports, dunder/private access and dangerous builtins."""
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError("Imports and global/nonlocal statements are not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Access to private or dunder attributes is not allowed")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in _BLOCKED_NAMES):
            raise ValueError(f"Use of '{node.id}' is not allowed")
    return tree
