// T157 — FR-005 static-analysis audit.
//
// Asserts every mutation in `apps/control_panel/lib/` originates from
// `core/daemon/app_client.dart`'s public surface. No UI code may:
//   1. construct `app.*` JSON request envelopes directly,
//   2. invoke `SocketClient.sendRequest(...)` outside `core/daemon/`, or
//   3. mutate Notifier `state` outside `build()` without a preceding
//      `await ref.read(appClientProvider).<method>(...)` call (heuristic).
//
// Run from the `apps/control_panel/` directory:
//   /opt/flutter-3.27.0/bin/dart run tools/audit_no_local_mutation.dart
//
// Exits 0 when clean, 1 when violations are reported.

// ignore_for_file: avoid_print

import 'dart:io';

import 'package:analyzer/dart/analysis/features.dart';
import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';
import 'package:analyzer/source/line_info.dart';

const String _libRoot = 'lib';
const String _appClientFile = 'lib/core/daemon/app_client.dart';
const String _daemonDir = 'lib/core/daemon/';

// Top-level `app.*` method namespaces from app-methods.md. Only these are
// considered protected mutation surfaces; nested config strings under
// other prefixes (e.g. `app.settings.foo` from a hypothetical future
// surface) would need to be added here when added to AppClient.
const List<String> _appMethodNamespaces = <String>[
  'agent',
  'log',
  'send_input',
  'queue',
  'route',
  'scan',
  'handoff',
  'drift',
  'validation',
  'notification',
  'project',
];

class Violation {
  Violation({
    required this.file,
    required this.line,
    required this.column,
    required this.kind,
    required this.message,
    this.severity = 'error',
  });

  final String file;
  final int line;
  final int column;
  final String kind;
  final String message;
  final String severity;

  @override
  String toString() =>
      '$file:$line:$column  [$severity:$kind] $message';
}

void main(List<String> args) {
  final cwd = Directory.current.path;
  final libDir = Directory('$cwd/$_libRoot');
  if (!libDir.existsSync()) {
    stderr.writeln(
      'audit_no_local_mutation: expected to run from apps/control_panel/ '
      '(could not find $_libRoot/).',
    );
    exit(2);
  }

  final allFiles = libDir
      .listSync(recursive: true)
      .whereType<File>()
      .where((f) => f.path.endsWith('.dart'))
      .where((f) => !f.path.endsWith('.g.dart'))
      .where((f) => !f.path.endsWith('.freezed.dart'))
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));

  final violations = <Violation>[];

  // ----- Scan 1: string-literal scan for `app.<namespace>` in UI dirs ---
  final namespaceAlt = _appMethodNamespaces.join('|');
  // Match string literals (single or double quoted) starting with `app.`
  // followed by one of the protected namespaces. Trailing `.foo` is
  // accepted (the full method name) but not required.
  final appMethodRe = RegExp(
    "['\"]app\\.($namespaceAlt)(\\.[A-Za-z0-9_]+)?['\"]",
  );

  for (final file in allFiles) {
    final rel = _relPath(file.path, cwd);
    if (!_isUiFile(rel)) continue;
    final content = file.readAsStringSync();
    final lines = content.split('\n');
    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      // Skip pure comment lines so doc references like `// see app.agent.update`
      // don't trip the audit.
      final trimmed = line.trimLeft();
      if (trimmed.startsWith('//') || trimmed.startsWith('///')) continue;
      for (final m in appMethodRe.allMatches(line)) {
        violations.add(
          Violation(
            file: rel,
            line: i + 1,
            column: m.start + 1,
            kind: 'direct-app-method-literal',
            message:
                'UI code references `${m.group(0)}` directly. Route the '
                'call through `AppClient` in core/daemon/app_client.dart.',
          ),
        );
      }
    }
  }

  // ----- Scan 2 + 3: AST scan ------------------------------------------
  for (final file in allFiles) {
    final rel = _relPath(file.path, cwd);
    final parseResult = parseFile(
      path: file.absolute.path,
      featureSet: FeatureSet.latestLanguageVersion(),
      throwIfDiagnostics: false,
    );
    if (parseResult.errors.isNotEmpty) {
      stderr.writeln(
        'warn: $rel — ${parseResult.errors.length} parse diagnostic(s); '
        'continuing best-effort.',
      );
    }

    final unit = parseResult.unit;
    final lineInfo = parseResult.lineInfo;

    // Scan 2: SocketClient.sendRequest outside core/daemon/
    if (!_isInDaemonCore(rel)) {
      final v2 = _SendRequestVisitor(rel, lineInfo);
      unit.accept(v2);
      violations.addAll(v2.violations);
    }

    // Scan 3: provider state-setter heuristic, only in features/.
    if (rel.startsWith('lib/features/')) {
      final v3 = _NotifierStateMutationVisitor(rel, lineInfo);
      unit.accept(v3);
      violations.addAll(v3.violations);
    }
  }

  // ----- Report --------------------------------------------------------
  if (violations.isEmpty) {
    stdout.writeln('audit_no_local_mutation: OK — no violations.');
    stdout.writeln('  files scanned: ${allFiles.length}');
    exit(0);
  }

  // Group by file for readability.
  violations.sort((a, b) {
    final c = a.file.compareTo(b.file);
    if (c != 0) return c;
    return a.line.compareTo(b.line);
  });

  stdout.writeln('audit_no_local_mutation: violations found.');
  stdout.writeln('');
  String? lastFile;
  for (final v in violations) {
    if (v.file != lastFile) {
      stdout.writeln('-- ${v.file}');
      lastFile = v.file;
    }
    stdout.writeln(
      '   ${v.line}:${v.column}  [${v.severity}:${v.kind}] ${v.message}',
    );
  }
  stdout.writeln('');

  final errorCount = violations.where((v) => v.severity == 'error').length;
  final reviewCount = violations.where((v) => v.severity == 'review').length;
  stdout.writeln(
    'summary: ${violations.length} total '
    '($errorCount error, $reviewCount review); '
    'files scanned: ${allFiles.length}',
  );
  exit(errorCount > 0 ? 1 : 0);
}

