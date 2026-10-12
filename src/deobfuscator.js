// 反混淆器：沙箱求值 + AST 常量折叠 + 死代码清除
// 用法:
//   node deob.js <输入.js> <输出.js>                 单文件
//   node deob.js --batch <列表文件>                  批量（每行: 输入路径\t输出路径）
const fs = require('fs');
const vm = require('vm');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const generate = require('@babel/generator').default;
const t = require('@babel/types');

const noop = () => {};
const fakeConsole = { log: noop, error: noop, warn: noop, info: noop, debug: noop, table: noop, trace: noop, dir: noop };

function deobfuscate(code) {
  // ---------- 1) 沙箱执行，拿到全局解码器 ----------
  const sandbox = { console: fakeConsole, Math, JSON, Date, String, Number, Array, Object, parseInt, parseFloat, decodeURIComponent, RegExp, Error };
  sandbox.window = sandbox; sandbox.self = sandbox; sandbox.global = sandbox;
  vm.createContext(sandbox);
  try { vm.runInContext(code, sandbox, { timeout: 15000 }); } catch (e) { /* 自防御异常忽略 */ }

  const fns = {};
  for (const k of Object.keys(sandbox)) {
    if (typeof sandbox[k] !== 'function' || !/^a\d+[A-Za-z]+$/.test(k)) continue;
    let src = '';
    try { src = Function.prototype.toString.call(sandbox[k]); } catch (e) {}
    if (src.includes('constructor') || src.includes('__proto__')) continue;
    fns[k] = sandbox[k];
  }

  // ---------- 2) 解析 AST ----------
  const ast = parser.parse(code, { sourceType: 'script', allowReturnOutsideFunction: true });

  // 字面量求值（兼容 -0x2a8 这类一元负号）
  function litVal(n) {
    if (t.isNumericLiteral(n)) return n.value;
    if (t.isStringLiteral(n)) return n.value;
    if (t.isBooleanLiteral(n)) return n.value;
    if (t.isUnaryExpression(n) && (n.operator === '-' || n.operator === '+') && t.isNumericLiteral(n.argument)) {
      return n.operator === '-' ? -n.argument.value : n.argument.value;
    }
    return undefined;
  }
  const lit = n => litVal(n) !== undefined;

  // 收集局部包装函数（仅限「函数体只有一句 return」的纯转发函数）
  function isPureReturn(fn) {
    if (t.isArrowFunctionExpression(fn)) return t.isExpression(fn.body) || (t.isBlockStatement(fn.body) && fn.body.body.length === 1 && t.isReturnStatement(fn.body.body[0]));
    if (t.isFunctionExpression(fn) && t.isBlockStatement(fn.body)) return fn.body.body.length === 1 && t.isReturnStatement(fn.body.body[0]);
    return false;
  }
  const localSrc = {};
  traverse(ast, {
    VariableDeclarator(p) {
      if (t.isIdentifier(p.node.id) && (t.isFunctionExpression(p.node.init) || t.isArrowFunctionExpression(p.node.init)) && isPureReturn(p.node.init)) {
        localSrc[p.node.id.name] = generate(p.node.init).code;
      }
    },
    FunctionDeclaration(p) {
      if (p.node.id && t.isBlockStatement(p.node.body) && p.node.body.body.length === 1 && t.isReturnStatement(p.node.body.body[0])) {
        localSrc[p.node.id.name] = generate(p.node).code;
      }
    }
  });

  // 局部包装函数互相调用，需在「全局 + 全部局部包装函数」的上下文里编译
  const wrapperCtx = vm.createContext({});
  for (const k of Object.keys(sandbox)) wrapperCtx[k] = sandbox[k];
  for (const [name, src] of Object.entries(localSrc)) {
    try { wrapperCtx[name] = vm.runInContext('(' + src + ')', wrapperCtx); } catch (e) {}
  }
  function resolveFn(name) {
    if (fns[name]) return fns[name];
    if (name in localSrc) return wrapperCtx[name] || null;
    return null;
  }

  // ---------- 3) 常量折叠 ----------
  let changed = true, guard = 0;
  while (changed && guard++ < 60) {
    changed = false;
    traverse(ast, {
      CallExpression(path) {
        const c = path.node.callee;
        if (!t.isIdentifier(c)) return;
        const args = path.node.arguments;
        if (!args.length || !args.every(lit)) return;
        const fn = resolveFn(c.name);
        if (!fn) return;
        try {
          const v = fn(...args.map(litVal));
          if (typeof v === 'string') { path.replaceWith(t.stringLiteral(v)); changed = true; }
          else if (typeof v === 'number') { path.replaceWith(t.numericLiteral(v)); changed = true; }
        } catch (e) {}
      },
      BinaryExpression(path) {
        const { left, right, operator } = path.node;
        if (!lit(left) || !lit(right)) return;
        const lv = litVal(left), rv = litVal(right);
        let v;
        if (operator === '+' && (t.isStringLiteral(left) || t.isStringLiteral(right))) {
          v = String(lv) + String(rv);
        } else if (typeof lv === 'number' && typeof rv === 'number') {
          switch (operator) {
            case '+': v = lv + rv; break;
            case '-': v = lv - rv; break;
            case '*': v = lv * rv; break;
            case '/': v = lv / rv; break;
            case '%': v = lv % rv; break;
            case '**': v = lv ** rv; break;
            default: return;
          }
        } else return;
        path.replaceWith(typeof v === 'number' ? t.numericLiteral(v) : t.stringLiteral(v));
        changed = true;
      },
      UnaryExpression(path) {
        if (path.node.operator !== '!') return;
        const arg = path.node.argument;
        let truthy;
        if (t.isArrayExpression(arg)) truthy = true;        // 数组恒为真（含空数组）
        else if (t.isObjectExpression(arg)) truthy = true;
        else if (t.isNumericLiteral(arg)) truthy = arg.value !== 0;
        else if (t.isStringLiteral(arg)) truthy = arg.value.length > 0;
        else if (t.isBooleanLiteral(arg)) truthy = arg.value;
        else if (t.isNullLiteral(arg)) truthy = false;
        else return;
        path.replaceWith(t.booleanLiteral(!truthy));
        changed = true;
      }
    });
  }

  // ---------- 4) 清除局部未引用的函数变量 ----------
  let removedLocal = true, guard3 = 0;
  while (removedLocal && guard3++ < 30) {
    removedLocal = false;
    const refNames = new Set();
    traverse(ast, { Identifier(p) { if (p.isReferencedIdentifier()) refNames.add(p.node.name); } });
    traverse(ast, {
      VariableDeclarator(path) {
        if (!t.isIdentifier(path.node.id)) return;
        const init = path.node.init;
        if (!init || !(t.isFunctionExpression(init) || t.isArrowFunctionExpression(init))) return;
        if (refNames.has(path.node.id.name)) return;
        const parent = path.parentPath;
        path.remove();
        if (t.isVariableDeclaration(parent.node) && parent.node.declarations.length === 0) parent.remove();
        removedLocal = true;
      }
    });
  }

  // ---------- 5) 顶层死代码清除 ----------
  const ENTRY = new Set(['get', 'start', 'action', 'end', 'next']);
  const isObfName = n => /^a\d+[A-Za-z]*$/.test(n);
  function declaredNames(stmt) {
    const names = [];
    if (t.isFunctionDeclaration(stmt) && stmt.id) names.push(stmt.id.name);
    if (t.isVariableDeclaration(stmt)) for (const d of stmt.declarations) if (t.isIdentifier(d.id)) names.push(d.id.name);
    return names;
  }
  let removed = true, guard2 = 0;
  while (removed && guard2++ < 60) {
    removed = false;
    const body = ast.program.body;
    for (let i = body.length - 1; i >= 0; i--) {
      if (t.isExpressionStatement(body[i])) { body.splice(i, 1); removed = true; }
    }
    const refPaths = [];
    traverse(ast, { Identifier(p) { if (p.isReferencedIdentifier()) refPaths.push(p); } });
    for (let i = body.length - 1; i >= 0; i--) {
      const stmt = body[i];
      const names = declaredNames(stmt);
      if (!names.length) continue;
      if (names.some(n => ENTRY.has(n))) continue;
      if (!names.every(isObfName)) continue;
      const related = refPaths.filter(p => names.includes(p.node.name));
      if (related.every(p => !!p.findParent(par => par.node === stmt))) { body.splice(i, 1); removed = true; }
    }
  }

  // ---------- 6) 数值统一输出为十进制 ----------
  traverse(ast, { NumericLiteral(path) { delete path.node.extra; } });

  // ---------- 7) 生成 ----------
  return generate(ast, { comments: false, compact: false, concise: false, jsescOption: { minimal: true } }).code;
}

// ================= 入口 =================
const argv = process.argv;
if (argv[2] === '--batch') {
  const listFile = argv[3];
  const lines = fs.readFileSync(listFile, 'utf8').split(/\r?\n/).filter(Boolean);
  let ok = 0, err = 0;
  for (const line of lines) {
    const idx = line.indexOf('\t');
    const inp = line.slice(0, idx);
    const outp = line.slice(idx + 1);
    try {
      const code = fs.readFileSync(inp, 'utf8');
      fs.writeFileSync(outp, deobfuscate(code), 'utf8');
      ok++;
    } catch (e) {
      err++;
      console.log('FAIL\t' + inp + '\t' + String(e && e.message ? e.message : e));
    }
  }
  console.log('BATCH_DONE\tok=' + ok + '\terr=' + err);
} else {
  const inp = argv[2], outp = argv[3];
  try {
    const code = fs.readFileSync(inp, 'utf8');
    const result = deobfuscate(code);
    fs.writeFileSync(outp, result, 'utf8');
    console.log('OK ' + inp + ' -> ' + outp + ' (' + result.length + ' chars)');
  } catch (e) {
    console.log('FAIL ' + inp + ' : ' + (e && e.message ? e.message : e));
    process.exit(1);
  }
}
