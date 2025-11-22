#!/usr/bin/env python3
"""
Comprehensive Static Code Analysis Tool
Checks for syntax errors, import issues, undefined variables, type errors, and indentation issues.
"""

import ast
import os
import sys
import importlib.util
from pathlib import Path
from typing import List, Dict, Set, Tuple
import json
import re

class CodeAnalyzer:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.issues = []
        self.file_imports = {}  # Track imports per file
        self.import_graph = {}  # Track import dependencies

    def add_issue(self, file_path: str, line_num: int, issue_type: str,
                  description: str, severity: str, code_snippet: str = ""):
        self.issues.append({
            'file': file_path,
            'line': line_num,
            'type': issue_type,
            'description': description,
            'severity': severity,
            'code': code_snippet
        })

    def check_syntax(self, file_path: Path) -> bool:
        """Check for syntax errors by compiling the file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()

            # Try to compile
            compile(source, str(file_path), 'exec')

            # Also try to parse as AST
            ast.parse(source, filename=str(file_path))
            return True

        except SyntaxError as e:
            self.add_issue(
                str(file_path),
                e.lineno or 0,
                'SYNTAX_ERROR',
                f"Syntax error: {e.msg}",
                'critical',
                e.text or ""
            )
            return False
        except IndentationError as e:
            self.add_issue(
                str(file_path),
                e.lineno or 0,
                'INDENTATION_ERROR',
                f"Indentation error: {e.msg}",
                'critical',
                e.text or ""
            )
            return False
        except Exception as e:
            self.add_issue(
                str(file_path),
                0,
                'PARSE_ERROR',
                f"Failed to parse file: {str(e)}",
                'critical'
            )
            return False

    def check_indentation(self, file_path: Path):
        """Check for inconsistent indentation (mixing tabs and spaces)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            has_tabs = False
            has_spaces = False

            for line_num, line in enumerate(lines, 1):
                if line.startswith('\t'):
                    has_tabs = True
                elif line.startswith(' '):
                    has_spaces = True

                if has_tabs and has_spaces:
                    self.add_issue(
                        str(file_path),
                        line_num,
                        'INDENTATION_INCONSISTENCY',
                        "File mixes tabs and spaces for indentation",
                        'medium',
                        line.rstrip()
                    )
                    break

        except Exception as e:
            pass

    def analyze_imports(self, file_path: Path, tree: ast.AST):
        """Analyze imports for issues."""
        imports = []
        imported_names = set()
        used_names = set()

        # Collect all imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append({
                        'type': 'import',
                        'module': alias.name,
                        'name': name,
                        'line': node.lineno
                    })
                    imported_names.add(name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        if alias.name == '*':
                            continue
                        name = alias.asname if alias.asname else alias.name
                        imports.append({
                            'type': 'from_import',
                            'module': node.module,
                            'name': name,
                            'line': node.lineno
                        })
                        imported_names.add(name)

        # Collect all name usage
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)

        # Check for unused imports
        for imp in imports:
            if imp['name'] not in used_names:
                # Exception for common imports that might be used indirectly
                if imp['name'] not in ['logging', 'os', 'sys', 'Path', 'Optional',
                                       'List', 'Dict', 'Any', 'Tuple', 'Union']:
                    self.add_issue(
                        str(file_path),
                        imp['line'],
                        'UNUSED_IMPORT',
                        f"Import '{imp['name']}' is never used",
                        'low'
                    )

        self.file_imports[str(file_path)] = imports

        # Build import graph for circular dependency detection
        relative_path = str(file_path.relative_to(self.root_dir))
        module_name = relative_path.replace('/', '.').replace('.py', '')

        dependencies = []
        for imp in imports:
            if imp['type'] == 'import':
                dependencies.append(imp['module'])
            elif imp['type'] == 'from_import':
                dependencies.append(imp['module'])

        self.import_graph[module_name] = dependencies

    def check_undefined_variables(self, file_path: Path, tree: ast.AST):
        """Check for undefined variables."""

        class NameVisitor(ast.NodeVisitor):
            def __init__(self):
                self.scopes = [set()]  # Stack of scopes
                self.undefined = []

            def visit_FunctionDef(self, node):
                # New scope for function
                self.scopes.append(set())

                # Add function parameters to scope
                for arg in node.args.args:
                    self.scopes[-1].add(arg.arg)

                # Visit function body
                self.generic_visit(node)

                # Pop scope
                self.scopes.pop()

            def visit_ClassDef(self, node):
                # Add class name to current scope
                self.scopes[-1].add(node.name)

                # New scope for class
                self.scopes.append(set())

                # Visit class body
                self.generic_visit(node)

                # Pop scope
                self.scopes.pop()

            def visit_Assign(self, node):
                # Add assigned names to current scope
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.scopes[-1].add(target.id)
                    elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                self.scopes[-1].add(elt.id)

                # Visit the value being assigned
                self.visit(node.value)

            def visit_AnnAssign(self, node):
                # Annotated assignment
                if isinstance(node.target, ast.Name):
                    self.scopes[-1].add(node.target.id)
                if node.value:
                    self.visit(node.value)

            def visit_For(self, node):
                # Add loop variable to scope
                if isinstance(node.target, ast.Name):
                    self.scopes[-1].add(node.target.id)
                elif isinstance(node.target, (ast.Tuple, ast.List)):
                    for elt in node.target.elts:
                        if isinstance(elt, ast.Name):
                            self.scopes[-1].add(elt.id)

                self.generic_visit(node)

            def visit_With(self, node):
                # Add context manager variables to scope
                for item in node.items:
                    if item.optional_vars:
                        if isinstance(item.optional_vars, ast.Name):
                            self.scopes[-1].add(item.optional_vars.id)

                self.generic_visit(node)

            def visit_ExceptHandler(self, node):
                # Add exception variable to scope
                if node.name:
                    self.scopes.append(set([node.name]))
                    self.generic_visit(node)
                    self.scopes.pop()
                else:
                    self.generic_visit(node)

            def visit_Name(self, node):
                # Check if name is being loaded (used)
                if isinstance(node.ctx, ast.Load):
                    # Check if defined in any scope
                    defined = any(node.id in scope for scope in self.scopes)

                    # Check if it's a builtin
                    is_builtin = node.id in dir(__builtins__)

                    if not defined and not is_builtin:
                        self.undefined.append((node.id, node.lineno))

                self.generic_visit(node)

        visitor = NameVisitor()
        visitor.visit(tree)

        # Report undefined variables
        for name, line in visitor.undefined:
            # Filter out some common false positives
            if name not in ['self', 'cls', '__name__', '__file__']:
                self.add_issue(
                    str(file_path),
                    line,
                    'UNDEFINED_VARIABLE',
                    f"Variable '{name}' may be used before definition",
                    'high'
                )

    def check_type_errors(self, file_path: Path, tree: ast.AST):
        """Check for obvious type errors."""

        class TypeChecker(ast.NodeVisitor):
            def __init__(self, analyzer):
                self.analyzer = analyzer
                self.file_path = file_path

            def visit_BinOp(self, node):
                # Check for obvious type mismatches in binary operations
                if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                    left_type = type(node.left.value)
                    right_type = type(node.right.value)

                    # String + Number
                    if isinstance(node.op, ast.Add):
                        if (left_type == str and right_type in [int, float]) or \
                           (right_type == str and left_type in [int, float]):
                            self.analyzer.add_issue(
                                str(self.file_path),
                                node.lineno,
                                'TYPE_ERROR',
                                "Cannot concatenate string and number",
                                'high'
                            )

                self.generic_visit(node)

            def visit_Call(self, node):
                # Check for common type errors in function calls
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id

                    # Check len() called on non-sequence
                    if func_name == 'len':
                        if len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
                            if isinstance(node.args[0].value, (int, float)):
                                self.analyzer.add_issue(
                                    str(self.file_path),
                                    node.lineno,
                                    'TYPE_ERROR',
                                    "len() called on numeric constant",
                                    'high'
                                )

                self.generic_visit(node)

        checker = TypeChecker(self)
        checker.visit(tree)

    def detect_circular_imports(self):
        """Detect circular import dependencies."""

        def has_cycle(node, visited, rec_stack, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            if node in self.import_graph:
                for neighbor in self.import_graph[node]:
                    # Convert module name to file-like format
                    neighbor_parts = neighbor.split('.')

                    if neighbor not in visited:
                        if has_cycle(neighbor, visited, rec_stack, path):
                            return True
                    elif neighbor in rec_stack:
                        # Found a cycle
                        cycle_start = path.index(neighbor)
                        cycle = path[cycle_start:] + [neighbor]
                        self.add_issue(
                            "",
                            0,
                            'CIRCULAR_IMPORT',
                            f"Circular import detected: {' -> '.join(cycle)}",
                            'high'
                        )
                        return True

            path.pop()
            rec_stack.remove(node)
            return False

        visited = set()
        for node in self.import_graph:
            if node not in visited:
                has_cycle(node, visited, set(), [])

    def analyze_file(self, file_path: Path):
        """Perform complete analysis on a single file."""
        print(f"Analyzing: {file_path}")

        # Check syntax and indentation
        if not self.check_syntax(file_path):
            return  # Can't continue if syntax is invalid

        self.check_indentation(file_path)

        # Parse AST for deeper analysis
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()

            tree = ast.parse(source, filename=str(file_path))

            # Perform various checks
            self.analyze_imports(file_path, tree)
            self.check_undefined_variables(file_path, tree)
            self.check_type_errors(file_path, tree)

        except Exception as e:
            print(f"  Error during analysis: {e}")

    def analyze_directory(self, patterns: List[str]):
        """Analyze all Python files matching patterns."""
        python_files = []

        # Collect all Python files
        for pattern in patterns:
            if pattern.endswith('.py'):
                file_path = self.root_dir / pattern
                if file_path.exists():
                    python_files.append(file_path)
            else:
                # Directory pattern
                dir_path = self.root_dir / pattern
                if dir_path.exists() and dir_path.is_dir():
                    python_files.extend(dir_path.rglob('*.py'))

        # Analyze each file
        for file_path in sorted(set(python_files)):
            if '__pycache__' not in str(file_path):
                self.analyze_file(file_path)

        # Check for circular imports
        print("\nChecking for circular imports...")
        self.detect_circular_imports()

    def generate_report(self):
        """Generate analysis report."""
        # Sort issues by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        self.issues.sort(key=lambda x: (severity_order.get(x['severity'], 4), x['file'], x['line']))

        # Group by severity
        by_severity = {}
        for issue in self.issues:
            severity = issue['severity']
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(issue)

        # Print report
        print("\n" + "="*80)
        print("STATIC CODE ANALYSIS REPORT")
        print("="*80)
        print(f"\nTotal Issues Found: {len(self.issues)}")

        for severity in ['critical', 'high', 'medium', 'low']:
            if severity in by_severity:
                print(f"\n{severity.upper()}: {len(by_severity[severity])} issues")

        print("\n" + "="*80)
        print("DETAILED ISSUES")
        print("="*80)

        current_file = None
        for issue in self.issues:
            if issue['file'] != current_file:
                current_file = issue['file']
                print(f"\n{'='*80}")
                print(f"File: {issue['file']}")
                print('='*80)

            print(f"\n[{issue['severity'].upper()}] Line {issue['line']}: {issue['type']}")
            print(f"  {issue['description']}")
            if issue.get('code'):
                print(f"  Code: {issue['code'].strip()}")

        print("\n" + "="*80)
        print("SUMMARY BY TYPE")
        print("="*80)

        by_type = {}
        for issue in self.issues:
            itype = issue['type']
            if itype not in by_type:
                by_type[itype] = 0
            by_type[itype] += 1

        for itype, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            print(f"  {itype}: {count}")

        # Save to JSON
        with open('/home/user/Bitcoiner/analysis_report.json', 'w') as f:
            json.dump(self.issues, f, indent=2)

        print("\n" + "="*80)
        print(f"Full report saved to: /home/user/Bitcoiner/analysis_report.json")
        print("="*80)


def main():
    root_dir = '/home/user/Bitcoiner'

    patterns = [
        'main_trader.py',
        'data/',
        'ml/',
        'trading/',
        'notification/',
        'reporting/',
        'utils/'
    ]

    analyzer = CodeAnalyzer(root_dir)
    analyzer.analyze_directory(patterns)
    analyzer.generate_report()


if __name__ == '__main__':
    main()