bool _isUiFile(String relPath) {
  return relPath.startsWith('lib/features/') || relPath.startsWith('lib/ui/');
}

bool _isInDaemonCore(String relPath) {
  return relPath.startsWith(_daemonDir) || relPath == _appClientFile;
}

String _relPath(String absPath, String cwd) {
  final prefix = '$cwd/';
  if (absPath.startsWith(prefix)) {
    return absPath.substring(prefix.length);
  }
  return absPath;
}

// ---------------------------------------------------------------------------
// Scan 2: every `SocketClient.sendRequest(...)` invocation outside
// `lib/core/daemon/`. We match on the identifier `sendRequest` invoked on
// a target whose static name is `SocketClient` (best-effort syntactic match,
// since we are not running a full resolution).
// ---------------------------------------------------------------------------

class _SendRequestVisitor extends RecursiveAstVisitor<void> {
  _SendRequestVisitor(this.file, this.lineInfo);

  final String file;
  final LineInfo lineInfo;
  final List<Violation> violations = <Violation>[];

  @override
  void visitMethodInvocation(MethodInvocation node) {
    if (node.methodName.name == 'sendRequest') {
      final target = node.target;
      // Flag any `something.sendRequest(...)` where `something` could
      // plausibly be a SocketClient. We can't easily distinguish without
      // full element resolution, so flag everything outside daemon/ that
      // calls `.sendRequest` — there are no other `sendRequest` methods
      // in this codebase by convention.
      final loc = lineInfo.getLocation(node.offset);
      violations.add(
        Violation(
          file: file,
          line: loc.lineNumber,
          column: loc.columnNumber,
          kind: 'socket-sendrequest-outside-core',
          message:
              'Direct `${target?.toSource() ?? '<unknown>'}.sendRequest(...)` '
              'call outside `lib/core/daemon/`. All daemon I/O MUST go '
              'through `AppClient` (FR-005).',
        ),
      );
    }
    super.visitMethodInvocation(node);
  }
}

