#!/usr/bin/env python3
"""
More accurate static code analysis focusing on real issues
"""

import ast
import os
import sys
import subprocess
from pathlib import Path
from collections import defaultdict
import json

class AccurateAnalyzer:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.issues = []

    def add_issue(self, file_path, line_num, issue_type, description, severity, code=""):
        self.issues.append({
            'file': str(file_path),
            'line': line_num,
            'type': issue_type,
            'description': description,
            'severity': severity,
            'code': code
        })

    def check_syntax_errors(self, file_path):
        """Check for actual syntax errors"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            compile(source, str(file_path), 'exec')
            return True
        except UnicodeDecodeError as e:
            self.add_issue(
                file_path, 0, 'ENCODING_ERROR',
                f"File encoding error: {str(e)}. File is not valid UTF-8.",
                'critical'
            )
            return False
        except SyntaxError as e:
            code = e.text.strip() if e.text else ""
            self.add_issue(
                file_path, e.lineno or 0, 'SYNTAX_ERROR',
                f"{e.msg}",
                'critical',
                code
            )
            return False
        except IndentationError as e:
            code = e.text.strip() if e.text else ""
            self.add_issue(
                file_path, e.lineno or 0, 'INDENTATION_ERROR',
                f"{e.msg}",
                'critical',
                code
            )
            return False
        except Exception as e:
            self.add_issue(
                file_path, 0, 'PARSE_ERROR',
                f"Failed to parse: {str(e)}",
                'critical'
            )
            return False

    def check_imports(self, file_path):
        """Check import statements for issues"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()

            tree = ast.parse(source, filename=str(file_path))

            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({
                            'module': alias.name,
                            'line': node.lineno,
                            'type': 'import'
                        })
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append({
                            'module': node.module,
                            'line': node.lineno,
                            'type': 'from'
                        })

            # Check for missing standard library imports
            for imp in imports:
                module_name = imp['module'].split('.')[0]

                # Try to import to see if it exists
                if module_name not in sys.builtin_module_names:
                    try:
                        __import__(module_name)
                    except ImportError:
                        # Check if it's a local module
                        is_local = self._is_local_module(module_name, file_path)
                        if not is_local:
                            self.add_issue(
                                file_path, imp['line'], 'IMPORT_ERROR',
                                f"Module '{module_name}' may not be installed or does not exist",
                                'high'
                            )
        except:
            pass  # Already caught in syntax check

    def _is_local_module(self, module_name, file_path):
        """Check if module is a local project module"""
        # Check if module directory exists
        possible_paths = [
            self.root_dir / module_name,
            self.root_dir / f"{module_name}.py",
            file_path.parent / module_name,
            file_path.parent / f"{module_name}.py",
        ]

        for path in possible_paths:
            if path.exists():
                return True

        return False

    def check_indentation_consistency(self, file_path):
        """Check for mixed tabs and spaces"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            has_tab_indent = False
            has_space_indent = False

            for line_num, line in enumerate(lines, 1):
                # Only check non-empty lines
                if line.strip():
                    if line.startswith('\t'):
                        has_tab_indent = True
                    elif line.startswith(' '):
                        has_space_indent = True

                    if has_tab_indent and has_space_indent:
                        self.add_issue(
                            file_path, line_num, 'MIXED_INDENTATION',
                            "File mixes tabs and spaces for indentation",
                            'medium',
                            line.rstrip()
                        )
                        return
        except:
            pass

    def check_common_issues(self, file_path):
        """Check for common Python anti-patterns"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()

            tree = ast.parse(source)

            # Check for bare except clauses
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        self.add_issue(
                            file_path, node.lineno, 'BARE_EXCEPT',
                            "Bare except clause - should specify exception type",
                            'medium'
                        )

                # Check for mutable default arguments
                if isinstance(node, ast.FunctionDef):
                    for default in node.args.defaults:
                        if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                            self.add_issue(
                                file_path, node.lineno, 'MUTABLE_DEFAULT',
                                f"Function '{node.name}' has mutable default argument",
                                'medium'
                            )
        except:
            pass

    def analyze_file(self, file_path):
        """Analyze a single Python file"""
        print(f"Analyzing: {file_path}")

        # Check syntax first
        syntax_ok = self.check_syntax_errors(file_path)

        # Only continue with other checks if syntax is OK
        if syntax_ok:
            self.check_imports(file_path)
            self.check_indentation_consistency(file_path)
            self.check_common_issues(file_path)

    def analyze_directory(self, patterns):
        """Analyze all Python files matching patterns"""
        python_files = []

        for pattern in patterns:
            if pattern.endswith('.py'):
                file_path = self.root_dir / pattern
                if file_path.exists():
                    python_files.append(file_path)
            else:
                dir_path = self.root_dir / pattern
                if dir_path.exists() and dir_path.is_dir():
                    python_files.extend(dir_path.rglob('*.py'))

        for file_path in sorted(set(python_files)):
            if '__pycache__' not in str(file_path):
                self.analyze_file(file_path)

    def generate_report(self):
        """Generate comprehensive report"""
        # Sort by severity then file
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        self.issues.sort(key=lambda x: (
            severity_order.get(x['severity'], 4),
            x['file'],
            x['line']
        ))

        # Group by severity
        by_severity = defaultdict(list)
        for issue in self.issues:
            by_severity[issue['severity']].append(issue)

        # Group by type
        by_type = defaultdict(int)
        for issue in self.issues:
            by_type[issue['type']] += 1

        # Print summary
        print("\n" + "="*80)
        print("COMPREHENSIVE STATIC CODE ANALYSIS REPORT")
        print("="*80)
        print(f"\nTotal Issues Found: {len(self.issues)}")

        for severity in ['critical', 'high', 'medium', 'low']:
            if severity in by_severity:
                print(f"  {severity.upper()}: {len(by_severity[severity])}")

        # Print by type
        print("\n" + "="*80)
        print("ISSUES BY TYPE")
        print("="*80)
        for issue_type, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            print(f"  {issue_type}: {count}")

        # Print detailed issues
        print("\n" + "="*80)
        print("DETAILED ISSUES")
        print("="*80)

        current_file = None
        for issue in self.issues:
            if issue['file'] != current_file:
                current_file = issue['file']
                print(f"\n{'='*80}")
                print(f"FILE: {issue['file']}")
                print('='*80)

            print(f"\n  [{issue['severity'].upper()}] Line {issue['line']}: {issue['type']}")
            print(f"    Description: {issue['description']}")
            if issue.get('code'):
                print(f"    Code: {issue['code']}")

        # Save JSON report
        report_path = self.root_dir / 'detailed_analysis_report.json'
        with open(report_path, 'w') as f:
            json.dump({
                'summary': {
                    'total_issues': len(self.issues),
                    'by_severity': {k: len(v) for k, v in by_severity.items()},
                    'by_type': dict(by_type)
                },
                'issues': self.issues
            }, f, indent=2)

        print(f"\n{'='*80}")
        print(f"Full JSON report saved to: {report_path}")
        print("="*80)

        return self.issues

def main():
    root_dir = Path('/home/user/Bitcoiner')

    patterns = [
        'main_trader.py',
        'data/',
        'ml/',
        'trading/',
        'notification/',
        'reporting/',
        'utils/'
    ]

    analyzer = AccurateAnalyzer(root_dir)
    analyzer.analyze_directory(patterns)
    analyzer.generate_report()

if __name__ == '__main__':
    main()
