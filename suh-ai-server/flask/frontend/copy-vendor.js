/* 빌드 시 벤더 JS를 static으로 복사 (CDN 의존 제거) */
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, 'node_modules', 'lucide', 'dist', 'umd', 'lucide.min.js');
const destDir = path.join(__dirname, '..', 'static', 'js', 'vendor');
fs.mkdirSync(destDir, { recursive: true });
fs.copyFileSync(src, path.join(destDir, 'lucide.min.js'));
console.log('copied: static/js/vendor/lucide.min.js');