// ---------------------------------------------------------------------------
// Scan 3: provider state-setter heuristic.
//
// For every class in `lib/features/**` that extends a Riverpod
// *Notifier* type, walk the body for `state = ...` assignments. Flag for
// human review unless:
//   (a) the assignment is inside the class's `build()` method, OR
//   (b) within the same statement-block, an earlier statement contains
//       `await ref.read(appClientProvider).<anything>(...)` (or
//       `await ref.read(appClientProvider).<anything>` — heuristic).
//
// This is a heuristic, surfaced as severity=review, not a hard fail.
// Severity counts: violations with severity != 'error' do NOT push the
// exit code to 1, but ARE printed for human inspection.
// ---------------------------------------------------------------------------

class _NotifierStateMutationVisitor extends RecursiveAstVisitor<void> {
  _NotifierStateMutationVisitor(this.file, this.lineInfo);

  final String file;
  final LineInfo lineInfo;
  final List<Violation> violations = <Violation>[];

  static const Set<String> _notifierBaseTypes = <String>{
    'Notifier',
    'AsyncNotifier',
    'FamilyNotifier',
    'FamilyAsyncNotifier',
    'AutoDisposeNotifier',
    'AutoDisposeAsyncNotifier',
    'AutoDisposeFamilyNotifier',
    'AutoDisposeFamilyAsyncNotifier',
    'StateNotifier',
  };

  @override
  void visitClassDeclaration(ClassDeclaration node) {
    final ext = node.extendsClause?.superclass;
    final baseName = ext?.name2.lexeme;
    if (baseName == null || !_notifierBaseTypes.contains(baseName)) {
      // Not a Notifier — skip; don't even recurse into methods, the
      // FR-005 invariant only applies to provider state writers.
      return;
    }

    for (final member in node.members) {
      if (member is MethodDeclaration) {
        if (member.name.lexeme == 'build') {
          // `build()` initializers can freely set state — they ARE the
          // state. Skip.
          continue;
        }
        final visitor = _BodyStateAssignmentVisitor(file, lineInfo);
        member.body.accept(visitor);
        violations.addAll(visitor.violations);
      }
    }
  }
}

class _BodyStateAssignmentVisitor extends RecursiveAstVisitor<void> {
  _BodyStateAssignmentVisitor(this.file, this.lineInfo);

  final String file;
  final LineInfo lineInfo;
  final List<Violation> violations = <Violation>[];

  @override
  void visitBlock(Block node) {
    final stmts = node.statements;
    for (var i = 0; i < stmts.length; i++) {
      final stmt = stmts[i];
      if (_statementAssignsState(stmt)) {
        // Look back over the prior statements in this block for an
        // `await ref.read(appClientProvider).<method>(...)` call.
        final hasPriorAppClientCall = stmts
            .sublist(0, i)
            .any(_statementInvokesAppClient);
        if (!hasPriorAppClientCall) {
          final loc = lineInfo.getLocation(stmt.offset);
          violations.add(
            Violation(
              file: file,
              line: loc.lineNumber,
              column: loc.columnNumber,
              kind: 'state-mutation-without-app-client',
              message:
                  '`state = ...` assignment outside `build()` with no prior '
                  '`await ref.read(appClientProvider).<method>(...)` in the '
                  'same block. Confirm the source of the new state is the '
                  'daemon (FR-005).',
              severity: 'review',
            ),
          );
        }
      }
    }
    super.visitBlock(node);
  }
}

bool _statementAssignsState(Statement stmt) {
  if (stmt is ExpressionStatement) {
    final expr = stmt.expression;
    if (expr is AssignmentExpression) {
      final lhs = expr.leftHandSide;
      if (lhs is SimpleIdentifier && lhs.name == 'state') {
        return true;
      }
    }
  }
  return false;
}

bool _statementInvokesAppClient(Statement stmt) {
  // Cheap string search of the statement's source.
  final src = stmt.toSource();
  return src.contains('appClientProvider') ||
      src.contains('AppClient') ||
      src.contains('app_client');
}
