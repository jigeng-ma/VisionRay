"""防止定义的测试动作未被执行。"""
import ast
from pathlib import Path
import unittest


class TestWiringTests(unittest.TestCase):
    def test_each_nested_action_is_run(self):
        root = Path(__file__).resolve().parents[1] / 'cases'
        missing = []
        for path in root.rglob('test_*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for test in (node for node in tree.body
                         if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')):
                has_action = any(isinstance(node, ast.FunctionDef) and node.name == 'action'
                                 for node in test.body)
                runs_action = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == 'run'
                    and any(isinstance(arg, ast.Name) and arg.id == 'action' for arg in node.args)
                    for node in ast.walk(test)
                )
                if has_action and not runs_action:
                    missing.append(f'{path.relative_to(root.parent)}::{test.name}')
        self.assertEqual([], missing, '定义 action 但未执行：' + ', '.join(missing))


if __name__ == '__main__':
    unittest.main()
