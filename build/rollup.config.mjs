// 把 src/deobfuscator.js（依赖 @babel/*）打包成单文件 assets/deob_bundle.js
// 用法：cd build && npm install && npm run bundle
import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import json from '@rollup/plugin-json';

export default {
  input: '../src/deobfuscator.js',
  output: {
    file: '../assets/deob_bundle.js',
    format: 'cjs',
    exports: 'auto',
  },
  plugins: [
    json(),
    resolve({ preferBuiltins: true }),
    commonjs(),
  ],
  onwarn: () => {},
};
