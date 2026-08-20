/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        forest: { 900: '#242b38', 800: '#30394a', 700: '#465268', 600: '#5a6882' },
        gold: { 400: '#67e8f9', 500: '#8b5cf6' },
        cream: '#f3f6fb',
      },
      fontFamily: {
        sans: ['Noto Sans SC', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
