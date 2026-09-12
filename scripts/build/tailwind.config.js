/** @type {import('tailwindcss').Config} */
const path = require('path');

module.exports = {
  content: [
    path.join(__dirname, '../../templates/**/*.html'),
    path.join(__dirname, '../../static/js/**/*.js'),
  ],
  theme: {
    extend: {
      colors: {
        // 浅色主题语义色：forest 为深色控件/描边，gold 为可在白底上清晰阅读的强调色，
        // cream 为正文黑色文本（含透明度即灰色文本）。
        forest: { 900: '#101826', 800: '#1c2738', 700: '#334155', 600: '#475569' },
        gold: { 400: '#0d8bb8', 500: '#6d28d9' },
        cream: '#1c2531',
      },
      fontFamily: {
        sans: ['Noto Sans SC', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
