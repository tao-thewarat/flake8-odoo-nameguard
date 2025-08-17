import ast
from typing import Generator, Tuple, Optional, Set


FIELD_RULES = {
    "Boolean": ("ODN100", "Boolean field '{name}' should start with 'is_'"),
    "Date": ("ODN101", "Date field '{name}' should end with '_date'"),
    "Many2one": ("ODN102", "Many2one field '{name}' should end with '_id'"),
    "Many2many": ("ODN103", "Many2many field '{name}' should end with '_ids'"),
}

FUNC_RULES = {
    "compute": ("ODN110", "Field '{name}' compute method should be named '_compute_{name}'"),
    "inverse": ("ODN111", "Field '{name}' inverse method should be named '_inverse_{name}'"),
    "search":  ("ODN112", "Field '{name}' search method should be named '_search_{name}'"),
}

DECORATOR_PREFIX_RULES = {
    "onchange": ("ODN113", "_onchange_", "Method '{func}' with @api.onchange should start with '_onchange_'"),
    "constrains": ("ODN114", "_check_", "Method '{func}' with @api.constrains should start with '_check_'"),
}

SUPER_RULE = ("ODN120",
              "Method '{func}' calls super() but does not return its result; "
              "use 'return super(...).<method>(...)' or return the assigned variable.")


def _is_fields_call(node: ast.AST) -> Tuple[Optional[str], Optional[ast.Call]]:
    """Return (field_type, call_node) if node is fields.<Type>(...), else (None, None)."""
    if not isinstance(node, ast.Call):
        return None, None
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "fields":
        return func.attr, node
    return None, None


def _literal_str(node: ast.AST) -> Optional[str]:
    """Extract string literal value if node is a literal string, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None
        return "".join(parts)
    return None


def _kwarg(call: ast.Call, key: str) -> Optional[ast.AST]:
    for kw in call.keywords or []:
        if kw.arg == key:
            return kw.value
    return None


def _is_super_ctor(call: ast.Call) -> bool:
    """True if call is super(...)"""
    return isinstance(call.func, ast.Name) and call.func.id == "super"


def _is_super_method_call(node: ast.AST) -> bool:
    """
    True if node is a Call like: super(...).something(...)
    i.e., Call(func=Attribute(value=Call(func=Name('super'))))
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Call)
        and _is_super_ctor(func.value)
    )


class OdooFieldNameChecker:
    name = "odoo-field-naming"
    version = "0.3.0"

    def __init__(self, tree: ast.AST, filename: str = None):
        self.tree = tree
        self.filename = filename

    # -------- Field Assign checks --------
    def _validate_field_name(self, field_type: str, name: str) -> Optional[str]:
        if field_type not in FIELD_RULES:
            return None
        code, template = FIELD_RULES[field_type]

        if field_type == "Boolean":
            if not name.startswith("is_"):
                return f"{code} " + template.format(name=name)
        elif field_type == "Date":
            if not name.endswith("_date"):
                return f"{code} " + template.format(name=name)
        elif field_type == "Many2one":
            if not name.endswith("_id"):
                return f"{code} " + template.format(name=name)
        elif field_type == "Many2many":
            if not name.endswith("_ids"):
                return f"{code} " + template.format(name=name)
        return None

    def _validate_field_methods(self, field_name: str, call: ast.Call) -> Generator[Tuple[int, int, str, type], None, None]:
        for param, (code, template) in FUNC_RULES.items():
            node = _kwarg(call, param)
            if node is None:
                continue
            s = _literal_str(node)
            if not s:
                continue
            expected = f"_{param}_{field_name}" if param != "search" else f"_search_{field_name}"
            if s != expected:
                yield (node.lineno, node.col_offset, f"{code} " + template.format(name=field_name), type(self))

    # -------- Decorator checks --------
    def _decorator_name(self, dec: ast.AST) -> Optional[Tuple[str, ast.Call]]:
        """
        Return ('onchange'|'constrains', call) if decorator is @api.onchange(...) / @api.constrains(...).
        """
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "api":
                if func.attr in ("onchange", "constrains"):
                    return func.attr, dec
        return None

    def _validate_decorated_func(self, fn: ast.FunctionDef) -> Optional[Tuple[int, int, str]]:
        for dec in fn.decorator_list:
            res = self._decorator_name(dec)
            if not res:
                continue
            kind, _call = res
            code, prefix, template = DECORATOR_PREFIX_RULES[kind]
            if not fn.name.startswith(prefix):
                return (fn.lineno, fn.col_offset, f"{code} " + template.format(func=fn.name))
            if kind == "onchange" and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                first_field = dec.args[0].value
                required = f"{prefix}{first_field}"
                if not fn.name.startswith(required):
                    return (fn.lineno, fn.col_offset, f"{code} Method '{fn.name}' should start with '{required}'")
        return None

    # -------- super() return checks --------
    def _validate_super_return(self, fn: ast.FunctionDef) -> Optional[Tuple[int, int, str]]:
        """
        ถ้าในเมธอดมีการเรียก super().xxx(...):
          - ต้องมี return super(...).xxx(...)  หรือ
          - ต้อง assign ผลลัพธ์ super(...) ให้ตัวแปร แล้วมี return <ตัวแปร> ภายหลัง
        มิฉะนั้นฟ้อง ODN120
        """
        super_assigned_names: Set[str] = set()
        has_super_call_any = False
        has_valid_return = False

        returned_names: Set[str] = set()

        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and node.value is not None:
                if _is_super_method_call(node.value):
                    has_valid_return = True
                elif isinstance(node.value, ast.Name):
                    returned_names.add(node.value.id)

            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _is_super_method_call(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        super_assigned_names.add(t.id)

            if isinstance(node, ast.Call) and _is_super_method_call(node):
                has_super_call_any = True

        if not has_super_call_any:
            return None

        if returned_names & super_assigned_names:
            has_valid_return = True

        if not has_valid_return:
            code, msg = SUPER_RULE
            return (fn.lineno, fn.col_offset, f"{code} " + msg.format(func=fn.name))
        return None

    def run(self) -> Generator[Tuple[int, int, str, type], None, None]:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign):
                field_type, call = _is_fields_call(node.value)
                if not field_type:
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        fname = target.id
                        msg = self._validate_field_name(field_type, fname)
                        if msg:
                            yield (node.lineno, node.col_offset, msg, type(self))
                        for err in self._validate_field_methods(fname, call):
                            yield err

            if isinstance(node, ast.AnnAssign) and node.value is not None:
                field_type, call = _is_fields_call(node.value)
                if field_type and isinstance(node.target, ast.Name):
                    fname = node.target.id
                    msg = self._validate_field_name(field_type, fname)
                    if msg:
                        yield (node.lineno, node.col_offset, msg, type(self))
                    for err in self._validate_field_methods(fname, call):
                        yield err

        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                res = self._validate_decorated_func(node)
                if res:
                    line, col, msg = res
                    yield (line, col, msg, type(self))
                res2 = self._validate_super_return(node)
                if res2:
                    line, col, msg = res2
                    yield (line, col, msg, type(self))
