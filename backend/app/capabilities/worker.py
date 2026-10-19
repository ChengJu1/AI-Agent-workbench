"""Trusted JSON worker. Generated code runs only inside the OS-isolated subprocess."""
import ast
import builtins
import importlib
import json
import resource
import sys

ALLOWED_MODULES = frozenset({"json", "csv", "math", "statistics", "datetime", "decimal", "re", "collections", "itertools", "functools", "string", "unicodedata"})
ALLOWED_BUILTINS = "abs all any bool chr dict divmod enumerate filter float format frozenset int isinstance iter len list map max min next ord pow range repr reversed round set slice sorted str sum tuple zip Exception ValueError TypeError KeyError IndexError ArithmeticError ZeroDivisionError StopIteration".split()


def validate_code(code):
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)):
            raise ValueError("只支持同步函数与数据处理，不支持类、异步或全局变量修改。")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("不能访问私有或特殊名称。")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("不能访问私有或特殊属性。")
        if isinstance(node, ast.Import):
            if any(item.name not in ALLOWED_MODULES for item in node.names):
                raise ValueError("导入了不支持的模块。")
        if isinstance(node, ast.ImportFrom) and (node.level or node.module not in ALLOWED_MODULES or any(item.name.startswith("_") or item.name == "*" for item in node.names)):
            raise ValueError("不支持此导入方式。")
        if isinstance(node, (ast.FunctionDef, ast.Lambda)) and getattr(node, "decorator_list", []):
            raise ValueError("不支持装饰器。")
    if not any(isinstance(node, ast.FunctionDef) and node.name == "run" for node in tree.body):
        raise ValueError("需要定义 run(arguments) 函数。")
    return tree


def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in ALLOWED_MODULES:
        raise ImportError("模块未开放。")
    return importlib.import_module(name)


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    try:
        payload = json.loads(sys.stdin.buffer.read(160001))
        tree = validate_code(payload["code"])
        safe = {name: getattr(builtins, name) for name in ALLOWED_BUILTINS}
        safe["__import__"] = restricted_import
        namespace = {"__builtins__": safe}
        exec(compile(tree, "<generated-method>", "exec"), namespace)
        result = namespace["run"](payload["arguments"])
        text = json.dumps({"ok": True, "result": result}, allow_nan=False)
        if len(text.encode("utf-8")) > 65536:
            raise ValueError("结果超过 64 KB，请减少返回内容。")
    except BaseException as error:
        text = json.dumps({"ok": False, "error": f"{type(error).__name__}: {str(error)[:800]}"})
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
